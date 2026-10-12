import SwiftUI
import AVFoundation
import UserNotifications
import NeemaCore

/// Calls — the WhatsApp call history (components/views/CallsView.tsx,
/// CALLING_UX.md §7; Android `CallsScreen`): All · Follow-ups, rows grouped
/// Today / Yesterday / date, each with its direction and outcome in words and
/// colour, length, who took it, the time, the recording / summary indicator
/// and a one-tap call back. A row opens its details: the timeline, the
/// recording, transcript and insights, Call back · Open chat · Mark follow-up
/// done, and the customer's full panel. Phone: the details replace the log;
/// tablet: side by side.
struct CallsScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let model = app.callsScreen {
            CallsScreenBody(model: model)
        } else {
            LoadingView()
        }
    }
}

private struct CallsScreenBody: View {
    @ObservedObject var model: CallsScreenModel
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @Environment(\.scenePhase) private var scenePhase
    @SceneStorage("calls.ui") private var savedUi = ""
    @SceneStorage("calls.autoPicked") private var autoPicked = ""
    @State private var readiness = CallReadiness.ready
    @State private var scrolledTo: String?

    private var vm: CallsViewModel { model.vm }

    var body: some View {
        GeometryReader { g in
            let width = g.size.width
            let wide = width >= 840
            let sidePad: CGFloat = width >= 640 ? 24 : 16
            // Little room for text (a small phone, big text): each row puts its time
            // on the name line, and the readiness prompt its button under the words.
            let compact = width / teamFontScale < 400
            let list = model.list
            let followUps = (list ?? []).filter { $0.followUpOpen }.count
            // Messenger shows up (header words, the app filter) once it can call or any call was on it.
            let anyMessenger = (model.channels.map { $0.messenger.inbound || $0.messenger.outbound } ?? false)
                || (list ?? []).contains { channelOf($0.channel) == CallWords.MESSENGER }
            let appFilter = anyMessenger ? model.channelFilter : "all"
            let shown: [Call]? = list?.filter { (!model.followUpsOnly || $0.followUpOpen) && (appFilter == "all" || channelOf($0.channel) == appFilter) }
            // Tablet: the details pane is never an empty half — the newest call in
            // view opens in it, and a filter that hides the open call moves the pane
            // to the first one still shown. Decided here, so the first frame already has it.
            let pick = detailsPick(wide: wide, shownIds: (shown ?? []).map { $0.id }, selected: model.selected?.id, autoPicked: autoPicked.isEmpty ? nil : autoPicked)
            let view: Call? = pick.select.flatMap { id in id == model.selected?.id ? model.selected : shown?.first { $0.id == id } }
            // A big tablet on its side: both panes grow with the room (log up to 640, details up to 600).
            let roomy = width >= 1100

            HStack(alignment: .top, spacing: 24) {
                if wide || view == nil {
                    CallLog(
                        model: model, shown: shown, total: list?.count ?? 0, followUps: followUps, selectedId: view?.id,
                        anyMessenger: anyMessenger, channelFilter: appFilter, readiness: readiness, compact: compact,
                        onReadiness: { Task { @MainActor in await readiness.fix(); refreshReadiness() } }
                    )
                    .frame(maxWidth: roomy ? 640 : 560)
                    .frame(maxWidth: .infinity)
                }
                if let sel = view {
                    CallDetails(model: model, sel: sel, calls: list ?? [])
                        .frame(maxWidth: roomy ? 600 : (wide ? 420 : .infinity))
                        .frame(minWidth: roomy ? 420 : nil)
                }
            }
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.horizontal, sidePad)
            .frame(width: width, height: g.size.height)
            .onChange(of: pick) { p in
                if p.select != model.selected?.id { vm.select(p.select.flatMap { id in shown?.first { $0.id == id } }) }
                autoPicked = p.autoPicked ?? ""
            }
        }
        .background(c.surface)
        .onAppear {
            vm.restoreIfFresh(savedUi)
            vm.life.shown.update(true)
            refreshReadiness()
            consumeFocus()
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: model.followUpsOnly) { _ in savedUi = vm.saveUi() }
        .onChange(of: model.channelFilter) { _ in savedUi = vm.saveUi() }
        .onChange(of: model.selected) { _ in savedUi = vm.saveUi() }
        .onChange(of: app.callsFocusKey) { _ in consumeFocus() }
        .onChange(of: model.list == nil) { _ in consumeFocus() }
        // Re-check on return from the system settings page.
        .onChange(of: scenePhase) { p in if p == .active { refreshReadiness() } }
    }

    private func consumeFocus() {
        if let key = app.callsFocusKey, model.list != nil { vm.consumeFocus(key) }
    }

    private func refreshReadiness() {
        Task { @MainActor in readiness = await CallReadiness.of() }
    }
}

/// Why a call might not ring this phone like the web's take-over card, and the
/// one tap that fixes it. On iOS the app can only be told of a call while it
/// runs (the live socket; see PLAN — pushes land with the backend's PushKit
/// support), so what matters is that notifications are allowed: a ringing
/// call then alerts from the background with CallKit.
struct CallReadiness: Equatable {
    enum Missing: Equatable { case notifications, microphone }
    var missing: Missing?
    var ready: Bool { missing == nil }
    static let ready = CallReadiness(missing: nil)

