import Foundation

/*
 * The seams around the softphone's logic (Android `feature/calls/CallPorts.kt`).
 * `CallManager` holds every rule the web's lib/callContext.tsx has (phases, the
 * re-ring cooldown, the poll cadence, the WebSocket frames, the error mapping);
 * everything that needs a device — WebRTC, the speakers, the ringtone, CallKit —
 * sits behind these small protocols so the rules run (and are tested) on Linux.
 */

/// The backend calls the softphone makes (callsApi in lib/api.ts, `NeemaApi.calls` here).
public protocol CallApi: AnyObject {
    func list() async throws -> [Call]
    /// GET /admin/calls/{id}: one call's row now (the re-sync after the phone was offline).
    func get(_ callId: String) async throws -> Call
    func iceConfig() async throws -> IceConfig
    func offer(_ callId: String) async throws -> CallOffer
    /// Accept with our SDP. WhatsApp: our answer (the reply carries nothing to
    /// apply). Messenger: our OFFER — the reply carries Meta's answer and,
    /// sometimes, a renegotiation offer (CALLING_UX.md §2.0).
    func answer(_ callId: String, sdp: String) async throws -> CallSdpResponse
    func terminate(_ callId: String) async throws
    func callback(_ callId: String) async throws
    /// Returns the new call's id.
    func connect(to: String, sdp: String, name: String?) async throws -> String
    /// GET /admin/calls/permission: has this customer allowed business calls?
    func permission(_ waId: String) async throws -> CallPermission
    /// GET /calls/channels: which channels can take / place a call right now.
    func channels() async throws -> CallChannels
    /// POST /calls/connect `{channel: messenger, psid, sdp}`: Meta's answer comes back at once.
    func connectMessenger(psid: String, sdp: String, name: String?) async throws -> CallSdpResponse
    /// GET /calls/permission?channel=messenger&psid=: did they accept our call request?
    func messengerPermission(_ psid: String) async throws -> CallPermission
    /// POST /calls/request-permission `{channel: messenger, psid}`: Messenger's `calling_optin` (Accept / Decline).
    func requestMessengerPermission(_ psid: String) async throws -> PermissionRequestResponse
    /// Sends WhatsApp's call-permission request: `{permission, route, already_permitted}`.
    /// A refusal is an `ApiError` carrying the server's `code` / `action` (template_required, 138009, …).
    func requestPermission(to: String, name: String?) async throws -> PermissionRequestResponse
    /// POST /admin/calls/{id}/recording — pass `UploadFile.of` a file so it streams from disk.
    func uploadRecording(_ callId: String, file: UploadFile) async throws
}

/// `CallApi` over the real HTTP client.
public final class NeemaCallApi: CallApi {
    private let api: NeemaApi
    public init(_ api: NeemaApi) { self.api = api }
    public func list() async throws -> [Call] { try await api.calls.list() }
    public func get(_ callId: String) async throws -> Call { try await api.calls.get(callId: callId) }
    public func iceConfig() async throws -> IceConfig { try await api.calls.iceConfig() }
    public func offer(_ callId: String) async throws -> CallOffer { try await api.calls.offer(callId: callId) }
    public func answer(_ callId: String, sdp: String) async throws -> CallSdpResponse { try await api.calls.answer(callId: callId, sdp: sdp) }
    public func terminate(_ callId: String) async throws { _ = try await api.calls.terminate(callId: callId) }
    public func callback(_ callId: String) async throws { _ = try await api.calls.callback(callId: callId) }
    public func connect(to: String, sdp: String, name: String?) async throws -> String { try await api.calls.connect(to: to, sdp: sdp, name: name).callId }
    public func permission(_ waId: String) async throws -> CallPermission { try await api.calls.permission(waId: waId) }
    public func channels() async throws -> CallChannels { try await api.calls.channels() }
    public func connectMessenger(psid: String, sdp: String, name: String?) async throws -> CallSdpResponse {
        try await api.calls.connectMessenger(psid: psid, sdp: sdp, name: name)
    }
    public func messengerPermission(_ psid: String) async throws -> CallPermission { try await api.calls.messengerPermission(psid: psid) }
    public func requestMessengerPermission(_ psid: String) async throws -> PermissionRequestResponse { try await api.calls.requestMessengerPermission(psid: psid) }
    public func requestPermission(to: String, name: String?) async throws -> PermissionRequestResponse { try await api.calls.requestPermission(to: to, name: name) }
    public func uploadRecording(_ callId: String, file: UploadFile) async throws { _ = try await api.calls.uploadRecording(callId: callId, file: file) }
}

/// What a peer connection reports back (RTCPeerConnection's state-change handlers).
public enum PeerEvent: Equatable, Sendable {
    /// connectionState "connected", or iceConnectionState "connected" / "completed".
    case connected
    /// connectionState "disconnected": the network blipped (a tunnel, a cell
    /// handover, Wi-Fi to mobile data). ICE keeps checking and often recovers
    /// on its own, so this is not the end of the call yet.
    case interrupted
    /// connectionState "failed" / "closed": the media path is gone for good.
    case ended
}

public enum SdpType: String, Equatable, Sendable { case offer = "Offer", answer = "Answer" }

