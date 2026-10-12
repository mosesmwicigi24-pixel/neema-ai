import Foundation

/// A failed call carrying the user-facing message (`shown`: the call card already says it).
public struct CallError: Error, Equatable, LocalizedError {
    public let message: String
    public let shown: Bool
    public init(_ message: String, shown: Bool = false) { self.message = message; self.shown = shown }
    public var errorDescription: String? { message }
}

/// The agent refused the microphone (or the prompt went unanswered for a minute).
public struct MicBlockedError: Error, Equatable {
    public init() {}
}

/// The device couldn't set the call up (the audio stack, WebRTC's native side):
/// the platform media layer throws it so the card says `DEVICE_CALL_FAILED`.
public struct DeviceCallError: Error {
    public let detail: String
    public init(_ detail: String) { self.detail = detail }
}

/// The softphone (WhatsApp and Messenger — CALLING_UX.md §2.0: a Messenger
/// call's SDP runs the other way, see `answer` / `placeMessenger` /
/// `media_update`): incoming-call ringing, answer / decline / callback,
/// outbound calls, mute, audio routes, the wrap-up after a call, and call
/// recording — the port of lib/callContext.tsx, grown into docs/CALLING_UX.md,
/// one rule for one rule with Android's `feature/calls/CallManager.kt`.
/// Process-wide (lives in the app container) so a call survives navigating
/// between screens.
///
/// This class is the rules and nothing else: the device side (WebRTC, audio
/// routing, ringtone, CallKit, the mic permission) arrives through the
/// protocols in CallPorts.swift, so every rule here runs on Linux in tests.
///
/// PUBLIC CONTRACT — other features call only `state`, `permissionGranted`,
/// `initiateCall`, `requestPermission`, `hangup`, `openChat` and (CallKit)
/// `handleAction`; the call card and bar call the rest.
///
/// Threading: every state change runs on the main actor; peer events and
/// socket frames hop there first.
///
/// Microphone: the same moment the browser asks inside getUserMedia raises
/// `micRequest`; the call card shows the system prompt and reports back
/// through `onMicResult`. Refused (or unanswered for a minute), the call ends
/// with "Microphone blocked".
///
/// Several agents, one call (CALLING_UX.md §4): ringing stops here the moment
/// `call_answered` (a colleague — "Answered by Ann"), `call_ended` (its
/// outcome), a poll that finds the row not ringing, or our own 409 / 410
/// arrives. After the socket reconnects or the app returns to the front, a
/// phone that shows a call re-reads its row (`resync`) and corrects itself.
///
/// The wrap-up (`.ended`) stays until the agent acts when the team still owes
/// the customer something (missed, no answer, dropped, failed, permission);
/// neutral ones close by themselves (`CallOutcome.autoCloseMs`). A new ring
/// replaces it at once. A second caller during a live call is a
/// `CallUiState.waiting` banner — never a take-over.
///
/// Every deliberate difference from the web listed on the Android class holds
/// here too (a `call_ended` frame ends the call properly; an outbound call hung
/// up while Meta was placing it is terminated; double taps on an ended call are
/// ignored; a 409 on answer never terminates the colleague's call; the poll
/// keeps running in the background and only rings for INBOUND rows; missed
/// frames are caught up on every reconnect and return to the front; a caller
/// who rang in during a live call is looked for the moment it ends; a
/// `call_ended` for a call never shown starts its cooldown; the poll cadence
/// switches the moment ringing starts; an early `outbound_answer` is kept and
/// applied once the id is known; ringing stops after `RING_TIMEOUT_MS`; a
/// refused microphone ends the call on this phone only), and so does every
/// network rule (a "disconnected" peer is a blip with `ICE_GRACE_MS` to
/// recover; hang-up ends the call at once and terminates in the background
/// with retries; an answer or outbound call whose request timed out may still
/// have gone through; an answer that couldn't even start leaves the call
/// ringing; the callback note says saved only once the server said so;
/// recordings wait on disk in `RecordingOutbox`).
@MainActor
public final class CallManager {
    // ── Constants ─────────────────────────────────────────────────────────
    nonisolated public static let MIC_BLOCKED = "Microphone blocked — allow it and try again"
    /// WebRTC couldn't start (or lost) the microphone: another app has it, or the device refused.
    nonisolated public static let MIC_UNAVAILABLE = "The microphone isn't working — close any app using it (a screen recorder), then hang up and call again"
    nonisolated public static let SPEAKER_UNAVAILABLE = "The call audio stopped on this device — hang up and call again"
    nonisolated public static let DEVICE_CALL_FAILED = "This device couldn't start the call — try again, or call from another phone"
    /// The wrap-up's words for a refused microphone (its button opens the settings).
    nonisolated public static let MIC_BLOCKED_WRAP = "Microphone blocked — allow it in settings"
    nonisolated public static let NO_CALL_PERMISSION = "This customer hasn't allowed WhatsApp calls yet — send them a call request"
    nonisolated public static let RING_POLL_MS: Int64 = 2_500
    nonisolated public static let IDLE_POLL_MS: Int64 = 12_000
    nonisolated public static let RERING_COOLDOWN_MS: Int64 = 12_000
    nonisolated public static let GATHER_TIMEOUT_MS: Int64 = 2_500
    nonisolated public static let MIC_PROMPT_TIMEOUT_MS: Int64 = 60_000
    nonisolated public static let MIN_RECORDING_BYTES: Int64 = 2_000
    /// Ended calls remembered before old ones are dropped (`markEnded`).
    nonisolated public static let ENDED_MAX = 256
    /// An ended call older than this is past every use of `endedAt`.
    nonisolated public static let ENDED_KEEP_MS: Int64 = 10 * 60_000
    /// routers/admin.py list_calls marks a call still "ringing" after 2 minutes as missed.
    nonisolated public static let RING_TIMEOUT_MS: Int64 = 120_000

    nonisolated public static let TAKEN_ELSEWHERE = "Another agent already answered this call"
    nonisolated public static let CALL_GONE = "This call has already ended"
    nonisolated public static let ANSWER_OFFLINE = "No connection — couldn't answer the call"
    nonisolated public static let ANSWER_SLOW = "The server took too long — couldn't connect the call"
    /// An answer that never left this phone: the call still rings and Answer stays live.
    nonisolated public static let ANSWER_NO_CONNECTION = "No connection — can't answer yet"
    nonisolated public static let ANSWER_SLOW_RETRY = "The server is slow — tap Answer to try again"
    nonisolated public static let OUTBOUND_OFFLINE = "No connection — the call wasn't placed"
    /// Our answer reached the server but its reply (and the audio) never came back.
    nonisolated public static let ANSWER_DROPPED = "The connection dropped while answering — call them back"
    /// Answered, but no audio ever flowed.
    nonisolated public static let AUDIO_NOT_CONNECTED = "The call audio couldn't connect"
    /// Meta's answer to our offer couldn't be applied.
    nonisolated public static let AUDIO_SETUP_FAILED = "Couldn't set up the call audio"
    /// 409 `messenger_calling_off` with no sentence of its own.
    nonisolated public static let MESSENGER_OFF = "Messenger calling is switched off — call them on WhatsApp instead."
    /// Under "{First} hasn't allowed WhatsApp calls yet" (CallStage.tsx).
    nonisolated public static let PERMISSION_EXPLAINED =
        "WhatsApp only lets a business call someone who allowed it. The request is a WhatsApp message with an Allow button."
    /// The same for Messenger (CallStage.tsx).
    nonisolated public static let PERMISSION_EXPLAINED_MESSENGER =
        "Messenger only lets a business call someone who accepted a call request. The request is a Messenger message with Accept and Decline buttons."
    nonisolated public static let OUTBOUND_SLOW = "The server took too long — couldn't place the call"
    /// connect timed out and no placed call turned up: it may still be ringing them.
    nonisolated public static let UNCONFIRMED_CALL = "Couldn't confirm the call went through — check Calls before trying again"
    nonisolated public static let CALL_NOT_CONNECTED = "The call couldn't be connected"
    nonisolated public static let SESSION_EXPIRED = "Your session expired — sign in again"
    nonisolated public static let CALLBACK_SAVED = "Saved to call back — find it under Calls"
    nonisolated public static let CALLBACK_RETRYING = "Callback not saved yet — retrying"
    nonisolated public static let CALLBACK_FAILED = "Couldn't save the callback"
    nonisolated public static let RECORDING_SAVED_AUTO = "Recording saved — summary in a minute"
    nonisolated public static let RECORDING_SAVED_MANUAL = "Recording saved — Transcribe from Calls"
    nonisolated public static let RECORDING_SAVED = "Recording saved"
    /// Nothing recorded here, but WhatsApp records and transcribes the call itself.
    nonisolated public static let META_SUMMARY = "Recorded by WhatsApp — summary in a minute"
    /// A refusal whose `action` is admin: no Try again.
    nonisolated public static let ADMIN_MUST_ACT = "An admin needs to fix this — trying again won't help."
    /// `action` wait with no time given.
    nonisolated public static let WAIT_A_MOMENT = "Wait a little before trying again."
    /// `action` none: calling won't work — write to them.
    nonisolated public static let MESSAGE_INSTEAD = "Send them a message instead."
    /// How long the permission read may hold up placing a call.
    nonisolated public static let PERMISSION_READ_MS: Int64 = 1_500
    /// How long a "disconnected" call may take to recover before it is ended.
    nonisolated public static let ICE_GRACE_MS: Int64 = 10_000
    /// How long an answer whose request timed out may take to connect anyway.
    nonisolated public static let ANSWER_CONFIRM_MS: Int64 = 8_000
    /// How long "Connecting…" may last once the call was answered (callContext CONNECT_GUARD_MS).
    nonisolated public static let CONNECT_GUARD_MS: Int64 = 20_000
    /// Waits between the terminate / callback retries.
    nonisolated public static let TERMINATE_RETRY_MS: [Int64] = [2_000, 5_000]
    nonisolated public static let PLACED_LOOKUP_GAP_MS: Int64 = 3_000
    /// How long sign-out waits for a live call's terminate before clearing the session anyway.
    nonisolated public static let SIGN_OUT_TERMINATE_MS: Int64 = 3_000
    /// The server's clock vs this phone's, when matching the row an outbound call created.
    nonisolated public static let CLOCK_SKEW_MS: Int64 = 120_000
    /// The phases with the call's audio set up (the voice session, the route).
    nonisolated static let AUDIO_PHASES: Set<CallPhase> = [.placing, .ringingOut, .connecting, .inCall]
    /// Debug lines ("WS event: …"), when the app wires a logger.
    nonisolated(unsafe) public static var debugLog: ((String) -> Void)?

    // ── Wiring ────────────────────────────────────────────────────────────
    private let api: CallApi
    private let events: Signal<JSONValue>
    private let connected: Watched<Bool>
    private let foreground: Watched<Bool>
    private let signedInFn: () -> Bool
    private let media: CallMedia
    private let ringer: CallRinger
    private let audio: CallAudio
    private let micGranted: () -> Bool
    private let now: () -> Int64
    private let sleep: Sleeper
    private let outbox: RecordingOutbox
    private let myAgentId: () -> String?
    private let myAgentName: () -> String?
    private let audioTrouble: Signal<Bool>