    static func of() async -> CallReadiness {
        let s = await UNUserNotificationCenter.current().notificationSettings()
        let notifs = s.authorizationStatus == .authorized || s.authorizationStatus == .provisional || s.authorizationStatus == .ephemeral
        let mic = AVAudioSession.sharedInstance().recordPermission != .denied
        return CallReadiness(missing: !notifs ? .notifications : (!mic ? .microphone : nil))
    }

    var title: String {
        switch missing {
        case .microphone: return "Calls can't use the microphone"
        default: return "Calls can't ring in the background"
        }
    }
    var text: String {
        switch missing {
        case .microphone: return "Allow the microphone so you can be heard on a WhatsApp call."
        default: return "Turn on notifications so a WhatsApp call rings this phone when Neema isn't open."
        }
    }
    var button: String { missing == .microphone ? "Allow" : "Turn on" }

    /// Asks once if never asked; otherwise the Settings page is the only way.
    @MainActor func fix() async {
        let center = UNUserNotificationCenter.current()
        let s = await center.notificationSettings()
        if missing == .notifications && s.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
            return
        }
        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url, options: [:], completionHandler: nil) }
    }
}

// ── The log ───────────────────────────────────────────────────────────────────

private struct CallLog: View {
    @ObservedObject var model: CallsScreenModel
    let shown: [Call]?
    let total: Int
    let followUps: Int
    let selectedId: String?
    let anyMessenger: Bool
    let channelFilter: String
    let readiness: CallReadiness
    let compact: Bool
    let onReadiness: () -> Void
    @EnvironmentObject private var app: AppModel

    private var vm: CallsViewModel { model.vm }

