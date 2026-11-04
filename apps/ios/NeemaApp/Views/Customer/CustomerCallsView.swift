import SwiftUI
import NeemaCore

/// The panel's "Calls" section (CALLING_UX.md §7): this customer's last calls —
/// outcome, time, length, who took it — and how many still owe them a call
/// back. "All calls" opens the Calls view on them.
struct CallsSection: View {
    @ObservedObject var model: CustomerPanelModel
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    private var vm: CustomerViewModel { model.vm }

    var body: some View {
        // WhatsApp's number, else (a Messenger chat) the PSID — never shown, only used to fetch and focus.
        let psid = vm.psidForCalls()
        if let key = vm.callsKey() ?? psid {
            let ui = model.ui
            let onMessenger = psid != nil && app.inboxHost.callChannels.value?.messenger.outbound == true
            Group {
                if let list = ui.recentCalls {
                    let open = list.filter { $0.followUpOpen }.count
                    VStack(alignment: .leading, spacing: 0) {
                        HStack(spacing: 8) {
                            Text("CALLS").font(NeemaFont.manrope(10, .semibold)).tracking(1).foregroundColor(c.muted).accessibilityAddTraits(.isHeader)
                            if open > 0 {
                                Text("\(open) to call back").font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.isDark ? Palette.red300 : Palette.red700)
                                    .padding(.horizontal, 8).padding(.vertical, 2).background(Capsule().fill(Palette.red500.opacity(0.12)))
                            }
                            Spacer()
                            if !list.isEmpty {
                                Button { app.focusCalls(key) } label: {
                                    Text("All calls").font(NeemaFont.manrope(11, .semibold)).foregroundColor(c.isDark ? Palette.emerald300 : Palette.emerald700)
                                        .padding(.horizontal, 8).frame(minHeight: 44)
                                }
                            }
                        }
                        CallPermissionBlock(
                            p: ui.callPermission, request: ui.callRequest, first: firstNameOf(vm.displayNameForCalls()) ?? "them",
                            onSend: { vm.sendCallRequest() },
                            onCallNow: { if onMessenger, let p = psid { vm.callOnMessenger(p) } else { vm.call(key) } },
                            onSettings: { app.navigate(.settings) }
                        )
                        if list.isEmpty {
                            Text("No calls with this customer yet.").font(NeemaFont.manrope(12)).foregroundColor(c.muted).padding(.vertical, 6)
                        }
                        // Both apps in the list: each line says which.
                        let mixed = list.contains { channelOf($0.channel) == CallWords.MESSENGER }
                        ForEach(list, id: \.callId) { CallLine(call: $0, showChannel: mixed) }
                    }
                    .padding(.leading, 16).padding(.trailing, 8).padding(.vertical, 8)
                    .background(c.bg2)
                }
            }
            .onAppear { vm.loadCalls(); vm.loadPermission(); vm.watchCalls() }
            // Messenger calling switched on / off: the permission shown is the app the Call button uses.
            .onChange(of: onMessenger) { vm.loadPermission() }
        }
    }
}

/// Where this customer's call permission stands (CALLING_UX.md §2.1) — said
/// honestly: allowed permanently / until a date, a request waiting, declined,
/// revoked after unanswered calls, when a new request can go, calls left today —
/// and "Send call request" when calling them needs one.
struct CallPermissionBlock: View {
    let p: CallPermission?
    let request: CallRequestUi
    let first: String
    let onSend: () -> Void
    let onCallNow: () -> Void
    let onSettings: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let lines = p.map { permissionLines($0, first: first, now: AppClock.now()) } ?? []
        let needsRequest = p != nil && p!.canCall == false && p!.status != "requested" && !request.sent && !request.alreadyAllowed && !request.templateRequired
        if !(lines.isEmpty && !needsRequest && !request.sent && !request.alreadyAllowed && request.error == nil) {
            let link = c.isDark ? Palette.emerald300 : Palette.emerald700
            VStack(alignment: .leading, spacing: 2) {
                ForEach(lines, id: \.self) { Text($0).font(NeemaFont.manrope(12)).lineSpacing(2).foregroundColor(c.textMid) }
                if request.alreadyAllowed {
                    Text("\(first) already allows calls").font(NeemaFont.manrope(12)).foregroundColor(link)
                    SmallPill(text: "Call now", filled: true, action: onCallNow)
                } else if request.sent {
                    Text("Call request sent — you'll be told when \(first) taps Allow").font(NeemaFont.manrope(12)).foregroundColor(link)
                } else if needsRequest {
                    let blocked = p?.canRequest == false
                    SmallPill(text: request.busy ? "Sending…" : "Send call request", filled: true, enabled: !blocked && !request.busy, action: onSend)
                }
                if let e = request.error {
                    Text(e).font(NeemaFont.manrope(12)).lineSpacing(2).foregroundColor(c.isDark ? Palette.red300 : Palette.red700).padding(.top, 4)
                    if request.adminCanFix { SmallPill(text: "Open WhatsApp calling settings", filled: false, action: onSettings) }
                }
            }
            .padding(.top, 4).padding(.bottom, 4).padding(.trailing, 8)
        }
    }
}

