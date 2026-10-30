import SwiftUI
import AVFoundation
import NeemaCore

/// What the call screen's buttons do (every one a no-op by default, for previews and tests).
struct CallActions {
    var answer: () -> Void = {}
    var decline: () -> Void = {}
    var callback: () -> Void = {}
    var toggleMute: () -> Void = {}
    var toggleSpeaker: () -> Void = {}
    var hangup: () -> Void = {}
    var selectRoute: (AudioRoute) -> Void = { _ in }
    var openChat: () -> Void = {}
    var minimise: () -> Void = {}
    var expand: () -> Void = {}
    var redial: () -> Void = {}
    var dismiss: () -> Void = {}
    var sendCallRequest: () -> Void = {}
    var openSettings: () -> Void = {}
    var callNow: () -> Void = {}
    /// Settings → WhatsApp calling (admins, after a template_required refusal).
    var openCallingSettings: () -> Void = {}
    var declineWaiting: () -> Void = {}
    var callbackWaiting: () -> Void = {}
    var endAndAnswer: () -> Void = {}

    /// What a wrap-up action does.
    func run(_ a: WrapAction) -> () -> Void {
        switch a {
        case .openChat, .message: return openChat
        case .callAgain, .callBack, .tryAgain: return redial
        case .sendCallRequest: return sendCallRequest
        case .openSettings: return openSettings
        case .callNow: return callNow
        case .callingSettings: return openCallingSettings
        case .done, .cancel: return dismiss
        }
    }

    /// The softphone's own actions, wired to the shell (Android `rememberCallActions`).
    @MainActor static func of(_ app: AppModel) -> CallActions {
        let calls = app.calls
        return CallActions(
            answer: { calls.answer() }, decline: { calls.hangup() }, callback: { calls.callback() },
            toggleMute: { calls.toggleMute() }, toggleSpeaker: { calls.toggleSpeaker() }, hangup: { calls.hangup() },
            selectRoute: { calls.selectRoute($0) },
            openChat: { if let k = calls.openChat() { app.openConversationFor(k) } },
            minimise: { calls.minimise() }, expand: { calls.expand() }, redial: { calls.redial() }, dismiss: { calls.dismiss() },
            sendCallRequest: { calls.sendCallRequest() },
            openSettings: {
                if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url, options: [:], completionHandler: nil) }
                calls.dismiss()
            },
            callNow: { calls.callNow() },
            openCallingSettings: { calls.dismiss(); app.navigate(.settings) },
            declineWaiting: { calls.declineWaiting() }, callbackWaiting: { calls.callbackWaiting() }, endAndAnswer: { calls.endAndAnswer() }
        )
    }
}

/// The softphone's state as SwiftUI reads it (the shell composes one).
@MainActor
final class CallCardModel: ObservableObject {
    @Published private(set) var state: CallUiState
    @Published private(set) var micRequest = false
    @Published private(set) var grant: PermissionGrant?
    private var subs: [Subscription] = []

    init(calls: CallManager) {
        state = calls.state.value
        micRequest = calls.micRequest.value
        grant = calls.permissionGranted.value
        subs.append(calls.state.observe { [weak self] v in onMainActor { self?.state = v } })
        subs.append(calls.micRequest.observe { [weak self] v in onMainActor { self?.micRequest = v } })
        subs.append(calls.permissionGranted.observe { [weak self] v in onMainActor { self?.grant = v } })
    }

    func close() { subs.forEach { $0.cancel() }; subs = [] }

    /// Whether the call card docks beside the view (a view `contentWidth` wide
    /// with room for it and a usable view: a big iPad on its side) rather than
    /// covering it. A minimised call is the top bar, whatever the width.
    func docks(contentWidth: CGFloat) -> Bool { callDocks(phase: state.phase, minimised: state.minimised, contentWidth: contentWidth) }
    /// Whether `CallBar` takes room at the top of the content.
    var barShown: Bool { (state.minimised && state.phase != .idle) || grant != nil }
}

// `CALL_PANEL_WIDTH` and `callDocks(phase:minimised:contentWidth:)` are the core's (`Shell/DockRules.swift`).