    var body: some View {
        let items = logItems(shown ?? [])
        let inset: CGFloat = compact ? 16 : 24
        ScrollView {
            // One card, as the web draws it (gradient, outline, shadow), spanning its first row to its last.
            LazyVStack(alignment: .leading, spacing: 0) {
                header(inset: inset)
                if let r = model.restriction { RestrictionBanner(r: r, inset: inset) { model.calls.dismissRestriction() } }
                if !readiness.ready { ReadinessBanner(r: readiness, compact: compact, inset: inset, onFix: onReadiness) }
                // The log couldn't be refreshed: what we had stays, with the reason and a way to try again.
                if let e = model.loadError, let s = shown, !s.isEmpty {
                    LoadErrorBanner(message: e, refreshing: model.refreshing, inset: inset) { vm.refresh() }
                }
                if shown == nil {
                    ForEach(0..<4, id: \.self) { _ in SkeletonRow(compact: compact) }
                } else if shown!.isEmpty, let e = model.loadError {
                    VStack(spacing: 6) {
                        Text("Couldn't load calls").font(NeemaFont.manrope(15, .medium)).foregroundColor(CallInk.soft)
                        Text(e).font(NeemaFont.manrope(13)).foregroundColor(CallInk.muted).multilineTextAlignment(.center)
                        RetryButton(busy: model.refreshing) { vm.refresh() }.padding(.top, 10)
                    }
                    .frame(maxWidth: .infinity).padding(.horizontal, 24).padding(.vertical, 48)
                } else if shown!.isEmpty {
                    VStack(spacing: 6) {
                        Text(model.followUpsOnly ? "No follow-ups — every caller has been called back"
                             : "No calls yet — incoming \(anyMessenger ? "WhatsApp and Messenger" : "WhatsApp") calls ring here")
                            .font(NeemaFont.manrope(15, .medium)).foregroundColor(CallInk.soft).multilineTextAlignment(.center)
                        Text(model.followUpsOnly ? "Every missed call has been returned or marked done."
                             : "Keep Neema signed in — a call rings this phone while the app is open.")
                            .font(NeemaFont.manrope(13)).foregroundColor(CallInk.muted).multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity).padding(.horizontal, 24).padding(.vertical, 56)
                } else {
                    ForEach(items) { item in
                        switch item {
                        case .day(let label, _):
                            Text(label.uppercased()).font(NeemaFont.manrope(11, .semibold)).tracking(0.8).foregroundColor(CallInk.dim)
                                .padding(.horizontal, inset).padding(.top, 14).padding(.bottom, 6)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .accessibilityAddTraits(.isHeader)
                        case .row(let call, _):
                            VStack(spacing: 0) {
                                Rectangle().fill(Color.white.opacity(0.05)).frame(height: 1)
                                CallRow(
                                    c: call, selected: selectedId == call.id, open: model.transcript?.callId == call.callId,
                                    canCallBack: vm.canCallBack(call), showChannel: anyMessenger, compact: compact,
                                    onSelect: { vm.select(call) }, onToggleTranscript: { vm.toggleTranscript(call.callId) },
                                    onCallBack: { vm.callBack(call) }
                                )
                                if let t = model.transcript, t.callId == call.callId, selectedId != call.id {
                                    TranscriptPanel(t: t, vm: vm, compact: compact)
                                }
                            }
                        }
                    }
                }
            }
            .padding(.vertical, 24)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    // radial-gradient(120% 60% at 50% 0%, #123626 0%, #0b1410 60%)
                    .fill(EllipticalGradient(stops: [.init(color: CallInk.glow, location: 0), .init(color: CallInk.ink, location: 0.6), .init(color: CallInk.ink, location: 1)],
                                             center: .top, startRadiusFraction: 0, endRadiusFraction: 1.2))
                    // border: 1px solid rgba(37,211,102,0.14); box-shadow: 0 20px 50px rgba(0,0,0,0.25)
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(CallInk.whatsApp.opacity(0.14), lineWidth: 1))
                    .shadow(color: .black.opacity(0.25), radius: 25, x: 0, y: 20)
            )
            .padding(.vertical, 24)
        }
        .refreshable { await pullToRefresh() }
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !model.refreshing { break }
        }
    }

    private func header(inset: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Calls").font(NeemaFont.manrope(22, .medium)).foregroundColor(.white).accessibilityAddTraits(.isHeader)
            Text("\(anyMessenger ? "WhatsApp and Messenger voice calls" : "WhatsApp voice calls") · \(total) total")
                .font(NeemaFont.manrope(13)).foregroundColor(CallInk.muted).padding(.top, 2)
            HStack(spacing: 8) {
                FilterChip(text: "All", selected: !model.followUpsOnly) { model.setFollowUpsOnly(false) }
                FilterChip(text: followUps > 0 ? "Follow-ups (\(followUps))" : "Follow-ups", selected: model.followUpsOnly, alert: followUps > 0) { model.setFollowUpsOnly(true) }
            }
            .padding(.top, 12)
            // Every call, or only WhatsApp / only Messenger (CallsView.tsx's app filter).
            if anyMessenger {
                HStack(spacing: 6) {
                    ForEach([("all", "All apps"), (CallWords.WHATSAPP, "WhatsApp"), (CallWords.MESSENGER, "Messenger")], id: \.0) { pair in
                        AppChip(id: pair.0, label: pair.1, selected: channelFilter == pair.0) { model.setChannelFilter(pair.0) }
                    }
                }
                .padding(.top, 8)
            }
        }
        .padding(.horizontal, inset).padding(.top, 24).padding(.bottom, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct FilterChip: View {
    let text: String
    let selected: Bool
    var alert = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(text).font(NeemaFont.manrope(13, .medium)).monospacedDigit()
                .foregroundColor(selected ? CallInk.ink : (alert ? CallInk.missedText : CallInk.text))
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(Capsule().fill(selected ? CallInk.green : Color.white.opacity(0.06)))
                .overlay(Capsule().stroke(selected ? CallInk.green : Color.white.opacity(0.12), lineWidth: 1))
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Show \(text)")
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

/// One app filter chip: "All apps" / WhatsApp / Messenger, with the app's glyph.
private struct AppChip: View {
    let id: String
    let label: String
    let selected: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                if id != "all" { ChannelGlyph(channel: id, size: 13, waTint: Color(hex: 0x7EE2A8)) }
                Text(label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(selected ? CallInk.text : CallInk.sage).lineLimit(1)
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(Capsule().fill(selected ? Color.white.opacity(0.12) : Color.clear))
            .overlay(Capsule().stroke(Color.white.opacity(selected ? 0.3 : 0.08), lineWidth: 1))
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Show \(label) calls")
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

/// A placeholder row while the log loads (no spinner: the page keeps its shape).
private struct SkeletonRow: View {
    let compact: Bool
    var body: some View {
        HStack(spacing: 12) {
            Circle().fill(Color.white.opacity(0.07)).frame(width: 40, height: 40)
            VStack(alignment: .leading, spacing: 8) {
                RoundedRectangle(cornerRadius: 6).fill(Color.white.opacity(0.08)).frame(height: 12).frame(maxWidth: 160)
                RoundedRectangle(cornerRadius: 5).fill(Color.white.opacity(0.05)).frame(height: 10).frame(maxWidth: 110)
            }
            Spacer()
        }
        .padding(.leading, compact ? 16 : 24).padding(.trailing, 24).padding(.vertical, 12)
        .accessibilityLabel("Loading calls")
    }
}

private struct CallRow: View {
    let c: Call
    let selected: Bool
    let open: Bool
    let canCallBack: Bool
    let showChannel: Bool
    let compact: Bool
    let onSelect: () -> Void
    let onToggleTranscript: () -> Void
    let onCallBack: () -> Void

    var body: some View {
        let w = callRowWords(c)
        let messenger = channelOf(c.channel) == CallWords.MESSENGER
        let who = rowWho(c)
        let initials = initialsOf(who)
        let hasNote = !(c.summary ?? "").isEmpty
        let time = Fmt.time(c.startedAt)
        HStack(spacing: compact ? 8 : 12) {
            Button(action: onSelect) {
                HStack(spacing: compact ? 8 : 12) {
                    ZStack {
                        Circle().fill(avatarColor(who))
                        // Initials are a picture inside a fixed circle: they don't grow with the font scale.
                        Text(initials.isEmpty ? "?" : initials).font(NeemaFont.fixed(13, .medium)).foregroundColor(.white).lineLimit(1)
                    }
                    .frame(width: 40, height: 40)
                    VStack(alignment: .leading, spacing: 1) {
                        HStack(spacing: 6) {
                            Text(who).font(NeemaFont.manrope(14, .medium)).foregroundColor(CallInk.text).lineLimit(1)
                            // Which app the call was on: a mixed history is never ambiguous.
                            if showChannel { CallChannelBadge(channel: c.channel, onDark: true, fontSize: 10) }
                        }
                        HStack(spacing: 6) {
                            WebIcon(glyph: CallIcons.of(w.icon), size: 13).foregroundColor(callToneColor(w.tone))
                            // One run of text so a tight row trims the end ("· Mo…") rather than dropping a whole part.
                            statusLine(w).font(NeemaFont.manrope(12)).lineLimit(1)
                            if c.hasVoicemail { VoicemailBadge() }
                        }
                        // Little room: the time drops under the outcome, and the name keeps the line.
                        if compact { Text(time).font(NeemaFont.manrope(11)).monospacedDigit().foregroundColor(CallInk.dim).lineLimit(1) }
                    }
                    .padding(.vertical, 6)
                    Spacer(minLength: 0)
                    if !compact { Text(time).font(NeemaFont.manrope(11)).monospacedDigit().foregroundColor(CallInk.dim).lineLimit(1) }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(who), \(w.label), \(time). Call details")
            // The two 48 pt touch cells sit flush: their 34 pt circles still read 14 pt apart.
            HStack(spacing: 0) {
                if c.hasRecording || hasNote {
                    RoundIcon(
                        glyph: CallIcons.transcript, iconSize: 15,
                        label: hasNote ? "Call summary & transcript" : "Call recording — transcribe & summarise",
                        bg: open ? CallInk.whatsApp.opacity(0.22) : (hasNote ? CallInk.whatsApp.opacity(0.12) : Color.white.opacity(0.06)),
                        tint: open || hasNote ? CallInk.green : CallInk.sage, border: Color.white.opacity(0.1), action: onToggleTranscript
                    )
                }
                if canCallBack {
                    if messenger {
                        RoundIcon(glyph: CallIcons.phone, iconSize: 15, label: "Call \(who) back on Messenger",
                                  bg: Msgr.badgeBg, tint: Msgr.badgeFg, border: Msgr.blue.opacity(0.4), action: onCallBack)
                    } else {
                        // The web's row button: WhatsApp green glyph on a soft green disc.
                        RoundIcon(glyph: CallIcons.phone, iconSize: 15, label: "Call \(who) back on WhatsApp",
                                  bg: CallInk.whatsApp.opacity(0.16), tint: CallInk.green, border: CallInk.whatsApp.opacity(0.3), action: onCallBack)
                    }
                }
            }
        }
        .padding(.leading, compact ? 16 : 24).padding(.trailing, compact ? 8 : 20).padding(.vertical, 8)
        .background(selected ? CallInk.whatsApp.opacity(0.08) : Color.clear)
    }

    /// "Missed · 3:04 · Moses · Follow up": the outcome in its colour, then length, agent, follow-up muted.
    private func statusLine(_ w: CallRowWords) -> Text {
        var t = Text(w.label).foregroundColor(callToneColor(w.tone))
        let d = callDuration(c.duration)
        if !d.isEmpty { t = t + Text(" · \(d)").foregroundColor(CallInk.muted) }
        if let a = agentFirst(c.agentName) { t = t + Text(" · \(a)").foregroundColor(CallInk.muted) }
        if c.followUpOpen { t = t + Text(" · Follow up").foregroundColor(CallInk.missedText) }
        return t
    }
}

/// 34 pt to the eye (the web's circle), 48 pt to the finger.
private struct RoundIcon: View {
    let glyph: WebGlyph
    let iconSize: CGFloat
    let label: String
    let bg: Color
    let tint: Color
    let border: Color
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            ZStack {
                Circle().fill(bg)
                Circle().stroke(border, lineWidth: 1)
                WebIcon(glyph: glyph, size: iconSize).foregroundColor(tint)
            }
            .frame(width: 34, height: 34)
            .frame(width: 48, height: 48)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// "Voicemail": WhatsApp voicemail arrived for this call (the audio is in the chat).
private struct VoicemailBadge: View {
    var body: some View {
        Text(CallWords.VOICEMAIL).font(NeemaFont.manrope(10, .semibold)).foregroundColor(CallInk.amber).lineLimit(1)
            .padding(.horizontal, 7).padding(.vertical, 1)
            .background(Capsule().fill(CallInk.amber.opacity(0.14)))
            .overlay(Capsule().stroke(CallInk.amber.opacity(0.35), lineWidth: 1))
    }
}

// ── The transcript panel ──────────────────────────────────────────────────────

/// The expandable transcript + AI summary panel under a call row: summary,
/// full transcript toggle (with language), status lines, on-demand
/// transcription (the free path — CPU is spent only when you ask) and retry,
/// plus playback of the recording.
private struct TranscriptPanel: View {
    let t: TranscriptUi
    let vm: CallsViewModel
    var compact = false
    var inDetails = false

    var body: some View {
        // Under the row's text: its inset + the 40 pt avatar + the gap (in the details: the card's own padding).
        let lead: CGFloat = inDetails ? 0 : (compact ? 64 : 68)
        let trail: CGFloat = inDetails ? 0 : (compact ? 16 : 24)
        let bottom: CGFloat = inDetails ? 8 : 16
        Group {
            if let data = t.data {
                loaded(data)
            } else if let err = t.loadErr {
                HStack(spacing: 0) {
                    Text("\(err) ").font(NeemaFont.manrope(12)).foregroundColor(CallInk.red)
                    Button("Retry") { vm.retryTranscript() }.font(NeemaFont.manrope(12)).foregroundColor(CallInk.green).underline()
                        .frame(minHeight: 44).padding(.horizontal, 4)
                }
            } else {
                Text("Loading…").font(NeemaFont.manrope(12)).foregroundColor(CallInk.muted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, lead).padding(.trailing, trail).padding(.bottom, bottom)
    }

    @ViewBuilder private func loaded(_ data: CallTranscript) -> some View {
        let st = data.status
        VStack(alignment: .leading, spacing: 0) {
            if let s = data.summary, !s.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("CALL SUMMARY").font(NeemaFont.manrope(11)).tracking(0.6).foregroundColor(CallInk.green)
                    Text(s).font(NeemaFont.manrope(13)).lineSpacing(4).foregroundColor(CallInk.soft)
                }
                .padding(.horizontal, 12).padding(.vertical, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 10).fill(CallInk.whatsApp.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(CallInk.whatsApp.opacity(0.15), lineWidth: 1))
                .padding(.bottom, 8)
            }
            if st == "done", let tx = data.transcript, !tx.isEmpty {
                Button { vm.toggleFull() } label: {
                    Text((t.showFull ? "Hide" : "Show") + " full transcript" + ((data.language ?? "").isEmpty ? "" : " · \(data.language!)"))
                        .font(NeemaFont.manrope(11)).foregroundColor(CallInk.muted).frame(minHeight: 44).padding(.vertical, 2)
                }
                .buttonStyle(.plain)
                if t.showFull { TranscriptText(text: tx) }
            }
            if st == "pending" || st == "processing" {
                Text("Transcribing… this runs on our server, usually ~1–2 min.").font(NeemaFont.manrope(12)).foregroundColor(CallInk.gold)
            }
            if st == "recorded" {
                Button { vm.runTranscribe() } label: {
                    Text(t.busy ? "Starting…" : "Transcribe & summarise").font(NeemaFont.manrope(12, .medium)).foregroundColor(CallInk.ink)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(RoundedRectangle(cornerRadius: 8).fill(CallInk.green))
                        .frame(minHeight: 44)
                }
                .buttonStyle(.plain)
                .disabled(t.busy)
                .opacity(t.busy ? 0.6 : 1)
            }
            if st == "failed" {
                HStack(spacing: 0) {
                    Text("Transcription failed. ").font(NeemaFont.manrope(12)).foregroundColor(CallInk.red)
                    Button("Retry") { vm.runTranscribe() }.font(NeemaFont.manrope(12)).foregroundColor(CallInk.green).underline()
                        .disabled(t.busy).frame(minHeight: 44).padding(.horizontal, 4)
                }
            }
            if st == "none" && !data.hasRecording {
                Text("No recording was captured for this call.").font(NeemaFont.manrope(12)).foregroundColor(CallInk.muted)
            }
            if let e = t.err { Text(e).font(NeemaFont.manrope(12)).foregroundColor(CallInk.red).padding(.top, 6) }
            if data.hasRecording, let u = data.recordingUrl, !u.isEmpty {
                RecordingPlayer(url: recordingUrl(u)).padding(.top, 8)
            }
        }
    }
}

/// The transcript: WhatsApp's own is speaker-separated ("Agent: …" /
/// "Customer: …" lines) — each turn under its speaker's label; any other
/// transcript as plain text.
private struct TranscriptText: View {
    let text: String
    var body: some View {
        if let turns = transcriptTurns(text) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(turns.enumerated()), id: \.offset) { _, turn in
                    VStack(alignment: .leading, spacing: 0) {
                        Text(turn.speaker).font(NeemaFont.manrope(11, .semibold)).foregroundColor(turn.speaker == "Agent" ? CallInk.green : CallInk.gold)
                        Text(turn.text).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(CallInk.sage)
                    }
                }
            }
            .padding(.top, 6)
        } else {
            Text(text).font(NeemaFont.manrope(12)).lineSpacing(4).foregroundColor(CallInk.sage).padding(.top, 6)
        }
    }
}

/// Play / pause + scrubber for the call recording (AVPlayer). The player is
/// only built on the first tap of Play, so opening a transcript costs nothing.
private struct RecordingPlayer: View {
    let url: String
    @StateObject private var p = RecordingPlayback()

    var body: some View {
        if p.failed {
            Text("Couldn't play the recording.").font(NeemaFont.manrope(12)).foregroundColor(CallInk.red)
        } else {
            HStack(spacing: 8) {
                Button { p.toggle(url) } label: {
                    ZStack {
                        Circle().fill(CallInk.green)
                        if p.buffering { ProgressView().progressViewStyle(.circular).tint(CallInk.ink).scaleEffect(0.6) }
                        else { Image(systemName: p.playing ? "pause.fill" : "play.fill").font(.system(size: 14, weight: .bold)).foregroundColor(CallInk.ink) }
                    }
                    .frame(width: 30, height: 30).frame(width: 44, height: 44).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(p.playing ? "Pause" : "Play recording")
                Slider(value: Binding(get: { p.scrub >= 0 ? p.scrub : p.progress }, set: { p.scrub = $0 }), in: 0...1) { editing in if !editing { p.scrubDone() } }
                    .tint(CallInk.green)
                Text(p.label).font(NeemaFont.manrope(11)).monospacedDigit().foregroundColor(CallInk.muted).lineLimit(1)
            }
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.06)))
            .onDisappear { p.release() }
        }
    }
}

@MainActor
private final class RecordingPlayback: ObservableObject {
    @Published var playing = false
    @Published var buffering = false
    @Published var failed = false
    @Published var pos: Double = 0
    @Published var dur: Double = 0
    @Published var scrub: Double = -1
    private var player: AVPlayer?
    private var ticker: Any?
    private var endObserver: Any?

    var progress: Double { dur > 0 ? pos / dur : 0 }
    var label: String { dur > 0 ? "\(fmt(pos)) / \(fmt(dur))" : fmt(pos) }
    private func fmt(_ s: Double) -> String { let t = Int(s); return "\(t / 60):" + String(format: "%02d", t % 60) }

    func toggle(_ url: String) {
        if player == nil {
            guard let u = URL(string: url) else { failed = true; return }
            let item = AVPlayerItem(url: u)
            let pl = AVPlayer(playerItem: item)
            player = pl
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
            try? AVAudioSession.sharedInstance().setActive(true)
            ticker = pl.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.25, preferredTimescale: 600), queue: .main) { [weak self] t in
                guard let self = self else { return }
                self.pos = t.seconds.isFinite ? t.seconds : 0
                let d = item.duration.seconds
                if d.isFinite && d > 0 { self.dur = d }
                self.buffering = pl.timeControlStatus == .waitingToPlayAtSpecifiedRate
                if item.status == .failed { self.failed = true; self.playing = false }
            }
            endObserver = NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main) { [weak self] _ in
                guard let self = self else { return }
                self.player?.pause(); self.player?.seek(to: .zero); self.pos = 0; self.playing = false
            }
            if pos > 0 { pl.seek(to: CMTime(seconds: pos, preferredTimescale: 600)) }
        }
        guard let pl = player else { return }
        if playing { pl.pause(); playing = false } else { pl.play(); playing = true }
    }

    func scrubDone() {
        if dur > 0 && scrub >= 0 {
            let to = scrub * dur
            player?.seek(to: CMTime(seconds: to, preferredTimescale: 600))
            pos = to
        }
        scrub = -1
    }

    func release() {
        player?.pause()
        if let t = ticker { player?.removeTimeObserver(t) }
        if let e = endObserver { NotificationCenter.default.removeObserver(e) }
        player = nil; ticker = nil; endObserver = nil
        playing = false
    }
}