    public let state: Watched<CallUiState>
    /// True while a call is waiting for the agent to allow the microphone.
    public let micRequest = Watched<Bool>(false)
    /// A customer this phone asked has allowed calls: the "{First} allowed calls — Call now" banner.
    public let permissionGranted = Watched<PermissionGrant?>(nil)
    /// Meta flagged or restricted calling on the number (`calling_restricted`):
    /// the Calls view's banner — calls we place may fail until it lifts.
    public let restriction = Watched<CallingRestriction?>(nil)
    /// Which channels can call right now (GET /calls/channels, read at start,
    /// on every socket reconnect and with each ice-config). Nil until read —
    /// Messenger counts as off until then, so a Messenger Call button never
    /// shows before the server said it may.
    public let channels = Watched<CallChannels?>(nil)
    /// This agent may open Settings → WhatsApp calling (manage_settings); the shell sets it.
    public var canManageSettings: () -> Bool = { false }

    /// Messenger calls can be placed now (the server's `messenger_calling_enabled` switch, as last read).
    public var messengerCallsOn: Bool { channels.value?.messenger.outbound == true }

    public func dismissRestriction() { restriction.value = nil }

    /// Tests: when the live call started, on the injected clock (nil when none is live).
    var liveSinceForTest: Int64? { liveSince }
    /// How many ended calls are remembered (tests: it stays bounded under a burst).
    var endedCount: Int { endedOrder.count }

    // ── Refs (the web's useRef state) ─────────────────────────────────────
    private var peer: CallPeer?
    /// The call currently on screen.
    private var activeId: String?
    /// callId → when we last dismissed it (the 12 s re-ring cooldown); `endedOrder` keeps them oldest first.
    private var endedAt: [String: Int64] = [:]
    private var endedOrder: [String] = []
    private var recEnabled = true
    /// The server transcribes recordings (and without being asked): what the wrap-up promises.
    private var transcribes = false
    private var autoTranscribes = false
    /// WhatsApp records + transcribes the call itself: "summary in a minute" even with nothing recorded here.
    private var metaTranscribes = false
    /// A `call_status: ringing` for our call that beat connect's reply (applied once the id is known).
    private var earlyRinging: String?
    private var recording: CallRecording?
    private var recCallId: String?
    private var timerJob: Job?
    /// When the call went live, on `now`'s clock. The timer is worked out from
    /// it on every tick — never counted up — so a main thread held back by the
    /// app in the background can't make the call look shorter than it is.
    private var liveSince: Int64?
    /// When this phone started ringing: an answer that goes back to ringing keeps the 2-minute limit.
    private var ringSince: Int64?
    private var resetJob: Job?
    private var ringTimeoutJob: Job?
    /// Running while a "disconnected" peer has its chance to recover.
    private var graceJob: Job?
    /// Our SDP answer went to the server (its reply may yet be lost).
    private var answerPosted = false
    /// The server accepted our answer: hanging up now ends a call. Until then
    /// End on a "Connecting…" incoming call is a decline — the call still rings
    /// for the team (CallStage.tsx / callContext hangup()).
    private var answerAccepted = false
    /// When the media path dropped (entering "Reconnecting…"): a dropped call lasted until here, not through the grace.
    private var droppedAt: Int64?
    /// "Connecting…" never lasts: the audio must arrive within `CONNECT_GUARD_MS`.
    private var connectGuard: Job?
    /// The call's audio route is set up (the voice session).
    private var audioIn = false
    /// The customer's SDP answer to OUR call, when it arrived before we knew the
    /// call's id: applied the moment the id is known.
    private var earlyAnswer: (id: String, sdp: String)?
    /// An incoming call was ignored because another call was on screen: look again once it's over.
    private var missedWhileBusy = false
    /// "channel:handle" → name of the customers this phone asked for call permission (for the "allowed calls" banner).
    private var askedPermission: [String: String?] = [:]
    private func askKey(_ channel: String, _ handle: String) -> String { "\(channel):\(handle)" }
    private var micWaiter: Deferred<Bool>?

    // ── Messenger's SDP (CALLING_UX.md §2.0) ──────────────────────────────
    /// The current peer has its remote description (Meta's answer): a renegotiation offer may be applied.
    private var remoteReady = false
    /// The highest `media_update` version applied to the call on screen (older ones are stale).
    private var mediaVersion = Int.min
    /// A `media_update` that came before the call was set up: (callId, version, sdp), applied once it is.
    private var pendingMedia: (id: String, version: Int, sdp: String)?
    /// The media path is up (the peer said connected, and hasn't dropped since).
    private var mediaUp = false
    /// Remote offers are applied one at a time (a renegotiation and a media_update may meet).
    private let sdpLock = AsyncLock()
    private var started = false
    private var subs: [Subscription] = []
    private var pollJob: Job?
    private var pollRinging: Bool?
    private var lastPhase: CallPhase = .idle
    private var inEffects = false
    private var polls: SingleFlight<Void>!
    private var resyncs: SingleFlight<Void>!

    public init(api: CallApi, events: Signal<JSONValue>, connected: Watched<Bool>, foreground: Watched<Bool>,
                signedIn: @escaping () -> Bool, media: CallMedia, ringer: CallRinger, audio: CallAudio,
                micGranted: @escaping () -> Bool, now: @escaping () -> Int64 = { AppClock.now() },
                sleep: @escaping Sleeper = realSleep,
                outboxDir: URL = FileManager.default.temporaryDirectory.appendingPathComponent("neema-call-rec-\(UUID().uuidString)"),
                myAgentId: @escaping () -> String? = { nil }, myAgentName: @escaping () -> String? = { nil },
                audioTrouble: Signal<Bool> = CallAudioTrouble.events) {
        self.api = api; self.events = events; self.connected = connected; self.foreground = foreground
        self.signedInFn = signedIn; self.media = media; self.ringer = ringer; self.audio = audio
        self.micGranted = micGranted; self.now = now; self.sleep = sleep
        self.outbox = RecordingOutbox(dir: outboxDir, now: now)
        self.myAgentId = myAgentId; self.myAgentName = myAgentName; self.audioTrouble = audioTrouble
        var s = CallUiState()
        s.routes = audio.routes.value
        s.route = Self.preferredRoute(audio.routes.value)
        state = Watched(s)
        polls = SingleFlight { [weak self] in await self?.pollNow() }
        resyncs = SingleFlight { [weak self] in await self?.resyncNow() }
    }

    private var phase: CallPhase { state.value.phase }

    /// The one way state changes: set, then the phase's side effects (looped until the phase is stable).
    private func update(_ f: (inout CallUiState) -> Void) {
        var s = state.value
        f(&s)
        state.value = s
        runPhaseEffects()
    }

    private func set(_ s: CallUiState) {
        state.value = s
        runPhaseEffects()
    }

    private func runPhaseEffects() {
        if inEffects { return }
        inEffects = true
        defer { inEffects = false }
        while lastPhase != state.value.phase {
            let p = state.value.phase
            lastPhase = p
            guarded("phase") { onPhase(p) }
        }
    }

    // ── Start ─────────────────────────────────────────────────────────────
    /// Begin listening for the call frames, the poll fallback and the audio routes.
    public func start() {
        if started { return }
        started = true
        // A ringing alert left behind by a process that died mid-ring.
        ringer.cancelIncoming()
        // Raw audio a process killed mid-call left behind (no call is live yet).
        let media = self.media
        Task.detached { media.sweepLeftovers() }

        // Primary path: the live WebSocket event (instant). One bad frame costs
        // that frame, never the listener.
        subs.append(events.observe { [weak self] e in
            onMain { guard let self = self else { return }; self.guarded("frame:\(e.str("type") ?? "")") { self.onFrame(e) } }
        })

        // Catch-up: frames sent while the socket was down are lost. Poll the
        // moment it (re)connects and when the app comes back on screen.
        var wasConnected = connected.value
        subs.append(connected.observe { [weak self] c in
            onMain {
                guard let self = self else { return }
                if c && !wasConnected { self.catchUp() }
                wasConnected = c
            }
        })
        var wasFront = foreground.value
        subs.append(foreground.observe { [weak self] fg in
            onMain {
                guard let self = self else { return }
                let came = fg && !wasFront
                wasFront = fg
                if came { self.catchUp() }
                // Back on screen mid-call: the timer reads the true length at once.
                if fg && self.phase == .inCall { self.tickTimer() }
                // The app went to the background while a call is still ringing: notify.
                // Back on screen, the card is the alert — drop the alert.
                if self.phase != .ringing { return }
                if fg { self.ringer.cancelIncoming() } else { self.postIncoming() }
            }
        })
        // Recordings a previous session could not upload.
        drainRecordings()
        // Which channels can call (Messenger sits behind a server switch).
        loadChannels()

        // Headsets come and go: the call follows them (see `onRoutes`).
        subs.append(audio.routes.observe { [weak self] r in
            onMain { guard let self = self else { return }; self.guarded("routes") { self.onRoutes(r) } }
        })
        subs.append(audioTrouble.observe { [weak self] mic in
            onMain { guard let self = self else { return }; self.guarded("audio-trouble") { self.onAudioTrouble(mic) } }
        })

        // Fallback path: poll the call log for a fresh "ringing" call, so the card
        // appears even if the WS event was missed. 2.5 s only while RINGING
        // (hang-up detection needs it); 12 s otherwise. The cadence switches the
        // moment the phone starts or stops ringing.
        restartPoll(ringing: phase == .ringing)
        lastPhase = phase
    }

    /// Tears the softphone down (sign-out of the container, a test's end): every
    /// observer and timer is cancelled; the state is left as it is.
    public func stop() {
        for s in subs { s.cancel() }
        subs.removeAll()
        pollJob?.cancel(); pollJob = nil
        pollRinging = nil
        timerJob?.cancel(); timerJob = nil
        resetJob?.cancel(); resetJob = nil
        ringTimeoutJob?.cancel(); ringTimeoutJob = nil
        graceJob?.cancel(); graceJob = nil
        connectGuard?.cancel(); connectGuard = nil
        polls.cancel(); resyncs.cancel()
        started = false
    }

    private func restartPoll(ringing: Bool) {
        if pollRinging == ringing { return }
        pollRinging = ringing
        pollJob?.cancel()
        let every = ringing ? Self.RING_POLL_MS : Self.IDLE_POLL_MS
        pollJob = Job { [weak self] in
            while !Task.isCancelled {
                guard let self = self else { return }
                do { try await self.sleep(every) } catch { return }
                if Task.isCancelled { return }
                await self.pollOnce()
            }
        }
    }

