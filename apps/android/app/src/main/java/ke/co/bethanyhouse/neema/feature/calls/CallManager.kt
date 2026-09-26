package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.IceConfig
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.notify.Notifier
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import ke.co.bethanyhouse.neema.feature.orders.SingleFlight
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject
import java.io.File

/** idle | ringing | connecting | in_call | ended (lib/callContext.tsx). */
enum class CallPhase { Idle, Ringing, Connecting, InCall, Ended }

data class CallUiState(
    val phase: CallPhase = CallPhase.Idle,
    val callId: String? = null,
    /** Customer wa_id (digits, no +). */
    val from: String? = null,
    val name: String? = null,
    val muted: Boolean = false,
    val speaker: Boolean = false,
    val seconds: Int = 0,
    val error: String? = null,
    val note: String? = null,
    /** True while we placed the call (ringing THEM). */
    val outbound: Boolean = false,
    /** The network blipped mid-call: ICE is trying to recover (see [CallManager.ICE_GRACE_MS]). */
    val reconnecting: Boolean = false,
    /** A request the card is waiting on (saving a callback): its buttons are disabled. */
    val busy: Boolean = false,
)

/**
 * The WhatsApp softphone: incoming-call ringing, answer / decline / callback,
 * outbound calls, mute, and call recording — the port of lib/callContext.tsx.
 * Process-wide (lives in AppContainer) so a call survives navigating between
 * screens.
 *
 * This class is the web's rules and nothing else: the device side (WebRTC,
 * audio routing, ringtone, notification, the mic permission) arrives through
 * the interfaces in CallPorts.kt, so every rule here runs on the JVM in tests.
 *
 * PUBLIC CONTRACT — other features call only [state], [initiateCall],
 * [requestPermission], [hangup] and (MainActivity) [handleIntent].
 *
 * Threading: every state change runs on [main]; peer events hop there first.
 *
 * Microphone: the browser asks for the mic inside getUserMedia, in the middle
 * of answering or placing a call. Here the same moment raises [micRequest];
 * [CallStage] (always composed while signed in) shows the system prompt and
 * reports back through [onMicResult]. Refused (or unanswered for a minute),
 * the call fails with "Microphone blocked — allow it and try again", as the
 * web's does.
 *
 * Deliberate differences from the web (all web bugs, none visible otherwise):
 *  - a `call_ended` frame ends the call properly (the web showed "ended" and
 *    never returned to idle, leaving the card stuck);
 *  - an outbound call hung up while Meta was still placing it is terminated
 *    (the web left the customer's phone ringing with nobody on the line);
 *  - hang-up / callback taps on a call that already ended are ignored (a
 *    double tap re-terminated and restarted the "Call ended" timer);
 *  - an answer refused with 409 ("call already answered" — a colleague picked
 *    up first) says so and does NOT terminate: the web's hangup() there cut
 *    off the colleague's live call;
 *  - the poll keeps running in the background (the web skips hidden tabs)
 *    so a call still rings the phone through the notification;
 *  - the poll only rings for INBOUND rows: a colleague's outbound call is a
 *    "ringing" row too (calls_connect), and the web rang every other agent's
 *    softphone for it (answering then failed — there is no offer to fetch);
 *  - missed frames are caught up at once instead of on the next 12s tick:
 *    the call log is polled as soon as the socket (re)connects — which is
 *    also how a process restarted by LiveService finds a call that is
 *    ringing right now — and when the app comes back to the foreground;
 *  - a call that rang in while another was live (the web ignores it, as
 *    here) is looked for again the moment this one is over, not up to 12s
 *    later, so the waiting customer rings through straight away;
 *  - a `call_ended` for a call this phone never showed starts its cooldown,
 *    so an `incoming_call` delivered late (out of order) or a lagging
 *    "ringing" row can't ring a call that is already over;
 *  - the poll cadence changes as soon as ringing starts (see [start]), so
 *    a call answered on a colleague's phone stops this one within 2.5s;
 *  - ringing stops after [RING_TIMEOUT_MS] even if every end signal was lost
 *    (the server treats a call still ringing after 2 minutes as missed).
 *
 * Network failures (a phone network drops calls the web never sees):
 *  - a "disconnected" peer is a blip, not the end: the call shows
 *    "Reconnecting…" and ends only if ICE has not recovered within
 *    [ICE_GRACE_MS] (the web hangs up on the first blip);
 *  - hang-up ends the call on this phone at once; the terminate request
 *    follows in the background and is retried while the server can't be
 *    reached (the web waited up to 30s for it, the card frozen meanwhile);
 *  - an answer or outbound call whose request timed out may still have gone
 *    through: an answer waits for the media to connect before calling it
 *    failed, an outbound call looks for the row the server wrote;
 *  - the callback note says the callback was saved only once the server said
 *    so; otherwise it says it is still trying, and retries;
 *  - recordings are kept on disk until uploaded ([RecordingOutbox]).
 */