// ── Banners ───────────────────────────────────────────────────────────────────

/// `calling_restricted`: Meta flagged or restricted calling on the number
/// (low quality, low pickup, the call button hidden). Calls we place may fail
/// until it lifts — up to 7 days.
private struct RestrictionBanner: View {
    let r: CallingRestriction
    let inset: CGFloat
    let onDismiss: () -> Void
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            WebIcon(glyph: CallIcons.alert, size: 18).foregroundColor(CallInk.red).padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text("WhatsApp restricted calling on this number").font(NeemaFont.manrope(13, .medium)).foregroundColor(CallInk.text)
                Text(restrictionText(r)).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(CallInk.sage)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Button(action: onDismiss) {
                WebIcon(glyph: CallIcons.close, size: 16).foregroundColor(CallInk.sage).frame(width: 48, height: 48).contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss")
        }
        .padding(.leading, 14).padding(.vertical, 12).padding(.trailing, 4)
        .background(RoundedRectangle(cornerRadius: 12).fill(CallInk.red.opacity(0.1)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(CallInk.red.opacity(0.3), lineWidth: 1))
        .padding(.horizontal, inset).padding(.bottom, 16)
    }
}

/// The log is showing what it last had because a refresh failed.
private struct LoadErrorBanner: View {
    let message: String
    let refreshing: Bool
    let inset: CGFloat
    let onRetry: () -> Void
    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 0) {
                Text("Showing the last call log").font(NeemaFont.manrope(13, .medium)).foregroundColor(CallInk.text)
                Text(message).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(CallInk.sage)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            RetryButton(busy: refreshing, action: onRetry)
        }
        .padding(.leading, 14).padding(.trailing, 8).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 12).fill(CallInk.red.opacity(0.1)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(CallInk.red.opacity(0.25), lineWidth: 1))
        .padding(.horizontal, inset).padding(.bottom, 12)
    }
}