/// The call over the content area. Renders nothing when idle, and only the
/// `CallBar` (composed by the shell above the content) while minimised.
struct CallStage: View {
    @EnvironmentObject private var app: AppModel
    var body: some View {
        if let m = app.callCard {
            CallStageBody(model: m)
        }
    }
}

private struct CallStageBody: View {
    @ObservedObject var model: CallCardModel
    @EnvironmentObject private var app: AppModel
    var body: some View {
        let c = model.state
        if c.phase != .idle && !c.minimised {
            CallCard(c: c, actions: CallActions.of(app))
                .transition(.opacity)
        }
    }
}

/// The microphone prompt a call raises (`CallManager.micRequest`) — composed
/// once by the shell, and never moved: the call card itself moves (over the
/// view on a phone, docked beside it on a wide tablet).
struct CallMicHost: View {
    @EnvironmentObject private var app: AppModel
    var body: some View {
        if let m = app.callCard { CallMicHostBody(model: m) }
    }
}

private struct CallMicHostBody: View {
    @ObservedObject var model: CallCardModel
    @EnvironmentObject private var app: AppModel
    var body: some View {
        Color.clear.frame(width: 0, height: 0)
            .onChange(of: model.micRequest) { _, asked in
                guard asked else { return }
                // getUserMedia's prompt: a call is waiting for the microphone.
                ask()
            }
            .onAppear { if model.micRequest { ask() } }
    }

    private func ask() {
        let calls = app.calls
        AVAudioApplication.requestRecordPermission { granted in
            Task { @MainActor in calls.onMicResult(granted) }
        }
    }
}

/// What sits between the app's top bar and the view while a call is minimised
/// (§6), a second caller waits, or a customer just allowed calls: the rest of
/// Neema stays usable under it. Nothing when none of these holds.
struct CallBar: View {
    @EnvironmentObject private var app: AppModel
    var body: some View {
        if let m = app.callCard { CallBarBody(model: m) }
    }
}

private struct CallBarBody: View {
    @ObservedObject var model: CallCardModel
    @EnvironmentObject private var app: AppModel
    var body: some View {
        let c = model.state
        let bar = c.minimised && c.phase != .idle
        if bar || model.grant != nil {
            let actions = CallActions.of(app)
            VStack(spacing: 0) {
                if let g = model.grant { PermissionGrantBanner(g: g, onCall: { app.calls.callGranted() }, onDismiss: { app.calls.dismissGrant() }) }
                if bar {
                    MinimisedCallBar(c: c, actions: actions)
                    if let w = c.waiting { WaitingBanner(w: w, actions: actions) }
                }
            }
            .frame(maxWidth: .infinity)
            .background(CallInk.waBottom)
        }
    }
}

/// The call screen for any `CallUiState` (idle included — callers skip it):
/// WhatsApp's dark surface, the caller large and centred, the phase's own
/// words, and the controls in a rounded bar at the bottom — Decline left,
/// Answer (the largest) right, as in WhatsApp. After the call, the wrap-up.
struct CallCard: View {
    let c: CallUiState
    let actions: CallActions