class CallManager internal constructor(
    private val api: CallApi,
    private val events: Flow<JsonObject>,
    /** The live socket's state: every (re)connect polls at once for frames missed while it was down. */
    private val connected: StateFlow<Boolean>,
    scope: CoroutineScope,
    /** True while the app is on screen (the incoming-call notification only fires when not). */
    private val foreground: StateFlow<Boolean>,
    private val signedInFn: () -> Boolean,
    private val media: CallMedia,
    private val ringer: CallRinger,
    private val audio: CallAudio,
    private val micGranted: () -> Boolean,
    private val main: CoroutineDispatcher,
    io: CoroutineDispatcher,
    private val now: () -> Long,
    /** Where recordings wait until the server has them. */
    outboxDir: File = java.nio.file.Files.createTempDirectory("neema-call-rec").toFile(),
) {
    constructor(
        context: Context,
        api: NeemaApi,
        socket: LiveSocket,
        scope: CoroutineScope,
        foreground: StateFlow<Boolean>,
        signedInFn: () -> Boolean,
        prefs: AppPrefs,
    ) : this(
        api = NeemaCallApi(api),
        events = socket.events,
        connected = socket.connected,
        scope = scope,
        foreground = foreground,
        signedInFn = signedInFn,
        media = WebRtcMedia(context),
        ringer = CallAlert(context, scope),
        audio = AndroidCallAudio(context) { prefs.backgroundLive.value && signedInFn() },
        micGranted = {
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        },
        main = Dispatchers.Main,
        io = Dispatchers.IO,
        now = System::currentTimeMillis,
        outboxDir = File(context.filesDir, "call-recordings"),
    )

    private val ui = CoroutineScope(scope.coroutineContext + main)
    private val bg = CoroutineScope(scope.coroutineContext + io)
    private val outbox = RecordingOutbox(outboxDir, now)

    private val _state = MutableStateFlow(CallUiState())
    val state: StateFlow<CallUiState> = _state.asStateFlow()

    /** Tests: when the live call started, on the injected clock (null when none is live). */
    internal val liveSinceForTest: Long? get() = liveSince

    private val _micRequest = MutableStateFlow(false)
    /** True while a call is waiting for the agent to allow the microphone. */
    val micRequest: StateFlow<Boolean> = _micRequest.asStateFlow()
    private var micWaiter: CompletableDeferred<Boolean>? = null

    // ── Refs (the web's useRef state) ────────────────────────────────────────
    private var peer: CallPeer? = null
    /** The call currently on screen. */
    private var activeId: String? = null
    /** callId → when we last dismissed it (the 12s re-ring cooldown). */
    private val endedAt = LinkedHashMap<String, Long>()   // oldest first
    private var recEnabled = true
    private var recording: CallRecording? = null
    private var recCallId: String? = null
    private var timerJob: Job? = null
    /**
     * When the call went live, on [now]'s clock. The timer is worked out from
     * it on every tick — never counted up — so a main thread held back by a
     * screen-off doze, a busy frame or the app in the background can't make
     * the call look shorter than it is.
     */
    private var liveSince: Long? = null
    private var resetJob: Job? = null
    private var ringTimeoutJob: Job? = null
    /** Running while a "disconnected" peer has its chance to recover. */
    private var graceJob: Job? = null
    /** An incoming call was ignored because another call was on screen: look again once it's over. */
    private var missedWhileBusy = false
    private var started = false

    private val phase: CallPhase get() = _state.value.phase
    private fun update(f: (CallUiState) -> CallUiState) { _state.value = f(_state.value) }

    init {
        (ringer as? CallAlert)?.onDecline = { id -> handleAction("decline", id) }
    }

    /** Begin listening for incoming_call / outbound_answer / call_ended and the poll fallback. */
    fun start() {
        if (started) return
        started = true
        // A ringing notification left behind by a process that died mid-ring.
        ringer.cancelIncoming()
        // Raw audio a process killed mid-call left behind (no call is live yet).
        bg.launch { runCatching { media.sweepLeftovers() } }

        // Primary path: the live WebSocket event (instant).
        ui.launch { events.collect(::onFrame) }

        // Catch-up: frames sent while the socket was down are lost. Poll the
        // moment it (re)connects — after a network drop, after the process was
        // restarted by LiveService, after the app returns from a socket-less
        // background — and when the app comes back on screen.
        ui.launch {
            var was = connected.value
            connected.collect { c -> if (c && !was) { pollOnce(); drainRecordings() }; was = c }
        }
        ui.launch {
            var was = foreground.value
            foreground.collect { fg -> if (fg && !was) { pollOnce(); drainRecordings() }; was = fg }
        }
        // Recordings a previous session could not upload.
        drainRecordings()

        // Fallback path: poll the call log for a fresh "ringing" call, so the card
        // appears even if the WS event was missed. 2.5s only while RINGING (hang-up
        // detection needs it); 12s otherwise. The cadence switches the moment the
        // phone starts or stops ringing (the web keeps a 12s wait already running,
        // so a colleague's answer — which sends no frame — could leave this phone
        // ringing for up to 12s).
        ui.launch {
            state.map { it.phase == CallPhase.Ringing }.distinctUntilChanged().collectLatest { ringing ->
                val every = if (ringing) RING_POLL_MS else IDLE_POLL_MS
                while (isActive) {
                    delay(every)
                    pollOnce()
                }
            }
        }

        // Phase side effects: ring + notify while ringing; timer + recording while
        // live; in-call audio routing + mic foreground service while a call runs.
        ui.launch {
            state.map { it.phase }.distinctUntilChanged().collect { p ->
                ringTimeoutJob?.cancel(); ringTimeoutJob = null
                if (p == CallPhase.Ringing) {
                    ringer.startRinging()
                    if (!foreground.value) postIncoming()
                    val id = _state.value.callId
                    ringTimeoutJob = ui.launch {
                        delay(RING_TIMEOUT_MS)
                        if (phase == CallPhase.Ringing && _state.value.callId == id) {
                            cleanup(); id?.let { markEnded(it) }; activeId = null
                            update { CallUiState() }
                        }
                    }
                } else {
                    ringer.stopRinging()
                    ringer.cancelIncoming()
                }
                // A caller who rang in during the last call may still be waiting.
                if (p == CallPhase.Idle && missedWhileBusy) {
                    missedWhileBusy = false
                    ui.launch { pollOnce() }
                }
                if (p == CallPhase.InCall) {
                    startRecording()   // begins once (guarded); remote audio is flowing by now
                    timerJob?.cancel()
                    val since = liveSince ?: (now() - _state.value.seconds * 1_000L).also { liveSince = it }
                    timerJob = ui.launch {
                        while (isActive) {
                            // Wake on the next whole second of the call, then read the clock.
                            delay(1_000L - (now() - since).mod(1_000L))
                            tickTimer()
                        }
                    }
                } else {
                    timerJob?.cancel(); timerJob = null
                    if (p == CallPhase.Idle || p == CallPhase.Connecting || p == CallPhase.Ringing) liveSince = null
                }
                if (p == CallPhase.Connecting || p == CallPhase.InCall) audio.enter(_state.value.speaker)
                else if (p == CallPhase.Idle || p == CallPhase.Ended) audio.leave()
            }
        }
        // The app went to the background while a call is still ringing: notify.
        // Back on screen, the card is the alert — drop the notification.
        ui.launch {
            foreground.collect { fg ->
                // Back on screen mid-call: the timer reads the true length at once.
                if (fg && phase == CallPhase.InCall) tickTimer()
                if (phase != CallPhase.Ringing) return@collect
                if (fg) ringer.cancelIncoming() else postIncoming()
            }
        }
    }

    /** The live call's length from [liveSince] (the only way [CallUiState.seconds] moves). */
    private fun tickTimer() {
        val since = liveSince ?: return
        val secs = ((now() - since) / 1_000L).toInt().coerceAtLeast(0)
        if (secs != _state.value.seconds) update { it.copy(seconds = secs) }
    }

    /** The poll cadence: 2.5s while ringing, 12s otherwise (restarted when ringing starts / stops). */
    internal fun pollDelay(): Long = if (phase == CallPhase.Ringing) RING_POLL_MS else IDLE_POLL_MS

    private fun postIncoming() {
        val s = _state.value
        val id = s.callId ?: return
        ringer.postIncoming(id, who(s), s.from?.takeIf { it.isNotEmpty() })
    }

    /** One WebSocket frame (only the three call types matter here). */
    internal fun onFrame(evt: JsonObject) {
        when (evt.str("type")) {
            "incoming_call" -> {
                logD("WS event: $evt")
                val id = evt.str("call_id") ?: return
                if (phase != CallPhase.Idle && id != _state.value.callId) missedWhileBusy = true
                startRinging(id, evt.str("from") ?: "", evt.str("name"))
            }
            "outbound_answer" -> if (evt.str("call_id") == activeId && activeId != null) {
                // The customer accepted OUR call — apply their SDP answer to connect.
                logD("outbound answered")
                val sdp = evt.str("sdp") ?: return
                val p = peer ?: return
                ui.launch { runCatching { p.setRemote(SdpType.Answer, sdp) } }
            }
            "call_ended" -> {
                logD("WS event: $evt")
                val id = evt.str("call_id") ?: return
                val cur = _state.value
                if (cur.callId == id) { if (cur.phase != CallPhase.Ended) finish() }
                // A call we never showed (or not yet: frames can arrive out of
                // order): it is over, so a late incoming_call must not ring it.
                else if (!endedAt.containsKey(id)) markEnded(id)
            }
        }
    }

    /**
     * One pass of the poll fallback. Passes never overlap: the tick, a
     * reconnect, a return to the app and the end of a call asking at once on
     * a slow network share one GET (see [SingleFlight]).
     */
    internal suspend fun pollOnce() = polls.run()

    private val polls = SingleFlight(ui) { pollNow() }

    private suspend fun pollNow() {
        if (!signedInFn()) return
        val calls = try { api.list() } catch (e: CancellationException) { throw e } catch (e: Exception) { return }
        val t = now()
        if (phase == CallPhase.Ringing) {
            // The caller hung up (row no longer "ringing") — tear the card down.
            val cur = calls.find { it.callId == activeId }
            if (calls.any { it.isFreshInboundRing(t) && it.callId != activeId }) missedWhileBusy = true
            // Saving a callback: the server marks the row itself; the card ends with its note.
            if (cur != null && cur.status != "ringing" && !_state.value.busy) {
                // Answered on another phone, or the caller gave up.
                cleanup(); activeId = null
                update { CallUiState() }
            }
            return
        }
        if (phase != CallPhase.Idle) {
            // Busy with another call: remember that someone is waiting.
            if (calls.any { it.isFreshInboundRing(t) && it.callId != _state.value.callId }) missedWhileBusy = true
            return
        }
        val ringing = calls.find { it.isFreshInboundRing(t) && !coolingDown(it.callId, t) }
        if (ringing != null) {
            logD("poll fallback caught ringing call: ${ringing.callId}")
            startRinging(ringing.callId, ringing.waId ?: "", ringing.name)
        }
    }

    /** A row the poll fallback rings for: inbound, still ringing, started under 90s ago. */
    private fun Call.isFreshInboundRing(t: Long) =
        status == "ringing" && direction != "outbound" && Fmt.millis(startedAt)?.let { t - it < 90_000 } == true

    /**
     * Remembers that [callId] is over. Bounded: a long shift sees a
     * `call_ended` frame for every call any agent takes, so beyond
     * [ENDED_MAX] the entries past any use (the re-ring cooldown and the
     * outbound-row lookup both look back minutes, not hours) are dropped,
     * then the oldest.
     */
    private fun markEnded(callId: String) {
        val t = now()
        endedAt.remove(callId)   // re-inserted at the end: the map stays oldest-first
        endedAt[callId] = t
        if (endedAt.size <= ENDED_MAX) return
        endedAt.values.removeAll { t - it > ENDED_KEEP_MS }
        val it = endedAt.entries.iterator()
        while (endedAt.size > ENDED_MAX && it.hasNext()) { it.next(); it.remove() }
    }

    /** How many ended calls are remembered (tests: it stays bounded under a burst). */
    internal val endedCount: Int get() = endedAt.size

    private fun coolingDown(callId: String, t: Long) = endedAt[callId]?.let { t - it < RERING_COOLDOWN_MS } == true

    private fun who(s: CallUiState) =
        s.name?.takeIf { it.isNotBlank() } ?: s.from?.takeIf { it.isNotEmpty() }?.let { "+$it" } ?: "Unknown"

    /** A notification action (answer/decline/show) routed through MainActivity. */
    fun handleIntent(intent: Intent) {
        val action = intent.getStringExtra(Notifier.EXTRA_CALL_ACTION) ?: return
        handleAction(action, intent.getStringExtra(Notifier.EXTRA_CALL_ID))
    }

    /** "answer" | "decline" | "show" from the incoming-call notification. */
    internal fun handleAction(action: String, id: String?) {
        val s = _state.value
        val matches = id == null || id == s.callId
        when (action) {
            "answer" -> when {
                matches && s.phase == CallPhase.Ringing -> { ringer.cancelIncoming(); answer() }
                // The process was restarted since the notification went up: find
                // the call again, then answer it if it's still ringing.
                s.phase == CallPhase.Idle && id != null -> ui.launch {
                    ringer.cancelIncoming()
                    pollOnce()
                    if (_state.value.callId == id && phase == CallPhase.Ringing) answer()
                }
            }
            "decline" -> when {
                matches && s.phase == CallPhase.Ringing -> hangup()
                // A call this process no longer tracks: still tell the server.
                s.phase == CallPhase.Idle && id != null -> ui.launch {
                    ringer.cancelIncoming()
                    markEnded(id)
                    terminateSoon(id)
                }
            }
            else -> Unit   // "show": the activity is up; CallStage renders the call
        }
    }

    // Start ringing for a given call (shared by the WS event + the poll fallback).
    // A short cooldown stops a still-"ringing" record from instantly re-ringing
    // after a decline / failed answer, while allowing a genuine retry after ~12s.
    private fun startRinging(callId: String, from: String, name: String?) {
        if (phase != CallPhase.Idle) return
        if (coolingDown(callId, now())) return
        activeId = callId
        update { it.copy(callId = callId, from = from, name = name, phase = CallPhase.Ringing) }
    }

    // ── Microphone ───────────────────────────────────────────────────────────
    /** The UI's answer to [micRequest]. */
    fun onMicResult(granted: Boolean) {
        val w = micWaiter
        micWaiter = null
        _micRequest.value = false
        w?.complete(granted)
    }

    private suspend fun ensureMic(): Boolean {
        if (micGranted()) return true
        val w = micWaiter ?: CompletableDeferred<Boolean>().also { micWaiter = it }
        _micRequest.value = true
        val granted = withTimeoutOrNull(MIC_PROMPT_TIMEOUT_MS) { w.await() } ?: false
        if (micWaiter === w) { micWaiter = null; _micRequest.value = false }
        return granted
    }

    // ── Recording ────────────────────────────────────────────────────────────
    private fun startRecording() {
        if (recording != null || !recEnabled) return
        val p = peer ?: return
        if (!p.hasMic) return
        recording = try { media.startRecording(_state.value.muted) } catch (e: Exception) {
            logW("recording unavailable", e); null
        } ?: return
        recCallId = activeId ?: _state.value.callId
    }

    /** Stop + upload. Called at the top of cleanup() so it flushes on EVERY end path. */
    private fun stopRecording() {
        val r = recording ?: return
        val callId = recCallId
        recording = null
        recCallId = null
        bg.launch {
            val file = try { r.stop() } catch (e: Exception) { null } ?: return@launch
            if (callId == null || callId == "pending" || file.length() < MIN_RECORDING_BYTES) {
                file.delete()   // skip near-silent / empty recordings
                return@launch
            }
            // Kept on disk until the server has it: an upload that fails now
            // (often the very network drop that ended the call) is retried later.
            if (outbox.put(callId, file)) drain()
        }
    }

    /** Uploads the recordings still waiting (see [RecordingOutbox]). */
    private fun drainRecordings() { bg.launch { drain() } }

    private suspend fun drain() {
        if (!signedInFn()) return
        outbox.drain { id, f ->
            // Streamed from disk: an hour-long call never sits in memory.
            try { api.uploadRecording(id, UploadFile.of(f, "$id.m4a", "audio/mp4")) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { logW("recording upload failed", e); throw e }
        }
    }

    // ── Teardown ─────────────────────────────────────────────────────────────
    private fun cleanup() {
        graceJob?.cancel(); graceJob = null
        stopRecording()
        peer?.let { p -> peer = null; runCatching { p.close() } }
        micWaiter?.let { w -> micWaiter = null; _micRequest.value = false; w.complete(false) }
        ringer.stopRinging()
        ringer.cancelIncoming()
    }

    private fun finish(noteText: String? = null) {
        cleanup()
        activeId?.let { markEnded(it) }
        activeId = null
        update { it.copy(phase = CallPhase.Ended, note = noteText ?: it.note, reconnecting = false, busy = false) }
        resetJob?.cancel()
        resetJob = ui.launch {
            delay(if (noteText != null) 1_600 else 1_000)
            update { CallUiState() }
        }
    }

    private val live: Boolean get() = phase != CallPhase.Idle && phase != CallPhase.Ended

    /**
     * Ends the call on this phone at once (a second tap finds it over), then
     * tells the server in the background — a slow or unreachable server never
     * keeps a live-looking card on screen.
     *
     * The returned job ends once the server has been told (or has given up
     * being told): sign-out waits on it, bounded, before dropping the token
     * the terminate request needs. Callers that don't care ignore it.
     */
    fun hangup(): Job = ui.launch {
        if (!live || _state.value.busy) return@launch
        val id = _state.value.callId
        cleanup()
        finish()
        if (id != null && id != "pending") terminateSoon(id).join()
    }

    /**
     * Sign-out: ends the call on this phone and waits — at most [timeoutMs] —
     * for the server to hear it, so the terminate still goes out under the
     * session that is about to be cleared (fired and forgotten, it raced the
     * sign-out and was refused with a 401, leaving the customer on the line).
     *
     * A call that is only ringing is let go on this phone without declining
     * it: a colleague may still answer. The card goes straight to idle — the
     * next agent to sign in sees nothing of this call.
     */
    suspend fun endForSignOut(timeoutMs: Long = SIGN_OUT_TERMINATE_MS) = withContext(main) {
        val s = _state.value
        resetJob?.cancel(); resetJob = null
        if (s.phase == CallPhase.Idle) return@withContext
        val id = s.callId
        val terminate = s.phase != CallPhase.Ringing && s.phase != CallPhase.Ended && id != null && id != "pending"
        cleanup()
        id?.let { markEnded(it) }
        activeId = null
        update { CallUiState() }
        if (terminate) withTimeoutOrNull(timeoutMs) {
            try { api.terminate(id!!) } catch (e: CancellationException) { throw e } catch (_: Exception) {}
        }
    }

    /**
     * POST /terminate, retried a couple of times while the server can't be
     * reached — otherwise the customer's phone keeps ringing, or the call stays
     * up on their side, until Meta times it out.
     */
    private fun terminateSoon(id: String): Job = ui.launch {
        for (attempt in 0..TERMINATE_RETRY_MS.size) {
            try { api.terminate(id); return@launch }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                // 502 "terminate failed": Meta says the call is already over, or couldn't be reached.
                if (!RecordingOutbox.isTransient(e) || attempt == TERMINATE_RETRY_MS.size) return@launch
                delay(TERMINATE_RETRY_MS[attempt])
            }
        }
    }

    /**
     * Decline now, call them back later. The card waits for the server (its
     * buttons disabled) so "Callback saved" is only said once it is; a request
     * that never got an answer keeps retrying in the background.
     */
    fun callback() {
        ui.launch {
            val s = _state.value
            if (!live || s.busy) return@launch
            val id = s.callId
            cleanup()
            if (id == null || id == "pending") { finish(CALLBACK_SAVED); return@launch }
            update { it.copy(busy = true) }
            val note = try {
                api.callback(id); CALLBACK_SAVED
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                logW("callback failed", e)
                if (RecordingOutbox.isTransient(e) && e.statusOrNull() != 401) { callbackSoon(id); CALLBACK_RETRYING }
                else CALLBACK_FAILED
            }
            if (_state.value.callId != id) return@launch   // the card has moved on
            finish(note)
        }
    }

    /** Background retries of POST /callback (idempotent: terminate + mark it callback). */
    private fun callbackSoon(id: String) {
        ui.launch {
            for (wait in TERMINATE_RETRY_MS) {
                delay(wait)
                try { api.callback(id); return@launch }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { if (!RecordingOutbox.isTransient(e)) return@launch }
            }
        }
    }

    // ── Answer an inbound call ───────────────────────────────────────────────
    fun answer() {
        ui.launch {
            val s = _state.value
            val callId = s.callId ?: return@launch
            if (s.phase != CallPhase.Ringing || s.busy) return@launch
            update { it.copy(error = null, phase = CallPhase.Connecting) }
            ringer.stopRinging(); ringer.cancelIncoming()
            fun stillMine() = _state.value.callId == callId && (phase == CallPhase.Connecting || phase == CallPhase.InCall)
            try {
                val (cfg, offer) = coroutineScope {
                    val c = async { api.iceConfig() }
                    val o = async { api.offer(callId) }
                    c.await() to o.await()
                }
                recEnabled = cfg.record != false
                if (!stillMine()) return@launch   // hung up meanwhile
                val p = newPeer(cfg)
                if (!ensureMic()) throw MicBlocked()
                if (peer !== p) return@launch
                p.addMic(!_state.value.muted)
                audio.micLive()
                p.setRemote(SdpType.Offer, offer.sdp)
                val answer = p.createAnswer()
                p.setLocal(SdpType.Answer, answer)
                awaitGathering(p)
                if (peer !== p) return@launch
                api.answer(callId, p.localSdp ?: answer)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                logW("answer failed", e)
                if (!stillMine()) return@launch
                if (e.isAmbiguous("/answer")) {
                    // The accept may have reached Meta even though its answer never
                    // came back: if the media connects, the call went through.
                    withTimeoutOrNull(ANSWER_CONFIRM_MS) {
                        state.first { it.callId != callId || it.phase != CallPhase.Connecting }
                    }
                    if (!stillMine() || phase == CallPhase.InCall) return@launch
                }
                update { it.copy(error = answerError(e)) }
                delay(1_800)
                if (_state.value.callId != callId || !live) return@launch
                // Connected after all (the error was about a request whose work was done).
                if (phase == CallPhase.InCall) { update { it.copy(error = null) }; return@launch }
                // 409 "call already answered": a colleague won the redis lock and is
                // talking to the customer. The web's hangup() here terminated THEIR
                // call; only tear down this device's side. A 404 offer: the caller
                // is gone, there is nothing to terminate.
                if (e.isTakenElsewhere() || e.isOfferGone()) finish() else hangup()
            }
        }
    }

    fun toggleMute() {
        val p = peer ?: return
        if (!p.hasMic) return
        val next = !_state.value.muted
        p.setMicEnabled(!next)
        recording?.micMuted = next
        update { it.copy(muted = next) }
    }

    /** Earpiece ↔ loudspeaker (the web plays through the computer's speakers). */
    fun toggleSpeaker() {
        val next = !_state.value.speaker
        audio.setSpeaker(next)
        update { it.copy(speaker = next) }
    }

    /**
     * Business-initiated call: WE call the customer. Build an offer, ask Meta to
     * place the call; the customer's SDP answer arrives as an outbound_answer
     * frame. Needs the customer's call permission (409 otherwise).
     * Result.failure carries the user-facing message; a call the agent hung up
     * before it was placed counts as success (there is nothing to report).
     */
    suspend fun initiateCall(to: String, name: String? = null): Result<Unit> = withContext(main) {
        if (phase != CallPhase.Idle) return@withContext Result.failure(CallError("Already in a call"))
        resetJob?.cancel()
        update {
            CallUiState(phase = CallPhase.Connecting, callId = "pending", from = to.removePrefix("+"), name = name, outbound = true)
        }
        fun stillMine() = _state.value.outbound && _state.value.callId == "pending" && phase == CallPhase.Connecting
        val startedAfter = now() - CLOCK_SKEW_MS
        try {
            val cfg = api.iceConfig()
            recEnabled = cfg.record != false
            if (!stillMine()) return@withContext Result.success(Unit)
            val p = newPeer(cfg)
            if (!ensureMic()) throw MicBlocked()
            if (peer !== p) return@withContext Result.success(Unit)
            p.addMic(!_state.value.muted)
            audio.micLive()
            val offer = p.createOffer()
            p.setLocal(SdpType.Offer, offer)
            awaitGathering(p)
            if (peer !== p) return@withContext Result.success(Unit)
            val id = try {
                api.connect(to, p.localSdp ?: offer, name?.takeIf { it.isNotEmpty() })
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // No answer came back, but Meta may be ringing the customer now:
                // find the row calls_connect wrote before calling it a failure.
                if (!e.isAmbiguous("/admin/calls/connect")) throw e
                findPlacedCall(to, startedAfter) ?: throw e
            }
            if (peer !== p) {
                // Hung up while Meta was placing it: don't leave their phone ringing.
                try { api.terminate(id) } catch (e: CancellationException) { throw e } catch (_: Exception) {}
                return@withContext Result.success(Unit)
            }
            activeId = id
            update { if (it.callId == "pending") it.copy(callId = id) else it }
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logW("outbound call failed", e)
            // A connect that timed out and left no row: it may yet ring them.
            val friendly = if (e.isAmbiguous("/admin/calls/connect") && e.isTimeout()) UNCONFIRMED_CALL else outboundError(e)
            if (!stillMine()) return@withContext Result.failure(CallError(friendly))
            update { it.copy(error = friendly) }
            resetJob?.cancel()
            resetJob = ui.launch {
                delay(2_200)
                cleanup()
                update { CallUiState() }
            }
            Result.failure(CallError(friendly))
        }
    }

    /**
     * Ask the customer for permission to call them (WhatsApp's interactive
     * call_permission_request). The web's customer panel sends this
     * automatically when [initiateCall] fails for lack of permission — callers
     * check `message.contains("permission", ignoreCase = true)`.
     */
    suspend fun requestPermission(to: String): Result<Unit> =
        try { api.requestPermission(to.filter { it.isDigit() }); Result.success(Unit) }
        catch (e: CancellationException) { throw e }
        catch (e: Exception) { Result.failure(e) }

    /**
     * The outbound row calls_connect records once Meta placed the call: to this
     * customer, still ringing, started since we asked. Looked for twice (the
     * server may still be finishing the request that timed out on us).
     */
    private suspend fun findPlacedCall(to: String, since: Long): String? {
        val wa = to.filter { it.isDigit() }
        repeat(2) { i ->
            if (i > 0) delay(PLACED_LOOKUP_GAP_MS)
            val rows = try { api.list() } catch (e: CancellationException) { throw e } catch (_: Exception) { null }
            rows?.firstOrNull {
                it.direction == "outbound" && it.status == "ringing" && it.waId == wa &&
                    !endedAt.containsKey(it.callId) && (Fmt.millis(it.startedAt) ?: 0L) >= since
            }?.let { return it.callId }
        }
        return null
    }

    // ── Peer connection plumbing ─────────────────────────────────────────────
    private fun newPeer(cfg: IceConfig): CallPeer {
        var self: CallPeer? = null
        val p = media.createPeer(cfg) { ev ->
            ui.launch {
                val me = self
                if (me == null || peer !== me) return@launch
                when (ev) {
                    PeerEvent.Connected -> {
                        graceJob?.cancel(); graceJob = null
                        if (_state.value.reconnecting) update { it.copy(reconnecting = false) }
                        setInCall()
                    }
                    PeerEvent.Interrupted -> onInterrupted(me)
                    PeerEvent.Ended -> finish(if (_state.value.reconnecting) CONNECTION_LOST else null)
                }
            }
        }
        self = p
        peer = p
        return p
    }

    /**
     * The media path dropped. A phone on a moving network loses it for a few
     * seconds all the time and ICE brings it back by itself; the web ended the
     * call on the first blip. Hold on for [ICE_GRACE_MS], then give up.
     */
    private fun onInterrupted(p: CallPeer) {
        if (phase != CallPhase.InCall && phase != CallPhase.Connecting) return
        if (graceJob?.isActive == true) return
        update { it.copy(reconnecting = true) }
        graceJob = ui.launch {
            delay(ICE_GRACE_MS)
            if (peer !== p) return@launch
            val id = _state.value.callId
            graceJob = null
            finish(CONNECTION_LOST)
            if (id != null && id != "pending") terminateSoon(id)
        }
    }

    private fun setInCall() {
        if (phase == CallPhase.Connecting || phase == CallPhase.Ringing) update { it.copy(phase = CallPhase.InCall) }
    }

    /** Wait for ICE gathering to finish, capped at 2.5s (as the web does). */
    private suspend fun awaitGathering(p: CallPeer) {
        withTimeoutOrNull(GATHER_TIMEOUT_MS) { p.awaitGathering() }
    }

    private class MicBlocked : Exception("Permission denied")

    /** A failed call carrying the user-facing message. */
    class CallError(message: String) : Exception(message)

    companion object {
        private const val TAG = "CallManager"

        // android.util.Log is a stub on the plain JVM (unit tests): never let logging throw.
        private fun logD(msg: String) { runCatching { Log.d(TAG, msg) } }
        private fun logW(msg: String, e: Throwable) { runCatching { Log.w(TAG, msg, e) } }
        const val MIC_BLOCKED = "Microphone blocked — allow it and try again"
        const val NO_CALL_PERMISSION = "Customer hasn't granted call permission. Send the WhatsApp template first."
        const val RING_POLL_MS = 2_500L
        const val IDLE_POLL_MS = 12_000L
        const val RERING_COOLDOWN_MS = 12_000L
        const val GATHER_TIMEOUT_MS = 2_500L
        const val MIC_PROMPT_TIMEOUT_MS = 60_000L
        const val MIN_RECORDING_BYTES = 2_000L
        /** Ended calls remembered before old ones are dropped ([markEnded]). */
        const val ENDED_MAX = 256
        /** An ended call older than this is past every use of [endedAt]. */
        const val ENDED_KEEP_MS = 10 * 60_000L
        /** routers/admin.py list_calls marks a call still "ringing" after 2 minutes as missed. */
        const val RING_TIMEOUT_MS = 120_000L

        const val TAKEN_ELSEWHERE = "Another agent already answered this call"
        const val CALL_GONE = "This call has already ended"
        const val ANSWER_OFFLINE = "No connection — couldn't answer the call"
        const val ANSWER_SLOW = "The server took too long — couldn't connect the call"
        const val OUTBOUND_OFFLINE = "No connection — couldn't place the call"
        const val OUTBOUND_SLOW = "The server took too long — couldn't place the call"
        /** connect timed out and no placed call turned up: it may still be ringing them. */
        const val UNCONFIRMED_CALL = "Couldn't confirm the call went through — check Calls before trying again"
        const val SESSION_EXPIRED = "Your session expired — sign in again"
        const val CALLBACK_SAVED = "Callback saved — find them under Calls"
        const val CALLBACK_RETRYING = "Callback not saved yet — retrying"
        const val CALLBACK_FAILED = "Couldn't save the callback"
        const val CONNECTION_LOST = "Connection lost — call ended"

        /** How long a "disconnected" call may take to recover before it is ended. */
        const val ICE_GRACE_MS = 10_000L
        /** How long an answer whose request timed out may take to connect anyway. */
        const val ANSWER_CONFIRM_MS = 8_000L
        /** Waits between the terminate / callback retries. */
        val TERMINATE_RETRY_MS = longArrayOf(2_000L, 5_000L)
        const val PLACED_LOOKUP_GAP_MS = 3_000L
        /** How long sign-out waits for a live call's terminate before clearing the session anyway. */
        const val SIGN_OUT_TERMINATE_MS = 3_000L
        /** The server's clock vs this phone's, when matching the row an outbound call created. */
        const val CLOCK_SKEW_MS = 120_000L

        private fun Throwable.statusOrNull() = (this as? ApiException)?.status

        /** The request left but no answer came back: it may have done its work. */
        private fun Throwable.isAmbiguous(pathEnd: String) =
            this is ApiException && status == 0 && path.endsWith(pathEnd)

        private fun Throwable.isTimeout() = this is ApiException && status == 0 && body.startsWith("timed out")
        private fun Throwable.isOffline() = this is ApiException && status == 0 && !isTimeout()

        /** POST /admin/calls/{id}/answer's 409 (routers/admin.py calls_answer: "call already answered"). */
        private fun Throwable.isTakenElsewhere() =
            this is ApiException && status == 409 && path.endsWith("/answer")

        /** GET /offer's 404 "call offer expired or not found": the caller hung up. */
        private fun Throwable.isOfferGone() =
            this is ApiException && status == 404 && path.endsWith("/offer")

        /** answer()'s catch in lib/callContext.tsx (plus the 409 a colleague's answer causes). */
        internal fun answerError(e: Throwable): String = when {
            e is MicBlocked -> MIC_BLOCKED
            e.isTakenElsewhere() -> TAKEN_ELSEWHERE
            e.isOfferGone() -> CALL_GONE
            e.isTimeout() -> ANSWER_SLOW
            e.isOffline() -> ANSWER_OFFLINE
            e.statusOrNull() == 401 -> SESSION_EXPIRED
            else -> "Couldn't connect the call"
        }

        /** initiateCall()'s catch in lib/callContext.tsx. Never says "permission" but for the 409 (callers key on it). */
        internal fun outboundError(e: Throwable): String = when {
            e is MicBlocked -> MIC_BLOCKED
            e is ApiException && e.status == 409 -> NO_CALL_PERMISSION
            e.isTimeout() -> OUTBOUND_SLOW
            e.isOffline() -> OUTBOUND_OFFLINE
            e.statusOrNull() == 401 -> SESSION_EXPIRED
            else -> "Couldn't place the call"
        }
    }
}