/// A small pill that retries a failed load; a spinner while it runs (no double taps).
private struct RetryButton: View {
    let busy: Bool
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Group {
                if busy { ProgressView().progressViewStyle(.circular).tint(CallInk.green).scaleEffect(0.7).frame(width: 14, height: 14) }
                else { Text("Retry").font(NeemaFont.manrope(12, .medium)).foregroundColor(CallInk.green) }
            }
            .padding(.horizontal, 14).padding(.vertical, 6)
            .background(Capsule().fill(CallInk.whatsApp.opacity(0.16)))
            .overlay(Capsule().stroke(CallInk.whatsApp.opacity(0.3), lineWidth: 1))
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(busy)
        .accessibilityLabel("Retry")
    }
}

/// Why a call might not ring this phone, and the one tap that fixes it.
private struct ReadinessBanner: View {
    let r: CallReadiness
    let compact: Bool
    let inset: CGFloat
    let onFix: () -> Void
    var body: some View {
        let action = Button(action: onFix) {
            Text(r.button).font(NeemaFont.manrope(12, .medium)).foregroundColor(CallInk.ink)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(Capsule().fill(CallInk.amber))
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        HStack(alignment: compact ? .top : .center, spacing: 12) {
            Image(systemName: "bell.badge.fill").font(.system(size: 16)).foregroundColor(CallInk.gold).padding(.top, compact ? 1 : 0)
            VStack(alignment: .leading, spacing: 2) {
                Text(r.title).font(NeemaFont.manrope(13, .medium)).foregroundColor(CallInk.text)
                Text(r.text).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(CallInk.sage)
                if compact { action }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if !compact { action }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: 12).fill(CallInk.amber.opacity(0.1)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(CallInk.amber.opacity(0.3), lineWidth: 1))
        .padding(.horizontal, inset).padding(.bottom, 16)
    }
}

// ── The details ───────────────────────────────────────────────────────────────

/// One call's details: what happened (rang → answered by → ended), the
/// recording, transcript and insights, what to do next (Call back · Open chat
/// · Mark follow-up done), then the customer's full CRM panel.
private struct CallDetails: View {
    @ObservedObject var model: CallsScreenModel
    let sel: Call
    let calls: [Call]
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    private var vm: CallsViewModel { model.vm }

    var body: some View {
        let messenger = channelOf(sel.channel) == CallWords.MESSENGER
        // The customer's handle on the call's app: the wa_id, or (Messenger) the PSID — never shown.
        let wa = callHandle(sel)
        let callerCalls = wa.isEmpty ? [] : calls.filter { channelOf($0.channel) == channelOf(sel.channel) && callHandle($0) == wa }
        let w = callRowWords(sel)
        // A synthetic conversation handle is enough — the panel fetches the real CRM profile by wa_id itself.
        let conv = Conversation(id: "call:\(sel.callId)", waId: messenger ? nil : wa, externalId: wa, lastMessageAt: sel.startedAt,
                                name: sel.name, channel: messenger ? CallWords.MESSENGER : CallWords.WHATSAPP)
        VStack(spacing: 12) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 8) {
                        WebIcon(glyph: CallIcons.of(w.icon), size: 16).foregroundColor(callToneColor(w.tone))
                        Text(rowWho(sel)).font(NeemaFont.manrope(16, .semibold)).foregroundColor(CallInk.text).lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading).accessibilityAddTraits(.isHeader)
                        Button("Close") { vm.select(nil) }.font(NeemaFont.manrope(12)).foregroundColor(CallInk.sage).frame(minWidth: 44, minHeight: 44)
                    }
                    HStack(spacing: 6) {
                        let d = callDuration(sel.duration)
                        Text("\(w.label)\(d.isEmpty ? "" : " · \(d)") · \(Fmt.dateTime(sel.startedAt))").font(NeemaFont.manrope(12)).foregroundColor(callToneColor(w.tone))
                        Spacer(minLength: 0)
                        if sel.hasVoicemail { VoicemailBadge() }
                        CallChannelBadge(channel: sel.channel, onDark: true)
                    }
                    .padding(.top, 2)
                    if sel.hasVoicemail {
                        Text("They left a voicemail — open the chat to listen.").font(NeemaFont.manrope(12)).foregroundColor(CallInk.sage).padding(.top, 6)
                    }
                    Timeline(c: sel).padding(.top, 12)
                    // Recording / transcript state (§7), and the insights the AI drew from the call.
                    if let line = recordingLine(sel) { Text(line).font(NeemaFont.manrope(12)).foregroundColor(CallInk.sage).padding(.top, 10) }
                    if let ins = sel.insights { InsightsBlock(i: ins).padding(.top, 10) }
                    if sel.hasRecording || !(sel.summary ?? "").isEmpty {
                        let open = model.transcript?.callId == sel.callId
                        Button { vm.toggleTranscript(sel.callId) } label: {
                            Text(open ? "Hide summary & transcript" : "Summary, transcript & recording")
                                .font(NeemaFont.manrope(12, .medium)).foregroundColor(CallInk.green).frame(minHeight: 48)
                        }
                        .buttonStyle(.plain)
                        if open, let t = model.transcript { TranscriptPanel(t: t, vm: vm, compact: true, inDetails: true) }
                    }
                    FlowLayout(spacing: 8, lineSpacing: 8) {
                        if !wa.isEmpty {
                            // Messenger calls back on Messenger only while it can call (the channels keep this current).
                            if vm.canCallBack(sel) {
                                StripButton(text: messenger ? "Call back on Messenger" : "Call back", filled: true, fill: messenger ? Msgr.ink : CallInk.waTealText) { vm.callBack(sel) }
                            }
                            StripButton(text: "Open chat") {
                                let key = (messenger && !(sel.conversationId ?? "").isEmpty) ? sel.conversationId! : wa
                                app.openConversationFor(key)
                            }
                        }
                        if sel.followUpOpen {
                            StripButton(text: model.doneBusy.contains(sel.callId) ? "Saving…" : "Mark follow-up done") { vm.markFollowUpDone(sel) }
                        }
                    }
                    .padding(.top, 8)
                    if callerCalls.count > 1 {
                        let missed = callerCalls.filter { $0.status == "missed" }.count
                        Text("\(callerCalls.count) calls with them" + (missed > 0 ? " · \(missed) missed" : "")
                             + (callerCalls.first?.startedAt.map { " · last \(Fmt.timeAgo($0))" } ?? ""))
                            .font(NeemaFont.manrope(12)).foregroundColor(CallInk.sage).padding(.top, 10)
                    }
                }
                .padding(.horizontal, 16).padding(.vertical, 14)
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxHeight: 460)
            .background(RoundedRectangle(cornerRadius: 16).fill(CallInk.ink))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(CallInk.whatsApp.opacity(0.14), lineWidth: 1))
            if !wa.isEmpty {
                CustomerPanelView(conversation: conv, onClose: { vm.select(nil) }, onOpenIdentity: { _, externalId in app.openConversationFor(externalId) },
                                  onNameChange: { _, _ in vm.load() })
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(c.bg2)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(c.isDark ? c.border : Palette.stone200, lineWidth: 1))
            }
        }
        .padding(.vertical, 24)
    }
}