    var body: some View {
        GeometryReader { g in
            let fontScale = teamFontScale
            // A short screen (a small phone, big text, landscape): a smaller avatar
            // and tighter spacing, so the whole card — above all its controls — fits.
            let short = g.size.height < 640 || g.size.height / fontScale < 560
            // A phone on its side: who on the left, the controls on the right.
            let sideBySide = g.size.width > g.size.height && g.size.height < 520
            let narrow = g.size.width / fontScale < 400
            let pad: CGFloat = narrow ? 16 : 24
            VStack(spacing: 0) {
                TopRow(c: c, actions: actions)
                if let w = c.waiting { WaitingBanner(w: w, actions: actions).padding(.bottom, 8) }
                if sideBySide {
                    HStack(spacing: 16) {
                        ScrollView { VStack(spacing: 0) { Who(c: c, short: true) }.frame(maxWidth: .infinity) }
                        ScrollView { VStack(spacing: 0) { Controls(c: c, actions: actions, compact: true) }.frame(maxWidth: .infinity).padding(.vertical, 8) }
                    }
                    .frame(maxHeight: .infinity)
                } else {
                    // Who / status scroll if they must; the controls below are always on screen.
                    ScrollView {
                        VStack(spacing: 0) {
                            Spacer().frame(height: short ? 8 : 32)
                            Who(c: c, short: short)
                            Spacer().frame(height: short ? 8 : 24)
                        }
                        .frame(maxWidth: .infinity, minHeight: g.size.height * 0.4)
                    }
                    .frame(maxHeight: .infinity)
                    VStack(spacing: 0) { Controls(c: c, actions: actions, compact: short) }
                        .frame(maxWidth: .infinity)
                        .padding(.bottom, short ? 12 : 28)
                }
            }
            .frame(maxWidth: sideBySide ? 900 : 520)
            .padding(.horizontal, pad)
            .frame(width: g.size.width, height: g.size.height)
        }
        .background(LinearGradient(colors: [CallInk.waTop, CallInk.waBottom], startPoint: .top, endPoint: .bottom).ignoresSafeArea())
        // The card owns the content area: swallow taps meant for the screen below.
        .contentShape(Rectangle())
        .onTapGesture {}
    }
}

/// Minimise (the call keeps running in the bar at the top of the app).
private struct TopRow: View {
    let c: CallUiState
    let actions: CallActions
    var body: some View {
        HStack {
            // On a call, Minimise sits in the control bar; before that, up here.
            if c.live && c.phase != .ringing && c.phase != .inCall {
                IconCell(glyph: CallIcons.minimise, label: "Minimise call", action: actions.minimise)
            }
            Spacer()
        }
        .frame(minHeight: 48)
    }
}

private struct IconCell: View {
    let glyph: WebGlyph
    let label: String
    var tint: Color = CallInk.waText
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            WebIcon(glyph: glyph, size: 24).foregroundColor(tint).frame(width: 48, height: 48).contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// Avatar (with the ring pulse while it rings), name, number, "WhatsApp voice call", the status line.
private struct Who: View {
    let c: CallUiState
    let short: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let who = c.who
        let avatar: CGFloat = short ? 88 : 120
        let ringing = c.phase == .ringing || c.phase == .placing || c.phase == .ringingOut
        let accent = CallAccent.of(c.channel)
        VStack(spacing: 0) {
            ZStack {
                if ringing && !reduceMotion {
                    PulseRing(maxScale: 1.6, startAlpha: 0.35, size: avatar, color: accent.pulse)
                    PulseRing(maxScale: 2, startAlpha: 0.2, size: avatar, color: accent.pulse)
                }
                // Messenger: the blue → purple ring around the same avatar (a gap in the call's dark between).
                if accent.ring { Circle().fill(Msgr.ring).frame(width: avatar, height: avatar) }
                let inner = accent.ring ? avatar - 10 : avatar
                ZStack {
                    Circle().fill(avatarColor(who))
                    if accent.ring { Circle().stroke(CallInk.waTop, lineWidth: 2) }
                    // A Messenger caller with no name yet: the handset, never initials made of "Messenger caller".
                    if c.messenger && (c.name ?? "").trimmingCharacters(in: .whitespaces).isEmpty {
                        WebIcon(glyph: CallIcons.phone, size: short ? 32 : 40).foregroundColor(.white)
                    } else {
                        // The initials are a picture inside a fixed circle: they don't grow with the font scale.
                        let i = initialsOf(who)
                        Text(i.isEmpty ? "?" : i).font(NeemaFont.fixed(short ? 32 : 42, .semibold)).foregroundColor(.white).lineLimit(1)
                    }
                }
                .frame(width: inner, height: inner)
            }
            .frame(width: avatar, height: avatar)
            Spacer().frame(height: short ? 12 : 20)
            Text(who).font(NeemaFont.manrope(26, .semibold)).foregroundColor(CallInk.waText).lineLimit(2).multilineTextAlignment(.center)
            // A Messenger PSID is no number: never shown.
            if !(c.name ?? "").trimmingCharacters(in: .whitespaces).isEmpty, let n = c.number {
                Text("+\(n)").font(NeemaFont.manrope(14)).monospacedDigit().foregroundColor(CallInk.waSub).lineLimit(1).padding(.top, 4)
            }
            HStack(spacing: 6) {
                if c.messenger { ChannelGlyph(channel: CallWords.MESSENGER, size: 15) }
                else { WebIcon(glyph: CallIcons.phone, size: 14).foregroundColor(CallInk.whatsApp) }
                Text("\(c.app) voice call").font(NeemaFont.manrope(14)).foregroundColor(CallInk.waSub).lineLimit(1)
            }
            .padding(.top, 6)
            Spacer().frame(height: short ? 10 : 16)
            StatusLine(c: c)
        }
    }
}