private struct SmallPill: View {
    let text: String
    let filled: Bool
    var enabled: Bool = true
    let action: () -> Void
    @Environment(\.neema) private var c
    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if filled { Image(systemName: "phone.fill").font(.system(size: 12)).foregroundColor(.white) }
                Text(text).font(NeemaFont.manrope(13, .semibold)).foregroundColor(filled ? .white : c.text)
            }
            .padding(.horizontal, 14).padding(.vertical, 8)
            .background(Capsule().fill(filled ? Palette.waDeep : .clear))
            .overlay(Group { if !filled { Capsule().stroke(c.border) } })
            .opacity(enabled ? 1 : 0.5)
            .frame(minHeight: 48)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .padding(.top, 4)
    }
}

private struct CallLine: View {
    let call: Call
    var showChannel: Bool = false
    @Environment(\.neema) private var c
    var body: some View {
        let w = callRowWords(call)
        let tone: Color = {
            switch w.tone {
            case .live, .good: return c.isDark ? Palette.emerald300 : Palette.emerald700
            case .bad: return c.isDark ? Palette.red300 : Palette.red700
            case .warn: return c.isDark ? Palette.amber300 : Palette.amber700
            case .neutral: return c.textMid
            }
        }()
        HStack(spacing: 8) {
            CallDirGlyph(icon: w.icon, color: tone, size: 12)
            // Which app the call was on (both show here for a customer we know on both).
            if showChannel { CallChannelBadge(channel: call.channel, onDark: c.isDark, fontSize: 10) }
            VStack(alignment: .leading, spacing: 1) {
                Text([w.label, callDuration(call.duration).isEmpty ? nil : callDuration(call.duration), agentFirst(call.agentName)].compactMap { $0 }.joined(separator: " · "))
                    .font(NeemaFont.manrope(12, .medium)).foregroundColor(tone).lineLimit(1)
                if let s = call.summary, !s.trimmingCharacters(in: .whitespaces).isEmpty { Text(s).font(NeemaFont.manrope(11)).foregroundColor(c.textMid).lineLimit(2) }
                if call.hasVoicemail { Text("Voicemail — open the chat to listen").font(NeemaFont.manrope(11)).foregroundColor(c.textMid).lineLimit(1) }
            }
            Spacer(minLength: 4)
            if call.followUpOpen {
                Text("Follow up").font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.isDark ? Palette.amber300 : Palette.amber700).padding(.horizontal, 6)
            }
            Text(Fmt.timeAgo(call.startedAt)).font(NeemaFont.manrope(11)).foregroundColor(c.muted).lineLimit(1)
        }
        .padding(.vertical, 4)
    }
}

/// The Call button on a chat whose app can't call right now: it says why plainly
/// (Messenger calling isn't switched on yet; Instagram doesn't let businesses take
/// calls) and offers a WhatsApp call instead — to the number on file, or the question that asks for it.
struct CallOnWhatsAppContent: View {
    let platform: CustomerWords.CallPlatform
    let first: String?
    let phone: String?
    let onCall: () -> Void
    let onAsk: () -> Void
    let onDismiss: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let who = first ?? "them"
        let colors: [Color] = platform == .messenger ? [Color(hex: 0x00B2FF), Color(hex: 0x006AFF)] : [Color(hex: 0xF9CE34), Color(hex: 0xEE2A7B), Color(hex: 0x6228D7)]
        VStack(alignment: .leading, spacing: 0) {
            // The platform's own look: its gradient, its name.
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(Color.white.opacity(0.22))
                    Image(systemName: "phone.down.fill").font(.system(size: 16)).foregroundColor(.white)
                }
                .frame(width: 36, height: 36)
                Text(cantCallWhy(platform.rawValue)).font(NeemaFont.manrope(15, .semibold)).lineSpacing(3).foregroundColor(.white).accessibilityAddTraits(.isHeader)
            }
            .padding(.horizontal, 16).padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottomTrailing)))
            Spacer().frame(height: 14)
            Text(phone != nil ? "Call \(who) on WhatsApp instead." : "Call \(who) on WhatsApp instead — ask for their WhatsApp number first.")
                .font(NeemaFont.manrope(14)).lineSpacing(3).foregroundColor(c.text)
            Spacer().frame(height: 16)
            if phone != nil {
                SheetButton(text: "Call on WhatsApp", filled: true, action: onCall)
            } else {
                SheetButton(text: "Ask for their WhatsApp number", filled: true, action: onAsk)
                Text("Puts the question in your reply box — nothing is sent until you send it.")
                    .font(NeemaFont.manrope(12)).foregroundColor(c.muted).multilineTextAlignment(.center).frame(maxWidth: .infinity).padding(.top, 6)
            }
            Spacer().frame(height: 8)
            SheetButton(text: "Not now", filled: false, action: onDismiss)
            Spacer().frame(height: 8)
        }
        .padding(.horizontal, 20).padding(.vertical, 8)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.bg2.ignoresSafeArea())
    }
}

private struct SheetButton: View {
    let text: String
    let filled: Bool
    let action: () -> Void
    @Environment(\.neema) private var c
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if filled { Image(systemName: "phone.fill").font(.system(size: 14)).foregroundColor(.white) }
                Text(text).font(NeemaFont.manrope(15, .semibold)).foregroundColor(filled ? .white : c.text)
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
            .frame(maxWidth: .infinity, minHeight: 48)
            // White on WhatsApp's deep green (#008069, as the web's sheet): 4.9:1, not white on #25D366.
            .background(Capsule().fill(filled ? Palette.waDeep : .clear))
            .overlay(Group { if !filled { Capsule().stroke(c.border) } })
        }
        .buttonStyle(.plain)
    }
}
