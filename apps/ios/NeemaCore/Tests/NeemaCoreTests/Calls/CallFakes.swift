import Foundation
import XCTest
@testable import NeemaCore

/// Android `calls/CallFakes.kt`: an in-memory backend for the softphone that
/// records every call and fails on demand, plus the peer, media, ringer and
/// audio fakes. Every field is read and written from the main actor (the
/// tests and the manager both live there); the few handlers the manager calls
/// from the cooperative pool guard themselves with the lock.
final class FakeCallApi: CallApi, @unchecked Sendable {
    private let lock = NSLock()
    private var _log: [String] = []
    var log: [String] { lock.sync { _log } }
    private func logged(_ s: String) { lock.sync { _log.append(s) } }
    var calls: [Call] = []
    var listError: Error?
    var ice = IceConfig(iceServers: [], record: true)
    var iceError: Error?
    var offerSdp = "v=0 caller-offer"
    var offerError: Error?
    var answerError: Error?
    var connectId = "wacid.out1"
    var connectError: Error?
    /// When set, connect() waits for it (to hang up mid-placement).
    var connectGate: Deferred<Void>?
    var permissionError: Error?
    /// Failures handed out one per call, in order (then success): terminate / callback / upload.
    var terminateErrors: [Error] = []
    var callbackErrors: [Error] = []
    var uploadErrors: [Error] = []
    /// When set, answer() waits for it (to reply late, or never).
    var answerGate: Deferred<Void>?
    /// When set, terminate() waits for it (a server that answers late, or never).
    var terminateGate: Deferred<Void>?
    /// When set, callback() waits for it.
    var callbackGate: Deferred<Void>?
    /// callId to (filename, mime type, bytes read from the streamed file).
    var uploads: [(callId: String, filename: String, mime: String, bytes: Int)] = []
    var lastAnswerSdp: String?
    /// The last recording was handed over as a streamed file, not bytes in memory.
    var lastUploadStreamed: Bool?
    var lastConnect: (to: String, sdp: String, name: String?)?
    /// GET /admin/calls/{id}: the row from `calls`, else 404 (as the handler).
    var getError: Error?
    /// What GET /calls/permission says for everyone.
    var permissionStatus = "unknown"
    /// The whole answer of GET /calls/permission (overrides `permissionStatus` when set).
    var permission: CallPermission?
    /// When set, permission() waits for it (a slow Meta read).
    var permissionGate: Deferred<Void>?
    var permissionReadError: Error?
    /// Messenger calls (CALLING_UX.md §2.0): which call ids ring on Messenger (their offer route says offer_required).
    var messengerCalls: Set<String> = []
    /// What Meta answers our Messenger offer with (accept / connect): the answer SDP and the renegotiation.
    var messengerAnswer: String? = "v=0 meta-answer"
    var messengerRenegotiation: JSONValue?
    /// GET /calls/channels (Messenger off — the server's switch).
    var channels = CallChannels()
    var channelsError: Error?
    var messengerConnectId = "c_msg.out1"
    var lastMessengerConnect: (psid: String, sdp: String, name: String?)?
    /// GET /calls/channels reads (kept out of `log`: the softphone reads it at start and on every reconnect).
    var channelsReads = 0
    /// What POST /calls/request-permission answers (default: sent free-form, now "requested").
    var requestResponse: PermissionRequestResponse?