/// One RTCPeerConnection with the agent's microphone on it.
public protocol CallPeer: AnyObject {
    /// getUserMedia + addTrack: the agent's mic (echo cancellation, noise suppression, auto gain).
    /// Throws when the device refuses (the audio stack, WebRTC's native side).
    func addMic(enabled: Bool) throws
    /// True once `addMic` has run — the web's `localStreamRef.current`.
    var hasMic: Bool { get }
    func setMicEnabled(_ enabled: Bool)
    func createOffer() async throws -> String
    func createAnswer() async throws -> String
    func setLocal(_ type: SdpType, _ sdp: String) async throws
    func setRemote(_ type: SdpType, _ sdp: String) async throws
    /// Resolves when ICE gathering completes (the caller caps the wait at 2.5 s).
    func awaitGathering() async throws
    /// pc.localDescription.sdp — with the gathered candidates, when there are any.
    var localSdp: String? { get }
    func close()
}

/// A started call recording (both sides mixed, as the web's Web-Audio mix).
public protocol CallRecording: AnyObject {
    var micMuted: Bool { get set }
    /// Stops and returns the encoded file, or nil when nothing usable was captured. Blocking.
    func stop() -> URL?
}

/// Builds peer connections and recordings — WebRTC in the app, a fake in tests.
public protocol CallMedia: AnyObject {
    /// `onEvent` may be called on any thread. Throws when WebRTC can't be set up.
    func createPeer(config: IceConfig, onEvent: @escaping @Sendable (PeerEvent) -> Void) throws -> CallPeer
    /// Starts recording the live call, or returns nil (or throws) when it can't.
    func startRecording(micMuted: Bool) throws -> CallRecording?
    /// Deletes what an earlier process killed mid-call left behind (the raw
    /// audio tracks of an unfinished recording). Called once at start-up.
    func sweepLeftovers()
}

public extension CallMedia {
    func sweepLeftovers() {}
}

/// The ringtone, vibration and the incoming-call alert (CallKit on iOS).
public protocol CallRinger: AnyObject {
    func startRinging()
    func stopRinging()
    /// `from`: their number (nil on Messenger — a PSID is never shown); `app`: "WhatsApp" / "Messenger".
    func postIncoming(callId: String, who: String, from: String?, app: String)
    func cancelIncoming()
}

/// Where a call's audio plays: the phone's earpiece, its loudspeaker, a wired headset or a Bluetooth one.
public enum AudioRouteKind: Equatable, Hashable, Sendable { case earpiece, speaker, wired, bluetooth }

/// One output a call can use (`name`: the Bluetooth device's own name, when the system gives one).
public struct AudioRoute: Equatable, Hashable, Sendable {
    public let kind: AudioRouteKind
    public let name: String?
    public init(_ kind: AudioRouteKind, name: String? = nil) { self.kind = kind; self.name = name }

    /// The words on the audio button and in its list.
    public var label: String {
        switch kind {
        case .earpiece: return "Phone"
        case .speaker: return "Speaker"
        case .wired: return "Headset"
        case .bluetooth:
            let n = (name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return n.isEmpty ? "Bluetooth" : n
        }
    }
    public var isHeadset: Bool { kind == .wired || kind == .bluetooth }

    public static let earpiece = AudioRoute(.earpiece)
    public static let speaker = AudioRoute(.speaker)
}

/// In-call audio (the audio session, the output route). Which route a call
/// uses is `CallManager`'s rule; this port only reports what is plugged in and
/// applies the choice.
public protocol CallAudio: AnyObject {
    /// A call is starting: the voice-chat session, and `route`.
    func enter(route: AudioRoute)
    /// The microphone is live on the call (the agent allowed it).
    func micLive()
    func leave()
    /// Plays the call through `route` (one of `routes`).
    func select(route: AudioRoute)
    /// The outputs a call can use right now, earpiece / speaker first, then any
    /// headset — updated as headsets are plugged in, paired or unplugged.
    var routes: Watched<[AudioRoute]> { get }
}

/// Runs a WebRTC callback's body and swallows what it throws: a native-side
/// observer must never bring the app down (Android's `rtcGuard`). The error
/// is handed to the crash hook with the callback's name.
public func rtcGuard(_ name: String, _ body: () throws -> Void) {
    do { try body() } catch { CrashHooks.recordNonFatal?(error, "rtc:\(name)") }
}

/// The device's call audio failing under WebRTC (the microphone taken by
/// another app, a recorder that never started, the speaker refusing): WebRTC
/// reports it on its own threads, far from the call. `CallManager` puts it on
/// the call card — a call never goes silent without a word.
public enum CallAudioTrouble {
    /// true: the microphone; false: the speaker / earpiece.
    public static let events = Signal<Bool>(buffer: 8)
    public static func mic() { events.emit(true) }
    public static func speaker() { events.emit(false) }
}

/// A failure the call flow doesn't expect (not the server's, not the network's,
/// not a refused microphone) is handed here so the trace reaches the team
/// (cycle 7's crash reporter wires it); the agent only sees the call fail.
public enum CrashHooks {
    nonisolated(unsafe) public static var recordNonFatal: ((Error, String) -> Void)?
}