/// The phase's own words, announced when they change.
private struct StatusLine: View {
    let c: CallUiState
    var body: some View {
        let text = c.statusText()
        VStack(spacing: 0) {
            if c.reconnecting && c.live {
                HStack(spacing: 8) {
                    WebIcon(glyph: CallIcons.noSignal, size: 16).foregroundColor(CallInk.waAmber)
                    Text(text).font(NeemaFont.manrope(15, .medium)).foregroundColor(CallInk.waAmber)
                }
                .padding(.horizontal, 14).padding(.vertical, 6)
                .background(Capsule().fill(CallInk.waAmber.opacity(0.14)))
            } else if c.phase == .inCall {
                Text(text).font(NeemaFont.manrope(18)).monospacedDigit().foregroundColor(CallInk.waText)
                    .accessibilityLabel("On call, \(spokenLength(c.seconds))")
                // Only while a recording really runs: this phone's, or WhatsApp's own (the customer heard it announced).
                if c.recording || c.metaTranscription {
                    HStack(spacing: 6) {
                        Circle().fill(CallInk.waRed).frame(width: 8, height: 8)
                        Text(c.recording ? "Recording" : "Recorded by WhatsApp").font(NeemaFont.manrope(13)).foregroundColor(CallInk.waText)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(Capsule().fill(CallInk.waRed.opacity(0.16)))
                    .padding(.top, 8)
                }
            } else if c.phase == .connecting {
                HStack(spacing: 8) {
                    ProgressView().progressViewStyle(.circular).tint(CallAccent.of(c.channel).answer).scaleEffect(0.7)
                    Text(text).font(NeemaFont.manrope(15)).foregroundColor(CallInk.waSub)
                }
            } else if c.phase == .ended {
                // Every outcome is an icon AND words (never colour alone, §5).
                let owed: Bool = {
                    switch c.outcome {
                    case .missed, .noAnswer, .rejected, .connectionLost, .failed, .micBlocked, .permissionNeeded: return true
                    default: return false
                    }
                }()
                let tint = owed ? CallInk.owed : CallInk.waText
                HStack(spacing: 8) {
                    if let g = outcomeGlyph(c.outcome) { WebIcon(glyph: g, size: 18).foregroundColor(tint) }
                    else { HandsetIcon(down: true, size: 18).foregroundColor(tint) }
                    Text(text).font(NeemaFont.manrope(16, .medium)).foregroundColor(tint).multilineTextAlignment(.center)
                }
            } else {
                Text(text).font(NeemaFont.manrope(15)).foregroundColor(CallInk.waSub).multilineTextAlignment(.center)
            }
            // Before the call goes through: they left our last calls unanswered (a caution, never a block).
            if let caution = c.callCaution() {
                HStack(alignment: .top, spacing: 8) {
                    WebIcon(glyph: CallIcons.alert, size: 16).foregroundColor(CallInk.waAmber).padding(.top, 1)
                    Text(caution).font(NeemaFont.manrope(13)).lineSpacing(3).foregroundColor(CallInk.waText)
                }
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(RoundedRectangle(cornerRadius: 12).fill(CallInk.waAmber.opacity(0.14)))
                .frame(maxWidth: 360)
                .padding(.top, 12)
            }
            if let note = c.outcomeNote() {
                Text(note).font(NeemaFont.manrope(13)).lineSpacing(3).foregroundColor(CallInk.waSub).multilineTextAlignment(.center)
                    .frame(maxWidth: 340).padding(.top, 8)
            }
            if c.phase == .ended, let r = c.recordingNote {
                HStack(spacing: 6) {
                    Circle().fill(CallInk.waSub).frame(width: 8, height: 8)
                    Text(r).font(NeemaFont.manrope(13)).foregroundColor(CallInk.waSub).multilineTextAlignment(.center)
                }
                .padding(.top, 8)
            }
            if let e = c.error {
                Text(e).font(NeemaFont.manrope(14)).foregroundColor(Palette.red300).multilineTextAlignment(.center).padding(.top, 10)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// The controls for the phase (the §3 table's last column).
private struct Controls: View {
    let c: CallUiState
    let actions: CallActions
    let compact: Bool

    var body: some View {
        switch c.phase {
        case .ringing:
            // Disabled (dimmed) while a callback is being saved: no second request.
            let on = !c.busy
            VStack(spacing: compact ? 4 : 12) {
                HStack(alignment: .bottom) {
                    Spacer()
                    RoundButton(label: "Decline", description: "Decline call", color: CallInk.waRed, size: 64, enabled: on, action: actions.decline) { HandsetIcon(down: true, size: 30).foregroundColor(.white) }
                    Spacer()
                    RoundButton(label: "Answer", description: "Answer call", color: CallAccent.of(c.channel).answer, size: 76, enabled: on, action: actions.answer) { HandsetIcon(size: 30).foregroundColor(.white) }
                    Spacer()
                }
                .frame(maxWidth: 360)
                TextAction(text: c.busy ? "Saving…" : "Call back later", glyph: CallIcons.callback, enabled: on, action: actions.callback)
            }
        case .placing, .ringingOut, .connecting, .inCall:
            HStack(alignment: .top, spacing: 0) {
                MuteButton(c: c, actions: actions)
                if c.phase == .connecting || c.phase == .inCall { AudioButton(c: c, actions: actions) }
                if c.phase == .inCall && c.chatKey != nil {
                    RoundButton(label: "Chat", description: "Open chat", color: CallInk.waControl, action: actions.openChat) { WebIcon(glyph: CallIcons.chat, size: 24).foregroundColor(.white) }
                }
                if c.phase == .inCall {
                    RoundButton(label: "Minimise", description: "Minimise call", color: CallInk.waControl, action: actions.minimise) { WebIcon(glyph: CallIcons.minimise, size: 24).foregroundColor(.white) }
                }
                RoundButton(label: "End", description: "End call", color: CallInk.waRed, action: actions.hangup) { HandsetIcon(down: true, size: 24).foregroundColor(.white) }
            }
            .padding(.horizontal, 4).padding(.vertical, 12)
            .frame(maxWidth: 460)
            .background(RoundedRectangle(cornerRadius: 32).fill(CallInk.waBar))
        case .ended:
            WrapUp(c: c, actions: actions)
        case .idle:
            EmptyView()
        }
    }
}

private struct MuteButton: View {
    let c: CallUiState
    let actions: CallActions
    var body: some View {
        RoundButton(label: c.muted ? "Unmute" : "Mute", description: c.muted ? "Unmute" : "Mute", color: c.muted ? CallInk.waText : CallInk.waControl,
                    state: c.muted ? "Microphone off" : nil, action: actions.toggleMute) {
            WebIcon(glyph: c.muted ? CallIcons.micOff : CallIcons.mic, size: 24).foregroundColor(c.muted ? CallInk.waBottom : CallInk.waText)
        }
    }
}

/// Earpiece ↔ speaker when that is all there is; with a headset or Bluetooth,
/// the current route and a list to choose from (as a phone's call screen).
private struct AudioButton: View {
    let c: CallUiState
    let actions: CallActions
    var body: some View {
        if !c.routeChoice {
            let on = c.speaker
            RoundButton(label: "Speaker", description: on ? "Speaker on" : "Speaker", color: on ? CallInk.waText : CallInk.waControl,
                        enabled: c.routes.count > 1, state: on ? "On" : "Off", action: actions.toggleSpeaker) {
                WebIcon(glyph: CallIcons.speaker, size: 24).foregroundColor(on ? CallInk.waBottom : CallInk.waText)
            }
        } else {
            Menu {
                ForEach(c.routes, id: \.self) { r in
                    Button { actions.selectRoute(r) } label: {
                        if r == c.route { Label(r.label, systemImage: "checkmark") } else { Text(r.label) }
                    }
                }
            } label: {
                RoundButtonLook(label: c.route.label, color: CallInk.waText, size: 56, enabled: true) {
                    WebIcon(glyph: routeGlyph(c.route.kind), size: 24).foregroundColor(CallInk.waBottom)
                }
            }
            .frame(maxWidth: .infinity)
            .accessibilityLabel("Audio: \(c.route.label) — choose where the call plays")
        }
    }
}

/// The wrap-up's actions: the one the agent most likely wants, filled; the rest outlined; Done last.
private struct WrapUp: View {
    let c: CallUiState
    let actions: CallActions
    var body: some View {
        let list = c.wrapActions()
        let fill = CallAccent.of(c.channel).button
        VStack(spacing: 8) {
            ForEach(Array(list.enumerated()), id: \.offset) { i, a in
                let run = actions.run(a)
                let label = a == .sendCallRequest && c.busy ? "Sending…" : a.label
                let closer = a == .done || a == .cancel
                // Meta's request limit is used up: the button stays, dimmed; the line above says when it can go.
                let blocked = a == .sendCallRequest && c.sendRequestBlocked() != nil
                if closer {
                    PillButton(text: label, filled: false, outlined: false, action: run)
                } else if i == 0 {
                    PillButton(text: label, filled: true, enabled: !c.busy && !blocked, fill: fill, action: run)
                } else {
                    PillButton(text: label, filled: false, enabled: !c.busy && !blocked, action: run)
                }
            }
        }
        .frame(maxWidth: 360)
    }
}

private struct PillButton: View {
    let text: String
    let filled: Bool
    var outlined = true
    var enabled = true
    var fill: Color = CallInk.waTealText
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(text).font(NeemaFont.manrope(15, filled ? .semibold : .medium)).foregroundColor(filled ? .white : CallInk.waText)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 16).padding(.vertical, 12)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(Capsule().fill(filled ? fill : Color.clear))
                .overlay(Capsule().stroke(!filled && outlined ? CallInk.waSub.opacity(0.5) : Color.clear, lineWidth: 1))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.5)
    }
}

private struct TextAction: View {
    let text: String
    let glyph: WebGlyph
    var enabled = true
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                WebIcon(glyph: glyph, size: 18).foregroundColor(CallInk.waText)
                Text(text).font(NeemaFont.manrope(15, .medium)).foregroundColor(CallInk.waText)
            }
            .padding(.horizontal, 16).padding(.vertical, 12).frame(minHeight: 48).contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.5)
    }
}