    /// Phase side effects: ring + alert while ringing; timer + recording while
    /// live; in-call audio routing while a call runs.
    private func onPhase(_ p: CallPhase) {
        ringTimeoutJob?.cancel(); ringTimeoutJob = nil
        if p == .ringing {
            ringer.startRinging()
            if !foreground.value { postIncoming() }
            let id = state.value.callId
            let left = max(0, Self.RING_TIMEOUT_MS - max(0, now() - (ringSince ?? now())))
            ringTimeoutJob = Job { [weak self] in
                guard let self = self else { return }
                do { try await self.sleep(left) } catch { return }
                // Every end signal was lost: the caller is long gone.
                if self.phase == .ringing && self.state.value.callId == id { self.finish(.missed()) }
            }
        } else {
            ringer.stopRinging()
            ringer.cancelIncoming()
        }
        // A caller who rang in during the last call may still be waiting.
        if (p == .idle || p == .ended) && missedWhileBusy {
            missedWhileBusy = false
            Task { @MainActor [weak self] in await self?.pollOnce() }
        }
        if p == .inCall {
            startRecording()   // begins once (guarded); remote audio is flowing by now
            timerJob?.cancel()
            let since: Int64
            if let l = liveSince { since = l } else { since = now() - Int64(state.value.seconds) * 1_000; liveSince = since }
            timerJob = Job { [weak self] in
                while !Task.isCancelled {
                    guard let self = self else { return }
                    // Wake on the next whole second of the call, then read the clock.
                    let elapsed = self.now() - since
                    let wait = 1_000 - ((elapsed % 1_000) + 1_000) % 1_000
                    do { try await self.sleep(wait) } catch { return }
                    if Task.isCancelled { return }
                    self.tickTimer()
                }
            }
        } else {
            timerJob?.cancel(); timerJob = nil
            liveSince = nil
        }
        if Self.AUDIO_PHASES.contains(p) { enterAudio() } else { leaveAudio() }
        restartPoll(ringing: p == .ringing)
    }

    private func catchUp() {
        Task { @MainActor [weak self] in await self?.pollOnce() }
        Task { @MainActor [weak self] in await self?.resync() }
        drainRecordings()
        loadChannels()
    }

    /// GET /calls/channels. A failure keeps what was known (unknown = Messenger off).
    public func loadChannels() {
        Task { @MainActor [weak self] in
            guard let self = self, self.signedInFn() else { return }
            do { self.channels.value = try await self.api.channels() } catch {}
        }
    }

    /// The live call's length from `liveSince` (the only way `CallUiState.seconds` moves).
    private func tickTimer() {
        // Only a live call's clock moves: a tick that lands after the call ended must not
        // overwrite the length the wrap-up says (a dropped call's is the connected time).
        if phase != .inCall { return }
        guard let since = liveSince else { return }
        let secs = max(0, Int((now() - since) / 1_000))
        if secs != state.value.seconds { update { $0.seconds = secs } }
    }

    /// The poll cadence: 2.5 s while ringing, 12 s otherwise (restarted when ringing starts / stops).
    func pollDelay() -> Int64 { phase == .ringing ? Self.RING_POLL_MS : Self.IDLE_POLL_MS }

    private func postIncoming() {
        let s = state.value
        guard let id = s.callId else { return }
        ringer.postIncoming(callId: id, who: s.who, from: s.number, app: s.app)
    }

    // ── Audio routes ──────────────────────────────────────────────────────
    /// What a call starts on, as phones do: a connected headset, else the earpiece (the speaker only when there is nothing else).
    nonisolated static func preferredRoute(_ routes: [AudioRoute]) -> AudioRoute {
        routes.last { $0.kind == .bluetooth } ?? routes.last { $0.kind == .wired } ?? quietRoute(routes)
    }

    /// Never the loudspeaker when the phone has an earpiece: a headset that goes must not blast the call into the room.
    nonisolated static func quietRoute(_ routes: [AudioRoute]) -> AudioRoute {
        routes.first { $0.kind == .earpiece } ?? routes.first ?? .earpiece
    }

    private func enterAudio() {
        if audioIn { return }
        audioIn = true
        let r = Self.preferredRoute(state.value.routes)
        update { $0.route = r }
        audio.enter(route: r)
    }

    private func leaveAudio() {
        if !audioIn { return }
        audioIn = false
        audio.leave()
    }

    /// The outputs changed. Outside a call the button just shows what a call
    /// would start on. During one: a headset that was just connected takes the
    /// call (as a phone does); the route in use disappearing (unplugged, out of
    /// range) falls back to another headset, else the earpiece — never the
    /// loudspeaker while there is an earpiece.
    private func onRoutes(_ routes: [AudioRoute]) {
        let s = state.value
        let before = s.routes
        update { $0.routes = routes }
        if !audioIn {
            update { $0.route = Self.preferredRoute(routes) }
            return
        }
        let added = routes.filter { r in r.isHeadset && !before.contains(r) }
        var next: AudioRoute? = nil
        if let a = added.last { next = a }
        else if !routes.contains(s.route) { next = routes.last { $0.isHeadset } ?? Self.quietRoute(routes) }
        if let n = next, n != s.route { selectRoute(n) }
    }

    /// The audio list's choice (or `toggleSpeaker`'s).
    public func selectRoute(_ route: AudioRoute) {
        if !state.value.routes.contains(route) { return }
        update { $0.route = route }
        audio.select(route: route)
    }

    /// Earpiece (or the headset) ↔ loudspeaker: the audio button when there is nothing else to choose.
    public func toggleSpeaker() {
        let s = state.value
        let next: AudioRoute = s.speaker ? (s.routes.last { $0.isHeadset } ?? Self.quietRoute(s.routes)) : .speaker
        if !s.routes.contains(next) { return }
        selectRoute(next)
    }

    // ── Frames ────────────────────────────────────────────────────────────
    /// One WebSocket frame (only the call types matter here).
    func onFrame(_ evt: JSONValue) {
        switch evt.str("type") {
        case "incoming_call":
            Self.debugLog?("WS event: \(evt)")
            guard let id = evt.str("call_id") else { return }
            let ch = channelOf(evt.str("channel"))
            // Messenger: `from` is their PSID (`external_id` too); no name — it follows in a call_update.
            let from = Self.bare(evt.str("from") ?? evt.str("external_id") ?? "")
            let s = state.value
            if s.live && id != s.callId {
                missedWhileBusy = true
                // On a call: a banner, never a take-over (there is no hold in the API).
                if s.phase != .ringing && endedAt[id] == nil {
                    update { $0.waiting = WaitingCall(callId: id, from: from, name: evt.str("name"), channel: ch) }
                }
            }
            startRinging(id, from: from, name: evt.str("name"), conversationId: evt.str("conversation_id"),
                         personId: evt.str("person_id"), channel: ch)
        case "outbound_answer":
            guard let id = evt.str("call_id"), let sdp = evt.str("sdp") else { return }
            let s = state.value
            if id == activeId {
                // The customer accepted OUR call — apply their SDP answer to connect.
                Self.debugLog?("outbound answered")
                guard let p = peer else { return }
                if phase == .placing || phase == .ringingOut { update { $0.phase = .connecting }; armConnectGuard(id) }
                // Posted: the call may have ended (and its peer closed) before this runs.
                Task { @MainActor [weak self] in
                    guard let self = self, self.peer === p else { return }
                    try? await p.setRemote(.answer, sdp)
                }
            } else if activeId == nil && s.outbound && s.callId == "pending" && s.phase == .placing {
                // Ours, most likely, but connect hasn't told us its id yet.
                earlyAnswer = (id, sdp)
            }
        case "call_answered": onAnswered(evt)
        // Messenger: the customer picked up our call, or changed media — a new offer (§2.0).
        case "media_update":
            guard let id = evt.str("call_id") else { return }
            let sdp = evt.str("sdp").flatMap { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : $0 }
            let type = evt.str("sdp_type")
            guard let sdp = sdp, type == nil || type == "offer" else { Self.debugLog?("media_update without an offer — ignored"); return }
            let v = Int(evt.str("version").flatMap { Double($0) } ?? 0)
            onMediaUpdate(id, version: v, sdp: sdp)
        // Meta rings the customer's phone now: "Calling…" becomes "Ringing…" — only on this.
        case "call_status":
            guard let id = evt.str("call_id"), evt.str("status") == "ringing" else { return }
            let s = state.value
            if s.outbound && s.phase == .placing {
                if s.callId == id { update { $0.phase = .ringingOut } }
                else if s.callId == "pending" { earlyRinging = id }
            }
        case "calling_restricted":
            let reasons: [String] = (evt["reasons"]?.arrayValue ?? []).compactMap { r in
                if let s = r.stringValue { return s }
                if r.objectValue != nil { return r.str("reason") ?? r.str("type") ?? r.str("description") }
                return nil
            }
            restriction.value = CallingRestriction(reasons: reasons, at: evt.str("at"))
        case "call_ended":
            Self.debugLog?("WS event: \(evt)")
            guard let id = evt.str("call_id") else { return }
            let cur = state.value
            if cur.waiting?.callId == id { update { $0.waiting = nil } }
            if cur.callId == id && cur.live {
                finish(outcomeOf(evt.str("outcome"), cur, agent: evt.str("agent_name"), agentId: evt.str("agent_id")),
                       serverSeconds: evt.str("duration").flatMap { Int($0) })
            }
            // A no_answer corrected to rejected a moment later: the latest word wins.
            else if cur.callId == id && evt.str("outcome") == "rejected" { correctToRejected() }
            // A call we never showed (or not yet: frames can arrive out of
            // order): it is over, so a late incoming_call must not ring it.
            else if cur.callId != id && endedAt[id] == nil { markEnded(id) }
        case "call_update":
            guard let obj = evt["call"], obj.objectValue != nil, let row = try? NeemaJSON.decode(Call.self, from: obj) else { return }
            applyRow(row)
        case "call_permission": onPermission(evt)
        default: break
        }
    }

    nonisolated private static func bare(_ s: String) -> String { s.hasPrefix("+") ? String(s.dropFirst()) : s }

    /// Someone answered. For our outbound call that is the customer picking up;
    /// for a call ringing here it is a colleague (this phone stops at once);
    /// while this phone is still answering, a colleague who won the race.
    private func onAnswered(_ evt: JSONValue) {
        guard let id = evt.str("call_id") else { return }
        let s = state.value
        if s.waiting?.callId == id { update { $0.waiting = nil } }
        if s.callId != id { return }
        let agentId = evt.str("agent_id")
        switch s.phase {
        case .ringing: finish(.answeredElsewhere(agent: evt.str("agent_name"), mine: isMe(agentId)))
        case .placing, .ringingOut: if s.outbound { customerAnswered(id) }
        case .connecting: if !s.outbound && takenBySomeoneElse(agentId) { finish(.answeredElsewhere(agent: evt.str("agent_name"))) }
        default: break
        }
    }

    /// The customer picked up OUR call. WhatsApp: their answer's media follows
    /// ("Connecting…"). Messenger: the media path to Meta may be up already
    /// (its answer came back with connect) — then they're talking now; never
    /// before this moment, whatever the media did.
    private func customerAnswered(_ id: String) {
        let s = state.value
        if s.callId != id || !s.outbound || (s.phase != .placing && s.phase != .ringingOut) { return }
        if s.messenger && mediaUp && peer != nil {
            update { $0.phase = .inCall }
            return
        }
        update { $0.phase = .connecting }
        armConnectGuard(id)
    }

    /// `media_update {version, sdp}` (Messenger): the offer with the highest
    /// version is applied as a remote offer and answered locally — nothing is
    /// sent back. Stale versions, other calls' and SDP-less frames are ignored;
    /// one that arrives before the call is set up is held and applied once it is.
    private func onMediaUpdate(_ id: String, version: Int, sdp: String) {
        let s = state.value
        if s.callId == id && s.live { applyMediaUpdate(id, version: version, sdp: sdp) }
        // Our call whose id connect hasn't told us yet.
        else if s.live && s.outbound && s.callId == "pending" { holdMedia(id, version: version, sdp: sdp) }
    }