    func list() async throws -> [Call] { logged("list"); if let e = listError { throw e }; return calls }
    func get(_ callId: String) async throws -> Call {
        logged("get \(callId)"); if let e = getError { throw e }
        if let c = calls.first(where: { $0.callId == callId }) { return c }
        throw ApiError(status: 404, method: "GET", path: "/admin/calls/\(callId)", body: #"{"detail":"Call not found"}"#)
    }
    func permission(_ waId: String) async throws -> CallPermission {
        logged("permission \(waId)"); if let g = permissionGate { try await g.value() }; if let e = permissionReadError { throw e }
        return permission ?? CallPermission(waId: waId, status: permissionStatus)
    }
    func iceConfig() async throws -> IceConfig { logged("ice-config"); if let e = iceError { throw e }; return ice }
    func offer(_ callId: String) async throws -> CallOffer {
        logged("offer \(callId)"); if let e = offerError { throw e }
        if messengerCalls.contains(callId) { return CallOffer(callId: callId, sdp: nil, from: "7788990011", channel: "messenger", offerRequired: true) }
        return CallOffer(callId: callId, sdp: offerSdp, from: "254712345678")
    }
    func answer(_ callId: String, sdp: String) async throws -> CallSdpResponse {
        logged("answer \(callId)"); lastAnswerSdp = sdp; if let g = answerGate { try await g.value() }; if let e = answerError { throw e }
        if messengerCalls.contains(callId) {
            return CallSdpResponse(ok: true, callId: callId, channel: "messenger", sdp: messengerAnswer, sdpType: "answer", renegotiation: messengerRenegotiation)
        }
        return CallSdpResponse(ok: true, callId: callId)
    }
    func channels() async throws -> CallChannels { channelsReads += 1; if let e = channelsError { throw e }; return channels }
    func connectMessenger(psid: String, sdp: String, name: String?) async throws -> CallSdpResponse {
        logged("connect-messenger \(psid)"); lastMessengerConnect = (psid, sdp, name)
        if let g = connectGate { try await g.value() }
        if let e = connectError { throw e }
        return CallSdpResponse(ok: true, callId: messengerConnectId, channel: "messenger", sdp: messengerAnswer, sdpType: "answer", renegotiation: messengerRenegotiation)
    }
    func messengerPermission(_ psid: String) async throws -> CallPermission {
        logged("permission messenger \(psid)"); if let g = permissionGate { try await g.value() }; if let e = permissionReadError { throw e }
        var p = permission ?? CallPermission(waId: nil, status: permissionStatus)
        p.waId = nil; p.channel = "messenger"; p.externalId = psid
        return p
    }
    func requestMessengerPermission(_ psid: String) async throws -> PermissionRequestResponse {
        logged("request-permission messenger \(psid)"); if let e = permissionError { throw e }
        return requestResponse ?? PermissionRequestResponse(ok: true, permission: CallPermission(waId: nil, status: "requested", channel: "messenger", externalId: psid),
                                                            route: "calling_optin", alreadyPermitted: false)
    }
    func terminate(_ callId: String) async throws {
        logged("terminate \(callId)"); if let g = terminateGate { try await g.value() }
        if !terminateErrors.isEmpty { throw terminateErrors.removeFirst() }
    }
    func callback(_ callId: String) async throws {
        logged("callback \(callId)"); if let g = callbackGate { try await g.value() }
        if !callbackErrors.isEmpty { throw callbackErrors.removeFirst() }
    }
    func connect(to: String, sdp: String, name: String?) async throws -> String {
        logged("connect \(to)"); lastConnect = (to, sdp, name)
        if let g = connectGate { try await g.value() }
        if let e = connectError { throw e }
        return connectId
    }
    func requestPermission(to: String, name: String?) async throws -> PermissionRequestResponse {
        logged("request-permission \(to)"); if let e = permissionError { throw e }
        return requestResponse ?? PermissionRequestResponse(ok: true, permission: CallPermission(waId: to, status: "requested"), route: "free_form", alreadyPermitted: false)
    }
    func uploadRecording(_ callId: String, file: UploadFile) async throws {
        logged("recording \(callId)"); if !uploadErrors.isEmpty { throw uploadErrors.removeFirst() }
        var streamed = false
        var bytes = 0
        switch file.source {
        case .file(let url): streamed = true; bytes = Int((try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int64) ?? 0)
        case .data(let d): bytes = d.count
        }
        lastUploadStreamed = streamed
        uploads.append((callId, file.filename, file.mimeType, bytes))
    }
}

/// A peer connection that does what it's told and remembers it.
final class FakePeer: CallPeer, @unchecked Sendable {
    let onEvent: @Sendable (PeerEvent) -> Void
    private let lock = NSLock()
    private var _ops: [String] = []
    var ops: [String] { lock.sync { _ops } }
    private func op(_ s: String) { lock.sync { _ops.append(s) } }
    var micEnabled: Bool?
    var closed = false
    let gathering = Deferred<Void>()
    var failSetRemote: Error?
    /// Every native step asked of this peer after close(): on a phone that is a
    /// PeerConnection used after dispose() — a native crash no catch can stop.
    var usedAfterClose: [String] = []
    /// When set, the SDP steps wait for it (a hang-up can land while WebRTC works).
    var sdpGate: Deferred<Void>?
    var hasMic = false
    init(onEvent: @escaping @Sendable (PeerEvent) -> Void) { self.onEvent = onEvent }
    func addMic(enabled: Bool) { if closed { usedAfterClose.append("addMic") }; hasMic = true; micEnabled = enabled; op("addMic(\(enabled))") }
    func setMicEnabled(_ enabled: Bool) { micEnabled = enabled }
    func createOffer() async throws -> String { if closed { usedAfterClose.append("createOffer") }; op("createOffer"); if let g = sdpGate { try await g.value() }; return "v=0 our-offer" }
    func createAnswer() async throws -> String { if closed { usedAfterClose.append("createAnswer") }; op("createAnswer"); if let g = sdpGate { try await g.value() }; return "v=0 our-answer" }
    func setLocal(_ type: SdpType, _ sdp: String) async throws { if closed { usedAfterClose.append("setLocal") }; op("setLocal(\(type.rawValue),\(sdp))"); if let g = sdpGate { try await g.value() } }
    func setRemote(_ type: SdpType, _ sdp: String) async throws {
        if closed { usedAfterClose.append("setRemote") }
        if let e = failSetRemote { throw e }
        op("setRemote(\(type.rawValue),\(sdp))"); if let g = sdpGate { try await g.value() }
    }
    func awaitGathering() async throws { try await gathering.value() }
    var localSdp: String? {
        if closed { usedAfterClose.append("localSdp") }
        return ops.last { $0.hasPrefix("setLocal") }.map { "\($0)+candidates" }
    }
    func close() { closed = true }
}

final class FakeRecording: CallRecording, @unchecked Sendable {
    let file: URL
    var stopped = false
    var micMuted: Bool
    init(bytes: Int, micMuted: Bool) {
        file = FileManager.default.temporaryDirectory.appendingPathComponent("call-\(UUID().uuidString).m4a")
        try? Data(count: bytes).write(to: file)
        self.micMuted = micMuted
    }
    func stop() -> URL? { stopped = true; return file }
    var exists: Bool { FileManager.default.fileExists(atPath: file.path) }
}

final class FakeMedia: CallMedia, @unchecked Sendable {
    var peers: [FakePeer] = []
    var peer: FakePeer { peers.last! }
    var configs: [IceConfig] = []
    var recordingBytes = 48_000
    var recordings: [FakeRecording] = []
    /// Handed to each new peer: its SDP steps wait on it.
    var sdpGate: Deferred<Void>?
    /// Complete ICE gathering immediately (otherwise the 2.5 s cap applies).
    var gatherAtOnce = true
    var sweeps = 0
    func createPeer(config: IceConfig, onEvent: @escaping @Sendable (PeerEvent) -> Void) -> CallPeer {
        configs.append(config)
        let p = FakePeer(onEvent: onEvent)
        if gatherAtOnce { p.gathering.complete(()) }
        p.sdpGate = sdpGate
        peers.append(p)
        return p
    }
    func startRecording(micMuted: Bool) -> CallRecording? {
        let r = FakeRecording(bytes: recordingBytes, micMuted: micMuted)
        recordings.append(r)
        return r
    }
    func sweepLeftovers() { sweeps += 1 }
}

final class FakeRinger: CallRinger {
    var ringing = false
    var ringStarts = 0
    var posted: [(callId: String, who: String, from: String?)] = []
    var showing = false
    /// The app each posted alert named ("WhatsApp" / "Messenger").
    var postedApps: [String] = []
    func startRinging() { ringing = true; ringStarts += 1 }
    func stopRinging() { ringing = false }
    func postIncoming(callId: String, who: String, from: String?, app: String) { posted.append((callId, who, from)); postedApps.append(app); showing = true }
    func cancelIncoming() { showing = false }
}

final class FakeAudio: CallAudio {
    var inCall = false
    var enters = 0
    /// Where the call's audio is going (nil outside a call and before any choice).
    var route: AudioRoute?
    var speakerOn: Bool { route?.kind == .speaker }
    /// The microphone is live on the call (only ever after the mic was allowed).
    var micService = false
    var micLives = 0
    let routes = Watched<[AudioRoute]>([.earpiece, .speaker])
    /// A headset is plugged in / paired.
    func plug(_ r: AudioRoute) { routes.value = routes.value + [r] }
    /// …and gone again.
    func unplug(_ r: AudioRoute) { routes.value = routes.value.filter { $0 != r } }
    func enter(route: AudioRoute) { if !inCall { enters += 1 }; inCall = true; self.route = route }
    func micLive() { micLives += 1; micService = true }
    func leave() { inCall = false; route = nil; micService = false }
    func select(route: AudioRoute) { self.route = route }
}