/// The expanding green rings behind a ringing avatar (the only motion besides the connecting spinner).
private struct PulseRing: View {
    let maxScale: CGFloat
    let startAlpha: Double
    let size: CGFloat
    let color: Color
    @State private var p: CGFloat = 0
    var body: some View {
        Circle().fill(color)
            .frame(width: size, height: size)
            .scaleEffect(1 + (maxScale - 1) * p)
            .opacity(startAlpha * (1 - p))
            .onAppear {
                withAnimation(.easeOut(duration: 1.7).repeatForever(autoreverses: false)) { p = 1 }
            }
    }
}

/// A round call control with its label under it: 56 pt at least (64 for
/// Decline, 76 for Answer), the whole column one touch target.
private struct RoundButton<Icon: View>: View {
    let label: String
    let description: String
    let color: Color
    var size: CGFloat = 56
    var enabled = true
    var state: String? = nil
    let action: () -> Void
    @ViewBuilder let icon: () -> Icon
    var body: some View {
        Button(action: action) {
            RoundButtonLook(label: label, color: color, size: size, enabled: enabled, icon: icon)
        }
        .buttonStyle(PressScaleStyle())
        .disabled(!enabled)
        .frame(maxWidth: .infinity)
        .accessibilityLabel(description)
        .accessibilityValue(state ?? "")
    }
}