    private func holdMedia(_ id: String, version: Int, sdp: String) {
        if let had = pendingMedia, had.id == id, had.version >= version { return }
        pendingMedia = (id, version, sdp)
    }

    private func applyMediaUpdate(_ id: String, version: Int, sdp: String) {
        if version <= mediaVersion { Self.debugLog?("stale media_update v\(version) ignored"); return }
        guard let p = peer, remoteReady else { holdMedia(id, version: version, sdp: sdp); return }
        mediaVersion = version
        Task { @MainActor [weak self] in _ = await self?.applyRemoteOffer(p, sdp, why: "media_update") }
    }

    /// A held media_update for `id`, now that the call has Meta's answer.
    private func flushMedia(_ id: String) {
        guard let m = pendingMedia, m.id == id else { return }
        pendingMedia = nil
        applyMediaUpdate(id, version: m.version, sdp: m.sdp)
    }

    /// Meta's offer (a renegotiation after accept / connect, or a media_update)
    /// → a local answer. A failure is logged, never fatal: the call keeps the
    /// media it has.
    @discardableResult
    private func applyRemoteOffer(_ p: CallPeer, _ sdp: String, why: String) async -> Bool {
        await sdpLock.withLock {
            if peer !== p { return false }
            do {
                try await p.setRemote(.offer, sdp)
                if peer !== p { return false }
                let answer = try await p.createAnswer()
                if peer !== p { return false }
                try await p.setLocal(.answer, answer)
                return true
            } catch {
                Self.debugLog?("Messenger \(why) offer not applied: \(error)")
                return false
            }
        }
    }

    private func takenBySomeoneElse(_ agentId: String?) -> Bool {
        guard let me = myAgentId() else { return false }
        return agentId != nil && agentId != me
    }

    /// `agentId` is the signed-in agent (on this or another of their devices).
    private func isMe(_ agentId: String?) -> Bool { agentId != nil && agentId == myAgentId() }

    /// A 409's "answered by {name}" names the signed-in agent: their other device has the call.
    private func namesMe(_ who: String?) -> Bool {
        guard let me = myAgentName()?.trimmingCharacters(in: .whitespacesAndNewlines), !me.isEmpty, let w = who else { return false }
        return w.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == me.lowercased()
    }

    /// `call_permission`: a customer this phone asked has allowed calls (or not).
    private func onPermission(_ evt: JSONValue) {
        // Matched by channel + handle: the wa_id, or (Messenger) the PSID in `external_id`.
        let ch = channelOf(evt.str("channel"))
        let raw = ch == CallWords.MESSENGER ? evt.str("external_id") : (evt.str("wa_id") ?? evt.str("external_id"))
        guard let r = raw, case let wa = Self.bare(r), !wa.isEmpty else { return }
        // The card showing this customer says where their permission stands now.
        let cur = state.value
        let sameCall = cur.from == wa && cur.channel == ch
        if sameCall && cur.phase != .idle {
            let st = evt.str("status") ?? "unknown"
            var p = cur.permission ?? CallPermission(waId: wa)
            p.status = st
            p.expiresAt = evt.str("expires_at")
            p.permanent = evt.str("permanent") == "true"
            p.revoked = evt.str("revoked") == "true"
            p.at = evt.str("at") ?? p.at
            switch st {
            case "granted": p.canCall = true
            case "denied": p.canCall = false
            default: break
            }
            update { $0.permission = p }
        }
        let key = askKey(ch, wa)
        guard evt.str("status") == "granted", let asked = askedPermission[key] else { return }
        askedPermission.removeValue(forKey: key)
        permissionGranted.value = PermissionGrant(waId: wa, name: asked, channel: ch)
        // The wrap-up that said "call request sent" has its answer: the banner replaces it.
        let s = state.value
        if s.phase == .ended && s.from == wa && s.channel == ch && (s.outcome == .permissionRequested || s.outcome == .permissionNeeded) {
            dismiss()
        }
    }

    /// What a call's end means for this phone: the server's outcome, read
    /// against where this phone was (a "completed" call that was still ringing
    /// here was answered by a colleague).
    private func outcomeOf(_ status: String?, _ s: CallUiState, agent: String?, agentId: String?) -> CallOutcome {
        switch status {
        case "answered": return .answeredElsewhere(agent: agent, mine: isMe(agentId))
        case "completed", "ended":
            return s.phase == .ringing ? .answeredElsewhere(agent: agent, mine: isMe(agentId)) : .completed
        case "missed": return .missed()
        // "Declined by Ann" only when it was a colleague (the web's `other`).
        case "declined": return .declined(agent: takenBySomeoneElse(agentId) ? agent : nil)
        case "callback": return .callback(saved: .saved, agent: takenBySomeoneElse(agentId) ? agent : nil)
        case "no_answer": return .noAnswer
        case "rejected": return .rejected
        case "cancelled": return .cancelled
        case "failed": return .failed(reason: Self.CALL_NOT_CONNECTED)
        // An older frame without an outcome: judge by where the call was.
        default:
            switch s.phase {
            case .ringing: return .missed()
            case .placing, .ringingOut: return .noAnswer
            default: return s.reconnecting ? .connectionLost : .completed
            }
        }
    }