/// Rang → answered by → ended, each with its time.
private struct Timeline: View {
    let c: Call
    var body: some View {
        let out = c.direction == "outbound"
        var steps: [(String, String?)] = []
        steps.append((out ? "Called\(agentFirst(c.agentName).map { " by \($0)" } ?? "")" : "Rang", c.startedAt))
        if let a = c.answeredAt { steps.append((out ? "Answered" : "Answered\(agentFirst(c.agentName).map { " by \($0)" } ?? "")", a)) }
        let end: String? = {
            switch c.status {
            case "ringing": return nil
            case "answered": return "On the call now"
            case "completed", "ended": let d = callDuration(c.duration); return "Ended\(d.isEmpty ? "" : " · \(d)")"
            default: return callRowWords(c).label
            }
        }()
        if let e = end { steps.append((e, c.status == "answered" ? nil : c.endedAt)) }
        let tone = callToneColor(callRowWords(c).tone)
        return VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { i, step in
                HStack(spacing: 10) {
                    Circle().fill(i == steps.count - 1 ? tone : CallInk.sage).frame(width: 8, height: 8)
                    Text(step.0).font(NeemaFont.manrope(13)).foregroundColor(CallInk.text).frame(maxWidth: .infinity, alignment: .leading)
                    if let at = step.1 { Text(Fmt.time(at)).font(NeemaFont.manrope(12)).monospacedDigit().foregroundColor(CallInk.dim) }
                }
                .padding(.vertical, 2)
            }
        }
    }
}