private struct RoundButtonLook<Icon: View>: View {
    let label: String
    let color: Color
    let size: CGFloat
    let enabled: Bool
    @ViewBuilder let icon: () -> Icon
    var body: some View {
        VStack(spacing: 8) {
            ZStack { Circle().fill(color); icon() }.frame(width: size, height: size)
            // The label grows with the font scale only so far: five controls share a row, and a word must never break in half.
            Text(label).font(NeemaFont.capped(12, maxScale: 1.15)).foregroundColor(CallInk.waText).lineLimit(1).fixedSize()
        }
        .opacity(enabled ? 1 : 0.45)
        .contentShape(Rectangle())
    }
}

private struct PressScaleStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.scaleEffect(configuration.isPressed ? 0.95 : 1)
    }
}

/// The minimised call (§6): a slim bar at the top of the content — live dot
/// (amber, with its icon, while reconnecting), who, the status or timer, Mute
/// and End. A tap anywhere else brings the call screen back.
struct MinimisedCallBar: View {
    let c: CallUiState
    let actions: CallActions

    var body: some View {
        let ended = c.phase == .ended
        let inCall = c.phase == .inCall
        let timer = inCall && !c.reconnecting
        HStack(spacing: 0) {
            Button(action: actions.expand) {
                HStack(spacing: 12) {
                    if c.reconnecting { WebIcon(glyph: CallIcons.noSignal, size: 14).foregroundColor(CallInk.waAmber) }
                    else { Circle().fill(ended ? CallInk.waSub : CallAccent.of(c.channel).dot).frame(width: 10, height: 10) }
                    VStack(alignment: .leading, spacing: 0) {
                        Text(c.who).font(NeemaFont.manrope(14, .semibold)).foregroundColor(CallInk.waText).lineLimit(1)
                        HStack(spacing: 8) {
                            // The clock never breaks across lines; words may take two.
                            Text(c.statusText()).font(NeemaFont.manrope(13)).monospacedDigit()
                                .foregroundColor(c.reconnecting ? CallInk.waAmber : CallInk.waSub).lineLimit(timer ? 1 : 2)
                            if timer && c.recording {
                                HStack(spacing: 4) {
                                    Circle().fill(CallInk.rec).frame(width: 8, height: 8)
                                    // At large text sizes the dot alone: the timer and the controls keep their room.
                                    if teamFontScale <= 1.3 { Text("Rec").font(NeemaFont.manrope(13)).foregroundColor(CallInk.rec).lineLimit(1).fixedSize() }
                                }
                                .accessibilityLabel("Recording")
                            }
                        }
                    }
                    .padding(.vertical, 8)
                    Spacer(minLength: 0)
                }
                .padding(.leading, 16)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Show the call")
            if ended {
                // A wrap-up that arrived while minimised: its main action, and Done.
                if let primary = c.wrapActions().first, primary != .done && primary != .cancel {
                    Button(action: actions.run(primary)) {
                        Text(primary.label).font(NeemaFont.manrope(13, .semibold)).foregroundColor(.white).lineLimit(1)
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .background(Capsule().fill(CallAccent.of(c.channel).button))
                            .frame(minHeight: 48)
                    }
                    .buttonStyle(.plain)
                    .disabled(c.busy)
                }
                Button(action: actions.dismiss) {
                    Text("Done").font(NeemaFont.manrope(13, .medium)).foregroundColor(CallInk.waText).padding(.horizontal, 12).frame(minHeight: 48)
                }
                .buttonStyle(.plain)
            } else {
                // Chat: the customer's conversation, the call stays up here (the web's bar has it too).
                if inCall && c.chatKey != nil { IconCell(glyph: CallIcons.chat, label: "Open chat with \(c.who) — the call keeps going", action: actions.openChat) }
                IconCell(glyph: c.muted ? CallIcons.micOff : CallIcons.mic, label: c.muted ? "Unmute" : "Mute", action: actions.toggleMute)
                Button(action: actions.hangup) {
                    ZStack {
                        Circle().fill(CallInk.waRed).frame(width: 38, height: 38)
                        HandsetIcon(down: true, size: 20).foregroundColor(.white)
                    }
                    .frame(width: 48, height: 48).contentShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("End call")
            }
        }
        .padding(.trailing, 4)
        .frame(minHeight: 56)
        .background(CallInk.waBar)
    }
}

/// A second caller while this phone is on a call: a banner, never a take-over.
/// The API has no hold — taking them means ending this call ("End & answer").
struct WaitingBanner: View {
    let w: WaitingCall
    let actions: CallActions
    var body: some View {
        let accent = CallAccent.of(w.channel)
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if channelOf(w.channel) == CallWords.MESSENGER { ChannelGlyph(channel: CallWords.MESSENGER, size: 16) }
                else { WebIcon(glyph: CallIcons.phone, size: 16).foregroundColor(CallInk.whatsApp) }
                Text("\(w.who) is also calling").font(NeemaFont.manrope(14, .medium)).foregroundColor(CallInk.waText).lineLimit(2)
                    .accessibilityLabel("\(w.who) is also calling on \(channelLabel(w.channel))")
            }
            // As the web's banner: three filled pills — Decline red, Call back later quiet, End & answer green.
            FlowLayout(spacing: 8, lineSpacing: 8) {
                SmallAction(text: "Decline", fill: CallInk.waRed, ink: .white, description: "Decline \(w.who)'s call", action: actions.declineWaiting)
                SmallAction(text: "Call back later", fill: CallInk.waControl, ink: CallInk.waText, description: nil, action: actions.callbackWaiting)
                SmallAction(text: "End & answer", fill: accent.button, ink: .white, description: nil, action: actions.endAndAnswer)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(CallInk.waBar))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(accent.pulse.opacity(0.35), lineWidth: 1))
    }
}