    /// A call's current row (a `call_update`, the re-sync, the poll): fill in
    /// what the ring didn't carry (the chat, the person, the name) and correct
    /// a phase the server knows to be over.
    private func applyRow(_ row: Call) {
        let s = state.value
        if row.callId.isEmpty || row.callId != s.callId { return }
        update {
            $0.conversationId = row.conversationId ?? $0.conversationId
            $0.personId = row.personId ?? $0.personId
            if ($0.name ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { $0.name = row.name }
            if channelOf(row.channel) == CallWords.MESSENGER { $0.channel = CallWords.MESSENGER }
        }
        let st = row.status
        if st.isEmpty { return }
        switch s.phase {
        // Saving a callback: the server marks the row itself; the card ends with its note.
        case .ringing: if st != "ringing" && !s.busy { finish(outcomeOf(st, s, agent: row.agentName, agentId: row.agentId)) }
        case .placing, .ringingOut:
            if st == "answered" { if s.outbound { customerAnswered(row.callId) } }
            else if st != "ringing" { finish(outcomeOf(st, s, agent: row.agentName, agentId: row.agentId), serverSeconds: row.duration) }
        case .connecting, .inCall:
            if st == "answered" {
                if s.phase == .connecting && !s.outbound && takenBySomeoneElse(row.agentId) { finish(.answeredElsewhere(agent: row.agentName)) }
            } else if st != "ringing" { finish(outcomeOf(st, s, agent: row.agentName, agentId: row.agentId), serverSeconds: row.duration) }
        case .ended: if st == "rejected" { correctToRejected() }
        default: break
        }
    }

    /// Meta's REJECTED can land just after the call was taken as unanswered: "{First} declined the call".
    private func correctToRejected() {
        let s = state.value
        if s.phase != .ended || !s.outbound || s.outcome != .noAnswer { return }
        update { $0.outcome = .rejected }
        scheduleClose(.rejected)
    }

    /// One pass of the poll fallback. Passes never overlap: the tick, a
    /// reconnect, a return to the app and the end of a call asking at once on
    /// a slow network share one GET (see `SingleFlight`).
    func pollOnce() async { try? await polls.run() }

    private func pollNow() async {
        if !signedInFn() { return }
        guard let calls = try? await api.list() else { return }
        let t = now()
        let s = state.value
        if s.phase == .ringing {
            // The caller hung up, or a colleague answered (row no longer "ringing").
            if calls.contains(where: { Self.isFreshInboundRing($0, t) && $0.callId != activeId }) { missedWhileBusy = true }
            if let row = calls.first(where: { $0.callId == activeId }) { applyRow(row) }
            return
        }
        if s.live {
            // Busy with another call: remember that someone is waiting, and show them.
            if let other = calls.first(where: { Self.isFreshInboundRing($0, t) && $0.callId != s.callId && !coolingDown($0.callId, t) }) {
                missedWhileBusy = true
                if s.waiting == nil { update { $0.waiting = WaitingCall(callId: other.callId, from: callHandle(other), name: other.name, channel: channelOf(other.channel)) } }
            }
            if let w = s.waiting, let row = calls.first(where: { $0.callId == w.callId }), row.status != "ringing" { update { $0.waiting = nil } }
            if s.callId != "pending", let row = calls.first(where: { $0.callId == s.callId }) { applyRow(row) }
            return
        }
        if let ringing = calls.first(where: { Self.isFreshInboundRing($0, t) && !coolingDown($0.callId, t) }) {
            Self.debugLog?("poll fallback caught ringing call: \(ringing.callId)")
            startRinging(ringing.callId, from: callHandle(ringing), name: ringing.name, conversationId: ringing.conversationId,
                         personId: ringing.personId, channel: channelOf(ringing.channel))
        }
    }

    /// After the socket reconnects or the app returns to the front: the call on
    /// screen re-reads its own row and takes the server's word for how it
    /// ended while this phone couldn't hear (CALLING_UX.md §4).
    func resync() async { try? await resyncs.run() }

    private func resyncNow() async {
        if !signedInFn() { return }
        let s = state.value
        guard let id = s.callId, id != "pending", s.live else { return }
        guard let row = try? await api.get(id) else { return }
        applyRow(row)
    }

    /// A row the poll fallback rings for: inbound, still ringing, started under 90 s ago.
    nonisolated private static func isFreshInboundRing(_ c: Call, _ t: Int64) -> Bool {
        guard c.status == "ringing", c.direction != "outbound", let at = Fmt.millis(c.startedAt) else { return false }
        return t - at < 90_000
    }

    /// Remembers that `callId` is over. Bounded: a long shift sees a
    /// `call_ended` frame for every call any agent takes, so beyond
    /// `ENDED_MAX` the entries past any use are dropped, then the oldest.
    private func markEnded(_ callId: String) {
        let t = now()
        if endedAt.removeValue(forKey: callId) != nil { endedOrder.removeAll { $0 == callId } }
        endedAt[callId] = t
        endedOrder.append(callId)
        if endedOrder.count <= Self.ENDED_MAX { return }
        for id in endedOrder where t - (endedAt[id] ?? t) > Self.ENDED_KEEP_MS { endedAt[id] = nil }
        endedOrder.removeAll { endedAt[$0] == nil }
        while endedOrder.count > Self.ENDED_MAX {
            let id = endedOrder.removeFirst()
            endedAt[id] = nil
        }
    }

    private func coolingDown(_ callId: String, _ t: Int64) -> Bool {
        guard let at = endedAt[callId] else { return false }
        return t - at < Self.RERING_COOLDOWN_MS
    }

    /// "answer" | "decline" | "end" | "show" from the call alerts (CallKit's actions route here).
    public func handleAction(_ action: String, id: String?) {
        let s = state.value
        let matches = id == nil || id == s.callId
        switch action {
        case "answer":
            // One tap from a locked phone: straight to Connecting, on the full card.
            if matches && s.phase == .ringing { ringer.cancelIncoming(); update { $0.minimised = false }; answer() }
            // The process was restarted since the alert went up: find the call
            // again, then answer it if it's still ringing.
            else if !s.live, let id = id {
                Task { @MainActor [weak self] in
                    guard let self = self else { return }
                    self.ringer.cancelIncoming()
                    await self.pollOnce()
                    if self.state.value.callId == id && self.phase == .ringing { self.answer() }
                }
            }
        case "decline":
            if matches && s.phase == .ringing { hangup() }
            // A call this process no longer tracks: still tell the server.
            else if !s.live, let id = id {
                ringer.cancelIncoming()
                markEnded(id)
                terminateSoon(id)
            }
        // The ongoing-call alert's End.
        case "end": if matches && s.live && s.phase != .ringing { hangup() }
        default: break   // "show": the app is up; the call card renders the call
        }
    }

    // Start ringing for a given call (shared by the WS event + the poll fallback).
    // A short cooldown stops a still-"ringing" record from instantly re-ringing
    // after a decline / failed answer, while allowing a genuine retry after ~12 s.
    // A wrap-up on screen gives way at once.
    private func startRinging(_ callId: String, from: String, name: String?, conversationId: String? = nil, personId: String? = nil,
                              channel: String = CallWords.WHATSAPP) {
        if state.value.live { return }
        if coolingDown(callId, now()) { return }
        resetJob?.cancel(); resetJob = nil
        activeId = callId
        ringSince = now()
        answerPosted = false
        resetSdp(keepFor: callId)
        let s = state.value
        var n = CallUiState()
        n.phase = .ringing; n.callId = callId; n.from = from; n.name = name; n.channel = channel
        n.conversationId = conversationId; n.personId = personId
        n.routes = s.routes; n.route = Self.preferredRoute(s.routes)
        set(n)
    }

    /// A new call: nothing of the last one's SDP state carries over (a frame held for `keepFor` does).
    private func resetSdp(keepFor: String? = nil) {
        remoteReady = false
        mediaUp = false
        mediaVersion = Int.min
        if pendingMedia?.id != keepFor { pendingMedia = nil }
    }

    // ── Microphone ────────────────────────────────────────────────────────
    /// The UI's answer to `micRequest`.
    public func onMicResult(_ granted: Bool) {
        let w = micWaiter
        micWaiter = nil
        micRequest.value = false
        w?.complete(granted)
    }

    private func ensureMic() async -> Bool {
        if micGranted() { return true }
        let w = micWaiter ?? Deferred<Bool>()
        micWaiter = w
        micRequest.value = true
        var granted = false
        if let g = try? await withTimeoutOrNil(Self.MIC_PROMPT_TIMEOUT_MS, sleep: sleep, { try await w.value() }) { granted = g }
        if micWaiter === w { micWaiter = nil; micRequest.value = false }
        return granted
    }

    // ── Recording ─────────────────────────────────────────────────────────
    private func startRecording() {
        if recording != nil || !recEnabled { return }
        guard let p = peer, p.hasMic else { return }
        guard let r = (try? media.startRecording(micMuted: state.value.muted)) ?? nil else { return }
        recording = r
        recCallId = activeId ?? state.value.callId
        update { $0.recording = true }
    }

    /// Stop + upload. Called at the top of cleanup() so it flushes on EVERY end path.
    private func stopRecording() {
        guard let r = recording else { return }
        let callId = recCallId
        recording = nil
        recCallId = nil
        let note = (autoTranscribes || metaTranscribes) ? Self.RECORDING_SAVED_AUTO : (transcribes ? Self.RECORDING_SAVED_MANUAL : Self.RECORDING_SAVED)
        update { $0.recording = false; $0.recordingNote = note }
        let outbox = self.outbox
        Task.detached { [weak self] in
            guard let file = r.stop() else { return }
            let size = (try? FileManager.default.attributesOfItem(atPath: file.path)[.size] as? Int64) ?? 0
            if callId == nil || callId == "pending" || size < Self.MIN_RECORDING_BYTES {
                try? FileManager.default.removeItem(at: file)   // skip near-silent / empty recordings
                return
            }
            // Kept on disk until the server has it: an upload that fails now
            // (often the very network drop that ended the call) is retried later.
            if outbox.put(callId!, file: file) { await self?.drain() }
        }
    }

    /// Uploads the recordings still waiting (see `RecordingOutbox`).
    private func drainRecordings() { Task { [weak self] in await self?.drain() } }

    private func drain() async {
        if !signedInFn() { return }
        let api = self.api
        _ = try? await outbox.drain { id, f in
            // Streamed from disk: an hour-long call never sits in memory.
            try await api.uploadRecording(id, file: UploadFile.of(file: f, filename: "\(id).m4a", mimeType: "audio/mp4"))
        }
    }

    private func readConfig(_ cfg: IceConfig) {
        recEnabled = cfg.record != false
        transcribes = cfg.transcribe == true
        autoTranscribes = cfg.autoTranscribe == true
        metaTranscribes = cfg.metaTranscription == true
        if let ch = cfg.channels { channels.value = ch }
        if state.value.metaTranscription != metaTranscribes { let m = metaTranscribes; update { $0.metaTranscription = m } }
    }

    // ── Teardown ──────────────────────────────────────────────────────────
    private func cleanup() {
        graceJob?.cancel(); graceJob = nil
        timerJob?.cancel(); timerJob = nil
        connectGuard?.cancel(); connectGuard = nil
        droppedAt = nil
        stopRecording()
        if let p = peer { peer = nil; p.close() }
        if let w = micWaiter { micWaiter = nil; micRequest.value = false; w.complete(false) }
        ringer.stopRinging()
        ringer.cancelIncoming()
    }

    /// The call is over on this phone: the wrap-up with its `outcome`. A neutral
    /// one closes by itself; a caller waiting behind this call rings at once.
    private func finish(_ outcome: CallOutcome, serverSeconds: Int? = nil, promoteWaiting: Bool = true, connectedSeconds: Int? = nil) {
        cleanup()
        if let a = activeId { markEnded(a) }
        activeId = nil
        earlyAnswer = nil
        let waiting = state.value.waiting
        // The look-again for a caller who waited behind this call is `promote`,
        // not the phase's own poll (decided before the phase changes, as Android's
        // collector sees it only after `finish` has run).
        let willPromote = promoteWaiting && waiting != nil && endedAt[waiting!.callId] == nil
        if willPromote { missedWhileBusy = false }
        update {
            $0.phase = .ended; $0.outcome = outcome; $0.reconnecting = false; $0.busy = false; $0.error = nil
            if let c = connectedSeconds { $0.seconds = c } else if $0.seconds == 0, let s = serverSeconds { $0.seconds = s }
            $0.waiting = nil
            if outcome == .completed || outcome == .connectionLost {
                // WhatsApp transcribes the call itself: a summary follows even when nothing was recorded here.
                if $0.recordingNote == nil && $0.metaTranscription && (connectedSeconds ?? $0.seconds) > 0 { $0.recordingNote = Self.META_SUMMARY }
            } else {
                $0.recordingNote = nil
            }
        }
        scheduleClose(outcome)
        if willPromote, let w = waiting { promote(w) }
    }

    /// A neutral wrap-up closes by itself (long enough to read a recording note).
    private func scheduleClose(_ outcome: CallOutcome) {
        resetJob?.cancel(); resetJob = nil
        guard let base = outcome.autoCloseMs else { return }
        let ms = state.value.recordingNote != nil ? max(base, 8_000) : base
        resetJob = Job { [weak self] in
            guard let self = self else { return }
            do { try await self.sleep(ms) } catch { return }
            if self.phase == .ended && self.state.value.outcome == outcome { self.toIdle() }
        }
    }

    /// A decline / call-back the server refused with 409 "call already answered
    /// by Ann": a colleague picked up a moment before the tap. The wrap-up says
    /// so instead of "Call declined".
    private func yieldTo(_ callId: String, _ who: String?) {
        let s = state.value
        if s.phase != .ended || s.callId != callId { return }
        guard let o = s.outcome, o.isDeclined || o.isCallback else { return }
        let next = CallOutcome.answeredElsewhere(agent: who, mine: namesMe(who))
        update { $0.outcome = next; $0.busy = false }
        scheduleClose(next)
    }

    /// The call that kept `w` waiting is over: ring them now — after one quick
    /// read that they are still on the line (a caller who gave up meanwhile
    /// must not ring). No answer from the server: the frame is trusted.
    private func promote(_ w: WaitingCall) {
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            let rows = try? await self.api.list()
            if self.state.value.live { return }
            let row = rows?.first { $0.callId == w.callId }
            if let r = row, r.status != "ringing" { self.markEnded(w.callId); return }
            let handle = row.map { callHandle($0) }.flatMap { $0.isEmpty ? nil : $0 }
            self.startRinging(w.callId, from: handle ?? w.from ?? "", name: row?.name ?? w.name, conversationId: row?.conversationId,
                              personId: row?.personId, channel: row.map { channelOf($0.channel) } ?? w.channel)
        }
    }

    private func toIdle() {
        resetJob?.cancel(); resetJob = nil
        let routes = state.value.routes
        var n = CallUiState()
        n.routes = routes; n.route = Self.preferredRoute(routes)
        set(n)
    }

    /// The wrap-up's Done / Cancel (a live call is never dismissed — it is hung up).
    public func dismiss() {
        if phase == .ended { toIdle() }
    }

    /// §6: the call shrinks to the bar at the top of the app; the rest of Neema stays usable.
    public func minimise() { if phase != .idle && phase != .ringing { update { $0.minimised = true } } }

    public func expand() { update { $0.minimised = false } }

    /// "Open chat" / "Message": the key of the customer's conversation to open
    /// (nil when there is nobody to write to). A live call shrinks to the bar
    /// rather than ending; a wrap-up closes.
    public func openChat() -> String? {
        let s = state.value
        guard let key = s.chatKey else { return nil }
        if s.live && s.phase != .ringing { update { $0.minimised = true } }
        else if s.phase == .ended { dismiss() }
        return key
    }

    /// "Call again" / "Call back" / "Try again" from the wrap-up.
    public func redial() {
        let s = state.value
        guard let to = s.from, !to.isEmpty, !s.live else { return }
        Task { @MainActor [weak self] in _ = await self?.initiateCall(to: to, name: s.name, conversationId: s.conversationId, channel: s.channel) }
    }

    /// Ends the call on this phone at once (a second tap finds it over), then
    /// tells the server in the background — a slow or unreachable server never
    /// keeps a live-looking card on screen. What the tap meant depends on where
    /// the call was: a ringing call is declined (for the whole team), our call
    /// not yet answered is cancelled, a call that was answered is completed.
    public func hangup() {
        let s = state.value
        if !s.live || s.busy { return }
        let id = s.callId
        let outcome: CallOutcome
        switch s.phase {
        case .ringing: outcome = .declined()
        case .placing, .ringingOut: outcome = .cancelled
        case .connecting: outcome = (!s.outbound && !answerAccepted) ? .declined() : .completed
        default: outcome = .completed
        }
        // The call's true length at the tap (the clock, not the last tick).
        let connected = liveSince.map { max(0, Int((now() - $0) / 1_000)) }
        finish(outcome, connectedSeconds: connected)
        if let id = id, id != "pending" {
            terminateSoon(id, onTaken: outcome.isDeclined ? { [weak self] who in self?.yieldTo(id, who) } : nil)
        }
    }