/// §7's recording words for a finished call (nil when nothing was recorded).
private func recordingLine(_ c: Call) -> String? {
    switch c.transcriptStatus {
    case "recorded": return "Recording saved — Transcribe below"
    case "pending", "processing": return "Recording saved — summary in a minute"
    case "done": return "Recording saved · summarised"
    case "failed": return "Recording saved — the transcript failed; retry below"
    default: return c.hasRecording ? "Recording saved" : nil
    }
}

/// What the AI drew from the call: intent, products, objections, agreed, next action.
private struct InsightsBlock: View {
    let i: CallInsights
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("INSIGHTS").font(NeemaFont.manrope(11)).tracking(0.6).foregroundColor(CallInk.green)
            line("Wants", i.intent)
            line("Products", i.products.isEmpty ? nil : i.products.joined(separator: ", "))
            line("Concerns", i.objections.isEmpty ? nil : i.objections.joined(separator: "; "))
            line("Agreed", i.commitments.isEmpty ? nil : i.commitments.joined(separator: "; "))
            line("Next", i.nextAction)
            line("Mood", i.sentiment)
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(CallInk.whatsApp.opacity(0.06)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(CallInk.whatsApp.opacity(0.15), lineWidth: 1))
    }
    @ViewBuilder private func line(_ k: String, _ v: String?) -> some View {
        if let v = v, !v.trimmingCharacters(in: .whitespaces).isEmpty {
            Text("\(k): \(v)").font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(CallInk.soft)
        }
    }
}

private struct StripButton: View {
    let text: String
    var filled = false
    var fill: Color = CallInk.waTealText
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if filled { WebIcon(glyph: CallIcons.phone, size: 15).foregroundColor(.white) }
                Text(text).font(NeemaFont.manrope(14, .semibold)).foregroundColor(filled ? .white : CallInk.text)
            }
            .padding(.horizontal, 16).padding(.vertical, 8)
            // The web's CallDetail buttons: the call one white on #008069, the rest quiet.
            .background(Capsule().fill(filled ? fill : Color.white.opacity(0.08)))
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