private struct SmallAction: View {
    let text: String
    let fill: Color
    let ink: Color
    let description: String?
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(text).font(NeemaFont.manrope(14, .semibold)).foregroundColor(ink).lineLimit(1)
                .padding(.horizontal, 16).frame(minHeight: 48)
                .background(Capsule().fill(fill))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(description ?? text)
    }
}

/// "{First} allowed calls — Call now": a customer this phone asked has tapped Allow.
struct PermissionGrantBanner: View {
    let g: PermissionGrant
    let onCall: () -> Void
    let onDismiss: () -> Void
    var body: some View {
        let messenger = channelOf(g.channel) == CallWords.MESSENGER
        // Never a PSID on screen.
        let first = firstNameOf(g.name) ?? (messenger ? "They" : "+\(g.waId)")
        HStack(spacing: 10) {
            if messenger { ChannelGlyph(channel: CallWords.MESSENGER, size: 16) }
            else { WebIcon(glyph: CallIcons.phone, size: 16).foregroundColor(CallInk.whatsApp) }
            Text(messenger ? "\(first) allowed Messenger calls" : "\(first) allowed calls").font(NeemaFont.manrope(14, .medium)).foregroundColor(CallInk.waText).lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(action: onCall) {
                HStack(spacing: 6) {
                    WebIcon(glyph: CallIcons.phone, size: 15).foregroundColor(.white)
                    Text("Call now").font(NeemaFont.manrope(14, .semibold)).foregroundColor(.white)
                }
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(Capsule().fill(CallAccent.of(g.channel).button))
                .frame(minHeight: 48)
            }
            .buttonStyle(.plain)
            IconCell(glyph: CallIcons.close, label: "Dismiss", action: onDismiss)
        }
        .padding(.leading, 16).padding(.trailing, 4)
        .frame(minHeight: 56)
        .background(CallInk.waTeal.opacity(0.18))
    }
}
