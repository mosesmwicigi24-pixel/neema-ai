import Foundation
import AVFoundation
import AudioToolbox
import CallKit
import NeemaCore

// The softphone's platform ports on iOS (Android: WebRtcMedia / CallRinger /
// CallAudio). The call rules live in NeemaCore's CallManager; these only
// touch the device.

/// Where a call's audio plays: AVAudioSession in voice-chat mode, its routes
/// (earpiece / speaker, and any wired or Bluetooth headset), and the choice.
final class SessionCallAudio: CallAudio, @unchecked Sendable {
    let routes = Watched<[AudioRoute]>([.earpiece, .speaker])
    private var observer: NSObjectProtocol?

    init() {
        observer = NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: nil) { [weak self] _ in
            self?.refreshRoutes()
        }
        refreshRoutes()
    }

    deinit { if let o = observer { NotificationCenter.default.removeObserver(o) } }

    private func refreshRoutes() {
        let session = AVAudioSession.sharedInstance()
        var list: [AudioRoute] = [.earpiece, .speaker]
        for port in session.currentRoute.outputs + (session.availableInputs ?? []) {
            switch port.portType {
            case .headphones, .headsetMic, .usbAudio: if !list.contains(where: { $0.kind == .wired }) { list.append(AudioRoute(.wired, name: port.portName)) }
            case .bluetoothHFP, .bluetoothA2DP, .bluetoothLE, .carAudio: if !list.contains(where: { $0.kind == .bluetooth }) { list.append(AudioRoute(.bluetooth, name: port.portName)) }
            default: break
            }
        }
        if list != routes.value { routes.update(list) }
    }

    func enter(route: AudioRoute) {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetooth, .allowBluetoothA2DP])
        try? session.setActive(true, options: [])
        select(route: route)
    }

    func micLive() {}

    func leave() {
        let session = AVAudioSession.sharedInstance()
        try? session.overrideOutputAudioPort(.none)
        try? session.setActive(false, options: [.notifyOthersOnDeactivation])
    }

    func select(route: AudioRoute) {
        let session = AVAudioSession.sharedInstance()
        switch route.kind {
        case .speaker: try? session.overrideOutputAudioPort(.speaker)
        case .earpiece: try? session.overrideOutputAudioPort(.none)
        case .wired, .bluetooth:
            try? session.overrideOutputAudioPort(.none)
            if let input = (session.availableInputs ?? []).first(where: { $0.portName == route.name }) { try? session.setPreferredInput(input) }
        }
    }
}

/// The incoming-call alert through CallKit: the system's own full-screen call
/// UI and ringtone, on the lock screen too, and Answer / Decline handed back
/// to the softphone. In the foreground the card is the alert, so `postIncoming`
/// is only called when the app leaves the screen mid-ring.
final class CallKitRinger: NSObject, CallRinger, CXProviderDelegate, @unchecked Sendable {
    private let provider: CXProvider
    private var current: (uuid: UUID, callId: String)?
    /// What the softphone should do with the system UI's answer ("answer" / "decline", the call id).
    var onAction: ((String, String) -> Void)?
    private var ringTimer: Timer?

    override init() {
        let cfg = CXProviderConfiguration()
        cfg.supportsVideo = false
        cfg.maximumCallGroups = 1
        cfg.maximumCallsPerCallGroup = 1
        cfg.supportedHandleTypes = [.phoneNumber, .generic]
        cfg.includesCallsInRecents = false
        provider = CXProvider(configuration: cfg)
        super.init()
        provider.setDelegate(self, queue: nil)
    }

    /// The card is on screen (the app in front): the system's alert tone with a
    /// buzz, every two seconds, until the call is taken or goes. In the
    /// background CallKit rings the device's own ringtone for the alert.
    func startRinging() {
        if ringTimer != nil { return }
        AudioServicesPlayAlertSound(1023)
        ringTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in AudioServicesPlayAlertSound(1023) }
    }

    func stopRinging() {
        ringTimer?.invalidate()
        ringTimer = nil
    }

    func postIncoming(callId: String, who: String, from: String?, app: String) {
        let uuid = UUID()
        current = (uuid, callId)
        let update = CXCallUpdate()
        update.remoteHandle = CXHandle(type: from == nil ? .generic : .phoneNumber, value: from.map { "+\($0)" } ?? who)
        update.localizedCallerName = "\(who) · \(app)"
        update.hasVideo = false
        provider.reportNewIncomingCall(with: uuid, update: update) { _ in }
    }

    func cancelIncoming() {
        guard let c = current else { return }
        current = nil
        provider.reportCall(with: c.uuid, endedAt: nil, reason: .remoteEnded)
    }

    // CXProviderDelegate
    func providerDidReset(_ provider: CXProvider) { current = nil }

    func provider(_ provider: CXProvider, perform action: CXAnswerCallAction) {
        if let c = current, c.uuid == action.callUUID { onAction?("answer", c.callId) }
        action.fulfill()
    }

    func provider(_ provider: CXProvider, perform action: CXEndCallAction) {
        if let c = current, c.uuid == action.callUUID { onAction?("decline", c.callId); current = nil }
        action.fulfill()
    }
}

/// WebRTC on the device. The WebRTC framework (stasel/WebRTC) is not yet part
/// of the project (PLAN.md, cycle 5): until it is, a call's media cannot be
/// set up, and the softphone ends the call with "Calling isn't available on
/// this device" (its DeviceCallError path) — never a crash.
final class DeviceCallMedia: CallMedia, @unchecked Sendable {
    func createPeer(config: IceConfig, onEvent: @escaping @Sendable (PeerEvent) -> Void) throws -> CallPeer {
        throw DeviceCallError("WebRTC is not linked into this build")
    }

    func startRecording(micMuted: Bool) throws -> CallRecording? { nil }

    func sweepLeftovers() {}
}