    /// Sign-out: ends the call on this phone and waits — at most `timeoutMs` —
    /// for the server to hear it, so the terminate still goes out under the
    /// session that is about to be cleared. A call that is only ringing is let
    /// go on this phone without declining it: a colleague may still answer.
    public func endForSignOut(timeoutMs: Int64 = SIGN_OUT_TERMINATE_MS) async {
        let s = state.value
        resetJob?.cancel(); resetJob = nil
        permissionGranted.value = nil
        askedPermission.removeAll()
        if s.phase == .idle { return }
        let id = s.callId
        let terminateId: String? = (s.live && s.phase != .ringing && id != "pending") ? id : nil
        cleanup()
        if let id = id { markEnded(id) }
        activeId = nil
        earlyAnswer = nil
        toIdle()
        if let t = terminateId {
            let api = self.api
            _ = try? await withTimeoutOrNil(timeoutMs, sleep: sleep) { try? await api.terminate(t) }
        }
    }

    /// POST /terminate, retried a couple of times while the server can't be
    /// reached — otherwise the customer's phone keeps ringing, or the call stays
    /// up on their side, until Meta times it out.
    private func terminateSoon(_ id: String, onTaken: ((String?) -> Void)? = nil) {
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            for attempt in 0...Self.TERMINATE_RETRY_MS.count {
                do { try await self.api.terminate(id); return }
                catch is CancellationError { return }
                catch {
                    // 409: a colleague answered a moment earlier — their call is left alone.
                    if error.statusOrNil == 409 { onTaken?(error.answeredBy()); return }
                    // 502 "terminate failed": Meta says the call is already over, or couldn't be reached.
                    if !RecordingOutbox.isTransient(error) || attempt == Self.TERMINATE_RETRY_MS.count { return }
                    do { try await self.sleep(Self.TERMINATE_RETRY_MS[attempt]) } catch { return }
                }
            }
        }
    }

    /// Decline now, call them back later. The card waits for the server (its
    /// buttons disabled) so "Saved to call back" is only said once it is; a
    /// request that never got an answer keeps retrying in the background.
    public func callback() {
        let s = state.value
        if !s.live || s.busy { return }
        let id = s.callId
        cleanup()
        guard let id = id, id != "pending" else { finish(.callback(saved: .saved)); return }
        update { $0.busy = true }
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            var saved: CallbackSave
            do { try await self.api.callback(id); saved = .saved }
            catch is CancellationError { return }
            catch {
                if error.statusOrNil == 409 {
                    // A colleague answered a moment before the tap: their call goes on.
                    if self.state.value.callId == id { let who = error.answeredBy(); self.finish(.answeredElsewhere(agent: who, mine: self.namesMe(who))) }
                    return
                }
                if RecordingOutbox.isTransient(error) && error.statusOrNil != 401 { self.callbackSoon(id); saved = .retrying }
                else { saved = .notSaved }
            }
            if self.state.value.callId != id { return }   // the card has moved on
            self.finish(.callback(saved: saved))
        }
    }

    /// Background retries of POST /callback (idempotent: terminate + mark it callback).
    private func callbackSoon(_ id: String) {
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            for wait in Self.TERMINATE_RETRY_MS {
                do { try await self.sleep(wait) } catch { return }
                do { try await self.api.callback(id); return }
                catch is CancellationError { return }
                catch { if !RecordingOutbox.isTransient(error) { return } }
            }
        }
    }

    // ── The second caller (a banner while this phone is on a call) ────────
    /// Decline the waiting caller — for the whole team, as any decline.
    public func declineWaiting() {
        guard let w = state.value.waiting else { return }
        update { $0.waiting = nil }
        markEnded(w.callId)
        terminateSoon(w.callId)
    }

    /// "Call back later" for the waiting caller: it ends and lands under Calls → Follow-ups.
    public func callbackWaiting() {
        guard let w = state.value.waiting else { return }
        update { $0.waiting = nil }
        markEnded(w.callId)
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            do { try await self.api.callback(w.callId) }
            catch is CancellationError { return }
            catch { if RecordingOutbox.isTransient(error) { self.callbackSoon(w.callId) } }
        }
    }

    /// "End & answer": the API has no hold, so taking the waiting caller means hanging up this call.
    public func endAndAnswer() {
        let s = state.value
        guard let w = s.waiting else { return }
        if !s.live || s.busy || s.phase == .ringing { return }
        let id = s.callId
        finish(.completed, promoteWaiting: false)
        if let id = id, id != "pending" { terminateSoon(id) }
        // The agent chose them: straight to answering (a 409 / 410 says if they are gone).
        startRinging(w.callId, from: w.from ?? "", name: w.name, channel: w.channel)
        if state.value.callId == w.callId && phase == .ringing { answer() }
    }

    // ── Answer an inbound call ────────────────────────────────────────────
    public func answer() {
        let s = state.value
        guard let callId = s.callId else { return }
        if s.phase != .ringing || s.busy { return }
        update { $0.error = nil; $0.phase = .connecting; $0.minimised = false }
        answerPosted = false
        answerAccepted = false
        ringer.stopRinging(); ringer.cancelIncoming()
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            await self.answerNow(callId)
        }
    }

    private func stillMine(_ callId: String) -> Bool {
        state.value.callId == callId && (phase == .connecting || phase == .inCall)
    }

    private func answerNow(_ callId: String) async {
        do {
            async let c = api.iceConfig()
            async let o = api.offer(callId)
            let (cfg, offer) = try await (c, o)
            readConfig(cfg)
            if !stillMine(callId) { return }   // hung up meanwhile
            // Messenger sends no offer (CALLING_UX.md §2.0): WE build the offer and
            // accept with it; Meta's answer comes back in the reply.
            let reversed = offer.offerRequired
                || ((offer.sdp ?? "").isEmpty && (channelOf(offer.channel) == CallWords.MESSENGER || state.value.messenger))
            if reversed && !state.value.messenger { update { $0.channel = CallWords.MESSENGER } }
            let p = try newPeer(cfg)
            if !(await ensureMic()) { throw MicBlockedError() }
            if peer !== p { return }
            try p.addMic(enabled: !state.value.muted)
            audio.micLive()
            let mine: String
            // Each step suspends: a hang-up meanwhile closes the peer, which must not be used again.
            if reversed {
                mine = try await p.createOffer()
                if peer !== p { return }
                try await p.setLocal(.offer, mine)
            } else {
                try await p.setRemote(.offer, offer.sdp ?? "")
                if peer !== p { return }
                mine = try await p.createAnswer()
                if peer !== p { return }
                try await p.setLocal(.answer, mine)
            }
            await awaitGathering(p)
            if peer !== p { return }
            answerPosted = true
            let resp = try await api.answer(callId, sdp: p.localSdp ?? mine)
            answerAccepted = true
            if reversed {
                let ok = await acceptMessengerAnswer(p, callId, resp)
                if !ok { return }
            }
            if stillMine(callId) && phase == .connecting { armConnectGuard(callId) }
        } catch is CancellationError {
            return
        } catch {
            // A failed answer, never the whole app closing on the agent.
            Self.debugLog?("answer failed: \(error)")
            reportUnexpected(error, "call-answer")
            if !stillMine(callId) { return }
            if error.isMessengerOff {
                // Messenger calling was switched off since we last looked.
                loadChannels()
                finish(.failed(reason: error.messengerOffReason(), action: "none")); return
            }
            if error.isTakenElsewhere {
                // 409: a colleague won the redis lock and is talking to the customer.
                // Only this device's side goes — never terminate their call.
                let who = error.answeredBy()
                finish(.answeredElsewhere(agent: who, mine: namesMe(who))); return
            }
            if error.isCallGone || error.isOfferGone {
                // 410, or the offer is gone (404): the caller hung up — nothing to terminate.
                finish(.missed(note: Self.CALL_GONE)); return
            }
            if error is MicBlockedError {
                // Nothing was answered: colleagues' phones still ring, so this one just steps back.
                finish(.micBlocked); return
            }
            if !answerPosted && error.statusOrNil == 0 {
                // Nothing reached Meta yet (no connection before our answer left): keep it
                // ringing and let the agent tap Answer again.
                cleanup()
                let why = error.isTimeout ? Self.ANSWER_SLOW_RETRY : Self.ANSWER_NO_CONNECTION
                update { $0.phase = .ringing; $0.error = why }
                return
            }
            if error.isAmbiguous("/answer") {
                // The accept may have reached Meta even though its answer never
                // came back: if the media connects, the call went through.
                let st = state
                _ = try? await withTimeoutOrNil(Self.ANSWER_CONFIRM_MS, sleep: sleep) {
                    for await s in st.stream() where s.callId != callId || s.phase != .connecting { return }
                }
                if !stillMine(callId) || phase == .inCall { return }
            }
            // Our answer left but its reply never came, and no audio followed: the
            // call may be up with nobody on it here — hang it up, say what happened.
            let why = (answerPosted && error.statusOrNil == 0) ? Self.ANSWER_DROPPED : Self.answerError(error)
            update { $0.error = why }
            do { try await sleep(1_800) } catch { return }
            if state.value.callId != callId || !state.value.live { return }
            // Connected after all (the error was about a request whose work was done).
            if phase == .inCall { update { $0.error = nil }; return }
            finish(.failed(reason: why, action: (error as? ApiError)?.action))
            terminateSoon(callId)
        }
    }

    /// Meta's answer to our offer, then (when present) its renegotiation offer,
    /// then any media_update that came early. Accepted but nothing to apply
    /// (or an answer the peer refuses): the call can't carry audio — it is
    /// ended, never left as a silent line. False when the call is over.
    private func acceptMessengerAnswer(_ p: CallPeer, _ callId: String, _ resp: CallSdpResponse) async -> Bool {
        if peer !== p { return false }
        let answer = resp.sdp.flatMap { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : $0 }
        var applied = false
        if let a = answer {
            do { try await p.setRemote(.answer, a); applied = true }
            catch { Self.debugLog?("Messenger answer rejected: \(error)") }
        }
        if peer !== p || state.value.callId != callId { return false }
        if !applied {
            finish(.failed(reason: answer == nil ? Self.AUDIO_NOT_CONNECTED : Self.AUDIO_SETUP_FAILED))
            terminateSoon(callId)
            return false
        }
        remoteReady = true
        if let r = resp.renegotiationSdp { await applyRemoteOffer(p, r, why: "accept") }
        flushMedia(callId)
        return peer === p
    }

    public func toggleMute() {
        guard let p = peer, p.hasMic else { return }
        let next = !state.value.muted
        p.setMicEnabled(!next)
        recording?.micMuted = next
        update { $0.muted = next }
    }

    /// Business-initiated call: WE call the customer. Build an offer, ask Meta to
    /// place the call ("Calling…"); once it rings them ("Ringing…") the
    /// customer's SDP answer arrives as an outbound_answer frame. Without their
    /// call permission (409) the wrap-up says so and offers the call request —
    /// never sent by itself, it messages the customer.
    /// `.failure` carries the user-facing message (`CallError.shown`: the card
    /// already says it); a call the agent hung up before it was placed counts
    /// as success (there is nothing to report).
    @discardableResult
    public func initiateCall(to: String, name: String? = nil, conversationId: String? = nil,
                             /// "messenger": `to` is their PSID and the call goes out on Messenger (CALLING_UX.md §2.0).
                             channel: String = CallWords.WHATSAPP) async -> Result<Void, Error> {
        do {
            return try await placeCall(to, name: name, conversationId: conversationId, channel: channel)
        } catch is CancellationError {
            return .failure(CancellationError())
        } catch {
            // The last net: whatever slipped past placeCall's own handling ends the
            // call on the card — the caller (a screen's task) never sees it.
            Self.debugLog?("outbound call broke: \(error)")
            reportUnexpected(error, "call-place")
            if state.value.outbound && state.value.live { finish(.failed(reason: Self.DEVICE_CALL_FAILED)) }
            return .failure(CallError(Self.DEVICE_CALL_FAILED, shown: true))
        }
    }

    private func stillPending() -> Bool { state.value.outbound && state.value.callId == "pending" && phase == .placing }

    private func placeCall(_ to: String, name: String?, conversationId: String?, channel: String) async throws -> Result<Void, Error> {
        if state.value.live { return .failure(CallError("Already in a call")) }
        let messenger = channelOf(channel) == CallWords.MESSENGER
        let wa = messenger ? to.filter { $0.isNumber } : Self.bare(to)
        if messenger && wa.isEmpty { return .failure(CallError("No Messenger id for this customer.")) }
        resetJob?.cancel(); resetJob = nil
        earlyAnswer = nil
        earlyRinging = nil
        answerPosted = false
        answerAccepted = false
        resetSdp()
        let routes = state.value.routes
        var n = CallUiState()
        n.phase = .placing; n.callId = "pending"; n.from = wa; n.name = name; n.outbound = true
        n.channel = messenger ? CallWords.MESSENGER : CallWords.WHATSAPP
        n.conversationId = conversationId; n.routes = routes; n.route = Self.preferredRoute(routes)
        set(n)
        let startedAfter = now() - Self.CLOCK_SKEW_MS
        do {
            // Permission truth first (Meta's answer, read alongside the ICE config): a customer
            // who hasn't allowed calls goes straight to "Send call request" — no doomed connect.
            // A slow or failed read never holds the call up: it is placed as before.
            async let permRead = readPermission(wa, messenger: messenger)
            let cfg = try await api.iceConfig()
            let perm = await permRead
            readConfig(cfg)
            if !stillPending() { return .success(()) }
            if let p = perm { update { $0.permission = p } }
            if let p = perm, p.canCall == false, p.status != "granted" {
                finish(p.status == "requested" ? .permissionRequested : .permissionNeeded)
                return .failure(CallError(Self.NO_CALL_PERMISSION, shown: true))
            }
            let p = try newPeer(cfg)
            if !(await ensureMic()) { throw MicBlockedError() }
            if peer !== p { return .success(()) }
            try p.addMic(enabled: !state.value.muted)
            audio.micLive()
            let offer = try await p.createOffer()
            if peer !== p { return .success(()) }   // hung up while the offer was made
            try await p.setLocal(.offer, offer)
            await awaitGathering(p)
            if peer !== p { return .success(()) }
            if messenger { return try await placeMessenger(p, psid: wa, sdp: p.localSdp ?? offer, name: name) }
            let id: String
            do {
                id = try await api.connect(to: to, sdp: p.localSdp ?? offer, name: (name ?? "").isEmpty ? nil : name)
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                // No answer came back, but Meta may be ringing the customer now:
                // find the row calls_connect wrote before calling it a failure.
                if !error.isAmbiguous("/admin/calls/connect") { throw error }
                guard let found = await findPlacedCall(to, since: startedAfter) else { throw error }
                id = found
            }
            if peer !== p {
                // Hung up while Meta was placing it: don't leave their phone ringing.
                try? await api.terminate(id)
                return .success(())
            }
            activeId = id
            // Placed: still "Calling…" until Meta says their phone rings (`call_status`), which may have come already.
            let ringing = earlyRinging == id
            earlyRinging = nil
            update { if $0.callId == "pending" { $0.callId = id; $0.phase = ringing ? .ringingOut : .placing } }
            if let early = earlyAnswer {
                earlyAnswer = nil
                if early.id == id {
                    Self.debugLog?("outbound answered (early)")
                    if phase == .placing || phase == .ringingOut { update { $0.phase = .connecting }; armConnectGuard(id) }
                    try? await p.setRemote(.answer, early.sdp)
                }
            }
            return .success(())
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            // A failed call on the card, never the whole app closing under the agent.
            Self.debugLog?("outbound call failed: \(error)")
            reportUnexpected(error, "call-place")
            // A connect that timed out and left no row: it may yet ring them.
            let friendly = (error.isAmbiguous("/admin/calls/connect") && error.isTimeout) ? Self.UNCONFIRMED_CALL : Self.outboundError(error)
            if !stillPending() { return .failure(CallError(friendly)) }
            let outcome: CallOutcome
            if error is MicBlockedError { outcome = .micBlocked }
            else if error.isMessengerOff {
                // Messenger calling was switched off since we last looked: call them on WhatsApp instead.
                loadChannels(); outcome = .failed(reason: error.messengerOffReason(), action: "none")
            } else if let a = error as? ApiError, a.status == 409 || a.action == "request_permission" {
                // Asked already (and waiting on their Allow), or never: the card says which.
                let perm = await readPermission(wa, messenger: messenger)
                if let p = perm, stillPending() { update { $0.permission = p } }
                outcome = perm?.status == "requested" ? .permissionRequested : .permissionNeeded
            } else if friendly == Self.UNCONFIRMED_CALL { outcome = .failed(reason: Self.UNCONFIRMED_CALL) }
            else {
                outcome = .failed(reason: error.serverReason() ?? friendly, action: (error as? ApiError)?.action,
                                  until: (error as? ApiError)?.field("request_available_at"))
            }
            if !stillPending() { return .failure(CallError(friendly)) }
            finish(outcome)
            return .failure(CallError(friendly, shown: true))
        }
    }

    /// The Messenger half of `initiateCall`: connect with our offer; Meta's
    /// answer comes back at once and is applied (then its renegotiation, and
    /// any media_update that beat the reply). The card stays "Calling…" /
    /// "Ringing…" until `call_answered` — the media path to Meta may come up
    /// before the customer picks up, and that is not them answering.
    private func placeMessenger(_ p: CallPeer, psid: String, sdp: String, name: String?) async throws -> Result<Void, Error> {
        // Never retried, never looked up after a timeout: a second connect would ring them twice.
        let resp = try await api.connectMessenger(psid: psid, sdp: sdp, name: (name ?? "").trimmingCharacters(in: .whitespaces).isEmpty ? nil : name)
        let id = resp.callId
        if id.isEmpty { throw CallError(Self.CALL_NOT_CONNECTED) }
        if peer !== p {
            try? await api.terminate(id)
            return .success(())
        }
        activeId = id
        let ringing = earlyRinging == id
        earlyRinging = nil
        update { if $0.callId == "pending" { $0.callId = id; $0.phase = ringing ? .ringingOut : .placing } }
        if let answer = resp.sdp, !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            do { try await p.setRemote(.answer, answer); remoteReady = true }
            catch { Self.debugLog?("Messenger answer rejected: \(error)") }
        }
        if remoteReady {
            if let r = resp.renegotiationSdp { await applyRemoteOffer(p, r, why: "connect") }
            flushMedia(id)
        }
        return .success(())
    }

    /// Ask the customer for permission to call them (WhatsApp's interactive
    /// call_permission_request inside the 24 h window, the approved template
    /// outside it). It messages the customer, so only ever on the agent's tap —
    /// "Send call request" on the wrap-up or the customer panel. Their Allow
    /// arrives as `call_permission` and raises `permissionGranted` on this
    /// phone. A refusal is an `ApiError` with the server's `code` / `action`
    /// (template_required, 138009 — see `requestRefusal`).
    public func requestPermission(to: String, name: String? = nil, channel: String = CallWords.WHATSAPP) async -> Result<PermissionRequestResponse, Error> {
        let wa = to.filter { $0.isNumber }
        let ch = channelOf(channel)
        do {
            let who = name ?? { let s = state.value; return (s.from == wa && s.channel == ch) ? s.name : nil }()
            // Messenger: the `calling_optin` message (Accept / Decline); WhatsApp: its call-permission request.
            let r = ch == CallWords.MESSENGER
                ? try await api.requestMessengerPermission(wa)
                : try await api.requestPermission(to: wa, name: (who ?? "").trimmingCharacters(in: .whitespaces).isEmpty ? nil : who)
            if !r.alreadyPermitted { askedPermission.updateValue(who, forKey: askKey(ch, wa)) }
            return .success(r)
        } catch {
            if error.isMessengerOff { loadChannels() }
            return .failure(error)
        }
    }

    /// The wrap-up's "Send call request".
    public func sendCallRequest() {
        let s = state.value
        guard let to = s.from, !to.isEmpty else { return }
        if s.phase != .ended || s.outcome != .permissionNeeded || s.busy { return }
        if s.sendRequestBlocked(now: now()) != nil || s.refusal?.code == "template_required" { return }
        update { $0.busy = true; $0.error = nil }
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            let r = await self.requestPermission(to: to, name: s.name, channel: s.channel)
            let cur = self.state.value
            if cur.phase != .ended || cur.from != to || cur.outcome != .permissionNeeded { return }
            switch r {
            case .success(let resp):
                if resp.alreadyPermitted {
                    // They had allowed calls permanently already: nothing to ask — "Call now".
                    self.update { $0.busy = false; $0.outcome = .alreadyAllowed; $0.permission = resp.permission ?? $0.permission }
                    self.scheduleClose(.alreadyAllowed)
                } else {
                    self.update { $0.busy = false; $0.outcome = .permissionRequested; $0.permission = resp.permission ?? $0.permission }
                    // Nothing more is owed on this card: it closes as the web's does (the banner follows the Allow).
                    self.scheduleClose(.permissionRequested)
                }
            case .failure(let e):
                let refusal = Self.requestRefusal(e, admin: self.canManageSettings())
                self.update {
                    switch refusal?.code {
                    // The limit (Messenger's: 2 a day): the button waits, saying when it can be pressed again.
                    case "138009", "request_limit":
                        $0.busy = false; $0.refusal = refusal
                        var p = $0.permission ?? CallPermission(waId: to)
                        p.canRequest = false
                        p.requestAvailableAt = (e as? ApiError)?.field("request_available_at") ?? $0.permission?.requestAvailableAt
                        $0.permission = p
                    case "template_required":
                        $0.busy = false; $0.refusal = refusal; $0.error = refusal?.detail
                    default:
                        $0.busy = false; $0.refusal = refusal; $0.error = Self.permissionRequestError(e)
                    }
                }
            }
        }
    }

    /// The wrap-up's "Call now" (the call request found they already allowed calls).
    public func callNow() {
        let s = state.value
        guard let to = s.from, !to.isEmpty, !s.live else { return }
        Task { @MainActor [weak self] in _ = await self?.initiateCall(to: to, name: s.name, conversationId: s.conversationId, channel: s.channel) }
    }

    /// GET /calls/permission, capped at `PERMISSION_READ_MS`: nil when it is
    /// slow or fails (the call is placed as it always was).
    private func readPermission(_ wa: String, messenger: Bool = false) async -> CallPermission? {
        let api = self.api
        do {
            return try await withTimeoutOrNil(Self.PERMISSION_READ_MS, sleep: sleep) {
                messenger ? try await api.messengerPermission(wa) : try await api.permission(wa)
            }
        } catch {
            if error.isMessengerOff { loadChannels() }
            return nil
        }
    }

    /// The banner's "Call now" for a customer who just allowed calls.
    public func callGranted() {
        guard let g = permissionGranted.value else { return }
        permissionGranted.value = nil
        if state.value.live { return }
        Task { @MainActor [weak self] in _ = await self?.initiateCall(to: g.waId, name: g.name, channel: g.channel) }
    }

    public func dismissGrant() { permissionGranted.value = nil }

    /// The outbound row calls_connect records once Meta placed the call: to this
    /// customer, still ringing, started since we asked. Looked for twice (the
    /// server may still be finishing the request that timed out on us).
    private func findPlacedCall(_ to: String, since: Int64) async -> String? {
        let wa = to.filter { $0.isNumber }
        for i in 0..<2 {
            if i > 0 { do { try await sleep(Self.PLACED_LOOKUP_GAP_MS) } catch { return nil } }
            let rows = try? await api.list()
            if let hit = rows?.first(where: {
                $0.direction == "outbound" && $0.status == "ringing" && $0.waId == wa
                    && endedAt[$0.callId] == nil && (Fmt.millis($0.startedAt) ?? 0) >= since
            }) { return hit.callId }
        }
        return nil
    }

    // ── Peer connection plumbing ──────────────────────────────────────────
    private func newPeer(_ cfg: IceConfig) throws -> CallPeer {
        let box = PeerBox()
        let p = try media.createPeer(config: cfg) { [weak self] ev in
            onMain {
                guard let self = self, let me = box.peer, self.peer === me else { return }
                switch ev {
                case .connected:
                    self.mediaUp = true
                    self.graceJob?.cancel(); self.graceJob = nil
                    self.connectGuard?.cancel(); self.connectGuard = nil
                    self.droppedAt = nil
                    if self.state.value.reconnecting { self.update { $0.reconnecting = false } }
                    self.setInCall()
                case .interrupted:
                    self.mediaUp = false
                    self.onInterrupted(me)
                case .ended:
                    self.mediaUp = false
                    // The path failed for good while it was recovering, or before any audio: gone.
                    if self.state.value.reconnecting || self.phase == .connecting { self.loseConnection() }
                    // Messenger: our call's path to Meta failed before they picked up.
                    else if self.phase == .placing || self.phase == .ringingOut { self.loseConnection() }
                    else { self.finish(.completed) }
                }
            }
        }
        box.peer = p
        peer = p
        remoteReady = false
        mediaUp = false
        return p
    }

    /// Lets the event closure find the peer it belongs to (set once `createPeer` returns).
    private final class PeerBox: @unchecked Sendable { var peer: CallPeer? }

    /// The media path dropped. A phone on a moving network loses it for a few
    /// seconds all the time and ICE brings it back by itself; the web ended the
    /// call on the first blip. Hold on for `ICE_GRACE_MS`, then give up.
    private func onInterrupted(_ p: CallPeer) {
        if phase != .inCall && phase != .connecting { return }
        if graceJob?.isActive == true { return }
        if phase == .inCall { droppedAt = now() }
        update { $0.reconnecting = true }
        graceJob = Job { [weak self] in
            guard let self = self else { return }
            do { try await self.sleep(Self.ICE_GRACE_MS) } catch { return }
            if self.peer !== p { return }
            self.graceJob = nil
            self.loseConnection()
        }
    }

    /// The media is gone for good: "Call dropped · 2:13" — the time it was
    /// really connected, not the grace spent waiting — or, when no audio ever
    /// flowed, "The call audio couldn't connect". Either way the call is hung
    /// up behind it, so the customer isn't left on a silent line.
    private func loseConnection() {
        let id = state.value.callId
        if let since = liveSince {
            finish(.connectionLost, connectedSeconds: max(0, Int(((droppedAt ?? now()) - since) / 1_000)))
        } else {
            finish(.failed(reason: Self.AUDIO_NOT_CONNECTED))
        }
        if let id = id, id != "pending" { terminateSoon(id) }
    }

    /// Answered (or the customer picked up), but the audio must arrive: never sit on "Connecting…" forever.
    private func armConnectGuard(_ id: String) {
        connectGuard?.cancel()
        connectGuard = Job { [weak self] in
            guard let self = self else { return }
            do { try await self.sleep(Self.CONNECT_GUARD_MS) } catch { return }
            self.connectGuard = nil
            let s = self.state.value
            if s.phase == .connecting && s.callId == id && !s.reconnecting {
                self.finish(.failed(reason: Self.AUDIO_NOT_CONNECTED))
                self.terminateSoon(id)
            }
        }
    }

    private func setInCall() {
        let s = state.value
        // Messenger: Meta's media server answered our offer before the customer picked up —
        // the call goes live on `call_answered`, never on the media alone.
        if s.outbound && s.messenger && (s.phase == .placing || s.phase == .ringingOut) { return }
        if phase == .connecting || phase == .ringing || phase == .ringingOut { update { $0.phase = .inCall } }
    }

    /// Wait for ICE gathering to finish, capped at 2.5 s (as the web does).
    private func awaitGathering(_ p: CallPeer) async {
        _ = try? await withTimeoutOrNil(Self.GATHER_TIMEOUT_MS, sleep: sleep) { try await p.awaitGathering() }
    }

    /// The device's call audio failed under WebRTC: the call stays up (the agent
    /// decides), and the card says what's wrong instead of going silent.
    private func onAudioTrouble(_ mic: Bool) {
        if !Self.AUDIO_PHASES.contains(phase) { return }
        update { $0.error = mic ? Self.MIC_UNAVAILABLE : Self.SPEAKER_UNAVAILABLE }
    }

    /// One step of a long-lived collector: a failure is recorded, and the collector carries on.
    private func guarded(_ where: String, _ block: () -> Void) {
        block()
    }

    /// A failure the call flow doesn't expect (not the server's, not the
    /// network's, not a refused microphone): kept as a crash report so the
    /// trace reaches the team — the agent only sees the call fail.
    private func reportUnexpected(_ e: Error, _ where: String) {
        if e is ApiError || e is CallError || e is MicBlockedError || e.isOffline || e.isTimeout { return }
        CrashHooks.recordNonFatal?(e, `where`)
    }

    // ── Error words ───────────────────────────────────────────────────────
    /// answer()'s catch in lib/callContext.tsx (plus the 409 a colleague's answer causes).
    nonisolated static func answerError(_ e: Error) -> String {
        if e is MicBlockedError { return MIC_BLOCKED }
        // accept's structured 502: the reason Meta gave, said for people.
        if let a = e as? ApiError, a.status == 502, a.code != nil {
            var d = a.detail.trimmingCharacters(in: .whitespacesAndNewlines)
            if d.lowercased().hasPrefix("accept failed:") { d = String(d.dropFirst("accept failed:".count)).trimmingCharacters(in: .whitespaces) }
            if !d.isEmpty && !d.hasPrefix("<") && d.count <= 160 { return d.prefix(1).uppercased() + d.dropFirst() }
            return "Couldn't connect the call"
        }
        if e.isTakenElsewhere { return TAKEN_ELSEWHERE }
        if e.isOfferGone || e.isCallGone { return CALL_GONE }
        if e.isTimeout { return ANSWER_SLOW }
        if e.isOffline { return ANSWER_OFFLINE }
        if e.statusOrNil == 401 { return SESSION_EXPIRED }
        return "Couldn't connect the call"
    }

    /// initiateCall()'s catch in lib/callContext.tsx. Never says "permission" but for the 409.
    nonisolated static func outboundError(_ e: Error) -> String {
        if e is MicBlockedError { return MIC_BLOCKED }
        if let a = e as? ApiError, a.status == 409 { return NO_CALL_PERMISSION }
        if e.isTimeout { return OUTBOUND_SLOW }
        if e.isOffline { return OUTBOUND_OFFLINE }
        if e.statusOrNil == 401 { return SESSION_EXPIRED }
        // Not the server, not the network: this device couldn't set the call up.
        if e is DeviceCallError { return DEVICE_CALL_FAILED }
        return "Couldn't place the call"
    }

    /// Why "Send call request" didn't go.
    nonisolated static func permissionRequestError(_ e: Error?) -> String { CallRequests.permissionRequestError(e) }

    /// A call request's structured refusal (nil for a plain network failure).
    nonisolated public static func requestRefusal(_ e: Error?, admin: Bool) -> CallRefusal? { CallRequests.refusal(e, admin: admin) }
}

