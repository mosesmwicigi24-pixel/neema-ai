import Foundation
import NeemaCore

/// The softphone's media on this device: WebRTC when the framework is linked
/// (project.yml's `WebRTC` package), else the port that ends a call with the
/// softphone's own "Calling isn't available on this device".
func makeCallMedia() -> CallMedia {
    #if canImport(WebRTC)
    return WebRTCMedia()
    #else
    return DeviceCallMedia()
    #endif
}

#if canImport(WebRTC)
import WebRTC

/// `CallMedia` over the WebRTC SDK (Android `WebRtcMedia`): one factory per
/// process. Recording stays off here (no public sample hook in the iOS
/// SDK — Meta's own transcription stands in; PARITY_MATRIX §8).
final class WebRTCMedia: CallMedia, @unchecked Sendable {
    private static let factory: RTCPeerConnectionFactory = {
        RTCInitializeSSL()
        return RTCPeerConnectionFactory(encoderFactory: RTCDefaultVideoEncoderFactory(), decoderFactory: RTCDefaultVideoDecoderFactory())
    }()

    func createPeer(config: IceConfig, onEvent: @escaping @Sendable (PeerEvent) -> Void) throws -> CallPeer {
        try WebRTCPeer(factory: Self.factory, config: config, onEvent: onEvent)
    }

    func startRecording(micMuted: Bool) throws -> CallRecording? { nil }

    func sweepLeftovers() {}
}

/// One peer connection: audio only, Unified Plan, the ICE servers from
/// ice-config, non-trickle (the caller waits for gathering, capped by
/// `CallManager`). Every SDK callback runs through `rtcGuard`; once closed,
/// nothing touches the native object again (`live`).
final class WebRTCPeer: NSObject, CallPeer, RTCPeerConnectionDelegate, @unchecked Sendable {
    private let factory: RTCPeerConnectionFactory
    private let pc: RTCPeerConnection
    private let onEvent: @Sendable (PeerEvent) -> Void
    private let gathered = Deferred<Void>()
    private let lock = NSLock()
    private var closed = false
    private var track: RTCAudioTrack?

    init(factory: RTCPeerConnectionFactory, config: IceConfig, onEvent: @escaping @Sendable (PeerEvent) -> Void) throws {
        self.factory = factory
        self.onEvent = onEvent
        let rtc = RTCConfiguration()
        rtc.sdpSemantics = .unifiedPlan
        rtc.iceServers = iceSpecs(config).map { RTCIceServer(urlStrings: $0.urls, username: $0.username, credential: $0.credential) }
        guard let pc = factory.peerConnection(with: rtc, constraints: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil), delegate: nil) else {
            throw DeviceCallError("Couldn't create the peer connection")
        }
        self.pc = pc
        super.init()
        pc.delegate = self
    }

    private func live<T>(_ what: String, _ body: () throws -> T) throws -> T {
        lock.lock(); defer { lock.unlock() }
        if closed { throw DeviceCallError("call already ended (\(what))") }
        return try body()
    }

    var hasMic: Bool { track != nil }

    func addMic(enabled: Bool) throws {
        try live("addMic") {
            let constraints = RTCMediaConstraints(mandatoryConstraints: [
                "googEchoCancellation": "true", "googNoiseSuppression": "true", "googAutoGainControl": "true", "googHighpassFilter": "true",
            ], optionalConstraints: nil)
            let src = factory.audioSource(with: constraints)
            let t = factory.audioTrack(with: src, trackId: "neema-mic")
            t.isEnabled = enabled
            track = t
            _ = pc.add(t, streamIds: ["neema"])
        }
    }

    func setMicEnabled(_ enabled: Bool) {
        _ = try? live("mic") { track?.isEnabled = enabled }
    }

    private static let sdpConstraints = RTCMediaConstraints(mandatoryConstraints: ["OfferToReceiveAudio": "true", "OfferToReceiveVideo": "false"], optionalConstraints: nil)

    func createOffer() async throws -> String {
        try await withCheckedThrowingContinuation { cont in
            do {
                try live("createOffer") {
                    pc.offer(for: Self.sdpConstraints) { sdp, err in
                        if let s = sdp { cont.resume(returning: s.sdp) } else { cont.resume(throwing: DeviceCallError(err?.localizedDescription ?? "no offer")) }
                    }
                }
            } catch { cont.resume(throwing: error) }
        }
    }

    func createAnswer() async throws -> String {
        try await withCheckedThrowingContinuation { cont in
            do {
                try live("createAnswer") {
                    pc.answer(for: Self.sdpConstraints) { sdp, err in
                        if let s = sdp { cont.resume(returning: s.sdp) } else { cont.resume(throwing: DeviceCallError(err?.localizedDescription ?? "no answer")) }
                    }
                }
            } catch { cont.resume(throwing: error) }
        }
    }

    func setLocal(_ type: SdpType, _ sdp: String) async throws {
        let desc = RTCSessionDescription(type: type == .offer ? .offer : .answer, sdp: sdp)
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            do {
                try live("setLocal") {
                    pc.setLocalDescription(desc) { err in
                        if let e = err { cont.resume(throwing: DeviceCallError(e.localizedDescription)) } else { cont.resume() }
                    }
                }
            } catch { cont.resume(throwing: error) }
        }
    }

    func setRemote(_ type: SdpType, _ sdp: String) async throws {
        let desc = RTCSessionDescription(type: type == .offer ? .offer : .answer, sdp: sdp)
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            do {
                try live("setRemote") {
                    pc.setRemoteDescription(desc) { err in
                        if let e = err { cont.resume(throwing: DeviceCallError(e.localizedDescription)) } else { cont.resume() }
                    }
                }
            } catch { cont.resume(throwing: error) }
        }
    }

    func awaitGathering() async throws { try await gathered.value() }

    var localSdp: String? { (try? live("localSdp") { pc.localDescription?.sdp }) ?? nil }

    /// Torn down off the calling thread so close() never runs on the thread that delivers events.
    func close() {
        _ = gathered.complete(())
        lock.lock()
        if closed { lock.unlock(); return }
        closed = true
        let t = track
        track = nil
        lock.unlock()
        let pc = self.pc
        let lock = self.lock
        DispatchQueue.global(qos: .userInitiated).async {
            // Under the lock: a setRemote / createOffer already inside native code finishes first.
            lock.lock(); defer { lock.unlock() }
            t?.isEnabled = false
            pc.close()
        }
    }

    // MARK: RTCPeerConnectionDelegate

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCPeerConnectionState) {
        rtcGuard("connection") {
            switch newState {
            case .connected: onEvent(.connected)
            // A blip, not the end: CallManager gives ICE a grace period to recover.
            case .disconnected: onEvent(.interrupted)
            case .failed, .closed: onEvent(.ended)
            default: break
            }
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {
        rtcGuard("ice") { if newState == .connected || newState == .completed { onEvent(.connected) } }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {
        rtcGuard("gathering") { if newState == .complete { _ = gathered.complete(()) } }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd rtpReceiver: RTCRtpReceiver, streams mediaStreams: [RTCMediaStream]) {
        // Remote audio plays through the audio device module on its own.
        rtcGuard("track") { rtpReceiver.track?.isEnabled = true }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
    func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {}
}
#endif