// ── How the server's refusals read (ApiError, the only error the wire throws) ──
extension Error {
    var apiError: ApiError? { self as? ApiError }
    var statusOrNil: Int? { apiError?.status }
    /// 409 `messenger_calling_off`: the server's switch is off (every Messenger action says so).
    var isMessengerOff: Bool { apiError?.code == "messenger_calling_off" }
    func messengerOffReason() -> String {
        let d = (apiError?.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return (!d.isEmpty && !d.hasPrefix("<") && d.count <= 200) ? d : CallManager.MESSENGER_OFF
    }
    /// The request left but no answer came back: it may have done its work.
    func isAmbiguous(_ pathEnd: String) -> Bool {
        guard let a = apiError else { return false }
        return a.status == 0 && a.path.hasSuffix(pathEnd)
    }
    var isTimeout: Bool { apiError.map { $0.status == 0 && $0.body.hasPrefix("timed out") } ?? false }
    var isOffline: Bool { apiError.map { $0.status == 0 && !$0.body.hasPrefix("timed out") } ?? false }
    /// POST /admin/calls/{id}/answer's 409 (routers/admin.py calls_answer: "call already answered by {name}").
    var isTakenElsewhere: Bool {
        guard let a = apiError else { return false }
        return a.status == 409 && a.path.hasSuffix("/answer") && !isMessengerOff
    }
    /// POST /answer's 410: "This call has already ended." (the caller gave up, a colleague declined).
    var isCallGone: Bool { apiError?.status == 410 }
    /// GET /offer's 404 "call offer expired or not found": the caller hung up.
    var isOfferGone: Bool {
        guard let a = apiError else { return false }
        return a.status == 404 && a.path.hasSuffix("/offer")
    }
    /// The winner's name in a 409's "call already answered by Ann" (nil when it isn't named).
    func answeredBy() -> String? {
        guard let d = apiError?.detail.trimmingCharacters(in: .whitespacesAndNewlines) else { return nil }
        guard let r = d.range(of: "answered by ", options: [.caseInsensitive, .backwards]) else { return nil }
        var who = String(d[r.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
        while who.hasSuffix(".") { who.removeLast() }
        who = who.trimmingCharacters(in: .whitespaces)
        if who.isEmpty || who == "None" || who.lowercased() == "a colleague" { return nil }
        return who
    }
    /// A connect refusal the agent can act on (routers/admin.py calls_connect's
    /// 502 "call failed: <reason>") — never an HTML error page or a stack of codes.
    func serverReason() -> String? {
        guard let a = apiError else { return nil }
        // A structured refusal (`code`) says what happened whatever its status; an older one only on connect's 502.
        if a.code == nil && (a.status != 502 || !a.path.hasSuffix("/connect")) { return nil }
        var d = a.detail.trimmingCharacters(in: .whitespacesAndNewlines)
        if d.lowercased().hasPrefix("call failed:") { d = String(d.dropFirst("call failed:".count)).trimmingCharacters(in: .whitespaces) }
        if d.isEmpty || d.hasPrefix("<") || d.count > 160 { return nil }
        return d.prefix(1).uppercased() + d.dropFirst()
    }
}
