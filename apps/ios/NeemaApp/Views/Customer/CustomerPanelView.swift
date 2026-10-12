import SwiftUI
import NeemaCore

/// The customer profile / CRM panel beside a thread (components/ui/CustomerSidebar.tsx,
/// Android `CustomerPanel`). The inbox calls exactly this signature: the open
/// thread's row, `onClose`, `onOpenIdentity` (jump to this person's thread on
/// another channel), `onNameChange` (the inbox patches its rows), and `hideHeader`
/// when a sheet shows its own header. The panel scrolls on its own; the
/// made-to-order card and Quick Actions stay pinned under the scroll, as on the web.
struct CustomerPanelView: View {
    let conversation: Conversation
    let onClose: () -> Void
    let onOpenIdentity: (String, String) -> Void
    let onNameChange: (String, String) -> Void
    var hideHeader: Bool = false
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    var body: some View {
        if let screen = app.inboxScreen {
            CustomerPanelBody(model: screen.customer(for: conversation), conversation: conversation, onClose: onClose,
                              onOpenIdentity: onOpenIdentity, onNameChange: onNameChange, hideHeader: hideHeader)
                .id(conversation.id)
        } else {
            Color.clear
        }
    }
}

/// Below this the made-to-order card scrolls with the panel instead of being pinned.
private let PIN_ENQUIRY_MIN_HEIGHT: CGFloat = 860

private struct CustomerPanelBody: View {
    @ObservedObject var model: CustomerPanelModel
    let conversation: Conversation
    let onClose: () -> Void
    let onOpenIdentity: (String, String) -> Void
    let onNameChange: (String, String) -> Void
    let hideHeader: Bool
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    private var vm: CustomerViewModel { model.vm }

    var body: some View {
        let ui = model.ui
        // Web parity (owner's call): CustomerSidebar is open to every signed-in agent and the CRM routes
        // only check login. Only the stage editor stays admin-only — shown exactly to whom
        // PUT /settings/pipeline-stages admits, so nobody gets an editor that 403s.
        let isAdmin = InboxPerms.canEditPipelineStages(agent: app.currentAgent)
        VStack(spacing: 0) {
            if !hideHeader { PanelHeader(onClose: onClose) }
            if ui.loading && ui.profile == nil {
                ProgressView().tint(c.gold).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let p = ui.profile {
                let ctx = PanelCtx.make(profile: p, allOrders: app.inboxHost.orders.value, waId: conversation.waId, customStages: ui.customStages, isAdmin: isAdmin)
                GeometryReader { g in
                    // The web pins the made-to-order card and Quick Actions under the scroll. On a short pane
                    // that pair would leave almost no room to scroll, so there the card rides at the top instead.
                    let pinEnquiry = g.size.height >= PIN_ENQUIRY_MIN_HEIGHT
                    VStack(spacing: 0) {
                        ScrollView {
                            // The tab body's surface runs to the bottom even when a tab is short, as on the web.
                            VStack(spacing: 0) {
                                LoadErrorBanner(model: model)
                                Hero(model: model, ctx: ctx, conversation: conversation, onOpenIdentity: onOpenIdentity)
                                CrmHairline()
                                if vm.callsKey() != nil || vm.psidForCalls() != nil {
                                    CallsSection(model: model)
                                    CrmHairline()
                                }
                                QuickStats(ctx: ctx)
                                CrmHairline()
                                if !pinEnquiry { EnquiryCard(model: model, canProduce: true, inline: true) }
                                TabsBar(active: ui.tab) { vm.setTab($0) }
                                Group {
                                    switch ui.tab {
                                    case .profile: ProfileTab(model: model, ctx: ctx, onNameChange: onNameChange, onOpenIdentity: onOpenIdentity)
                                    case .insights: InsightsTab(ctx: ctx)
                                    case .activity: ActivityTab(ctx: ctx)
                                    }
                                }
                                .padding(16)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(c.surface)
                            }
                            .frame(minHeight: g.size.height, alignment: .top)
                            .background(c.surface)
                        }
                        .refreshable {
                            vm.refresh()
                            try? await Task.sleep(nanoseconds: 600_000_000)
                        }
                        if pinEnquiry { EnquiryCard(model: model, canProduce: true, inline: false) }
                        QuickActions(model: model, ctx: ctx)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg2)
        // Live only while on screen: re-shown → refetch; foreground / reconnect / orders → catch up.
        .onAppear { vm.sync(conversation); vm.onShown() }
        .onDisappear { vm.onHidden() }
        // The web reloads the profile when the thread's row changes (new message, rename).
        .onChange(of: conversation) { vm.sync($0) }
    }
}

private struct PanelHeader: View {
    let onClose: () -> Void
    @Environment(\.neema) private var c
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("CUSTOMER").font(NeemaFont.manrope(12, .bold)).tracking(1.5).foregroundColor(c.text)
                Spacer()
                Button(action: onClose) { Image(systemName: "chevron.right").foregroundColor(c.muted).frame(width: 44, height: 44) }
                    .accessibilityLabel("Collapse sidebar")
            }
            .padding(.leading, 16).padding(.trailing, 4)
            .frame(height: 48)
            CrmHairline()
        }
    }
}

/// The last profile GET failed: say why above what is still shown (the last good
/// profile, or the fallback from the chat row), with a Retry.
private struct LoadErrorBanner: View {
    @ObservedObject var model: CustomerPanelModel
    @Environment(\.neema) private var c
    var body: some View {
        if let msg = model.ui.loadError {
            let amber = c.isDark ? Palette.amber300 : Palette.amber800
            VStack(spacing: 0) {
                HStack(spacing: 8) {
                    Text(msg).font(NeemaFont.manrope(11)).lineSpacing(2).foregroundColor(amber)
                    Spacer(minLength: 0)
                    Button { model.vm.refresh() } label: {
                        Text(model.ui.refreshing ? "Retrying…" : "Retry").font(NeemaFont.manrope(11, .semibold)).foregroundColor(amber).padding(.horizontal, 10).padding(.vertical, 8)
                    }
                    .disabled(model.ui.refreshing)
                }
                .padding(.leading, 16).padding(.trailing, 8).padding(.vertical, 8)
                .background(c.isDark ? Palette.amber500.opacity(0.12) : Palette.amber50)
                Rectangle().fill(c.isDark ? Palette.amber500.opacity(0.3) : Palette.amber300).frame(height: 1)
            }
        }
    }
}

// ── Hero ────────────────────────────────────────────────────────────────────

private struct Hero: View {
    @ObservedObject var model: CustomerPanelModel
    let ctx: PanelCtx
    let conversation: Conversation
    let onOpenIdentity: (String, String) -> Void
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @Environment(\.openURL) private var openURL
    @State private var platformSheet = false

    private var vm: CustomerViewModel { model.vm }

    var body: some View {
        let p = ctx.profile
        let ui = model.ui
        // A dialable phone — never a web visitor's `web_<hash>` key (see realPhoneDigits).
        let phoneDigits = Crm.realPhoneDigits(p.phone)
        // A website chat visitor with no phone on file: say so, never a number made from the hash.
        let webVisitor = Inbox.isWebVisitor(p.waId) && phoneDigits == nil
        let channels = app.inboxHost.callChannels.value
        let button = CustomerWords.callButtonFor(conversation, channels: channels, phoneDigits: phoneDigits)
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 12) {
                AvatarView(name: Fmt.displayName(p.name, p.waId), size: 44)
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 0) {
                        if let n = p.name, !n.isEmpty {
                            Text(n).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text).lineLimit(1)
                        } else {
                            // The thread header's words for an unnamed web visitor; otherwise the web's "Unknown".
                            Text(Inbox.isWebVisitor(p.waId) ? "Website visitor" : "Unknown").font(NeemaFont.manrope(14)).italic().foregroundColor(c.muted)
                        }
                        if p.nameConfirmed { Text(" ✓").font(NeemaFont.manrope(9, .bold)).foregroundColor(Palette.emerald600) }
                    }
                    HStack(spacing: 0) {
                        let flag = Fmt.flagEmoji(p.countryIso)
                        if !flag.isEmpty { Text("\(flag) ").font(NeemaFont.manrope(12)) }
                        // The web: the phone when it has ≥ 7 digits, else the wa_id.
                        let phoneLike = (p.phone ?? "").filter { $0.isNumber }.count >= 7 && !Inbox.isWebVisitor(p.phone)
                        // A Messenger call's details (Calls view): the PSID standing in for the key is no number — never shown.
                        let appId = conversation.id.hasPrefix("call:") && conversation.channel == "messenger" && !(conversation.externalId ?? "").isEmpty &&
                            (p.waId ?? "").filter { $0.isNumber } == (conversation.externalId ?? "").filter { $0.isNumber }
                        if webVisitor || phoneLike || !appId {
                            Text(webVisitor ? "Web chat" : Fmt.formatPhone(phoneLike ? p.phone : p.waId))
                                .font(webVisitor ? NeemaFont.manrope(12) : NeemaFont.mono(12)).foregroundColor(c.muted).lineLimit(1)
                        }
                    }
                    FlowLayout(spacing: 6, lineSpacing: 4) {
                        let sm = stageMeta(ctx.stage)
                        HStack(spacing: 4) {
                            Circle().fill(sm.dot).frame(width: 6, height: 6)
                            Text(sm.label).font(NeemaFont.manrope(10, .semibold)).foregroundColor(sm.color.themed(c.isDark))
                        }
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(sm.color.dim()))
                        if let iso = p.countryIso, !iso.isEmpty {
                            HStack(spacing: 4) {
                                // The flag_url may point at an SVG; the PNG from flagcdn draws everywhere.
                                let flagUrl = (p.flagUrl?.hasSuffix(".svg") == false ? p.flagUrl : nil) ?? "https://flagcdn.com/w40/\(iso.lowercased()).png"
                                if let u = URL(string: flagUrl) {
                                    AsyncImage(url: u) { im in im.resizable().scaledToFill() } placeholder: { Color.clear }
                                        .frame(width: 16, height: 16).clipShape(RoundedRectangle(cornerRadius: 2)).roundedBorder(c.hairline, radius: 2)
                                }
                                // An explicit (user-entered) country wins over the ISO's English name.
                                Text((p.country?.trimmingCharacters(in: .whitespaces)).flatMap { $0.isEmpty ? nil : $0 } ?? Fmt.countryName(iso))
                                    .font(NeemaFont.manrope(10)).foregroundColor(c.textMid)
                            }
                            .accessibilityLabel(p.country ?? iso)
                        }
                        if ui.saving { Text("saving…").font(NeemaFont.manrope(10)).foregroundColor(c.muted) }
                    }
                    .padding(.top, 6)
                }
            }

            // The SERVER owns the score (it ranks the leads list on it).
            let score = min(100, Int(p.leadScore.rounded()))
            HStack {
                Text("Lead Score").font(NeemaFont.manrope(10, .medium)).foregroundColor(c.muted)
                Spacer()
                Text("\(score)/100").font(NeemaFont.manrope(10)).foregroundColor(c.textMid)
            }
            .padding(.top, 12).padding(.bottom, 4)
            ScoreBar(score: score)

            // Segment badge + buying rhythm — a quick read while chatting.
            if let tier = p.tier, !tier.isEmpty {
                let tm = CustomerWords.TIER_META[tier]
                let look = TIER_LOOK[tier]
                FlowLayout(spacing: 6, lineSpacing: 4) {
                    let fg = look?.color.themed(c.isDark) ?? c.textMid
                    Text((p.tierLabel?.isEmpty == false ? p.tierLabel : nil) ?? tm?.label ?? tier)
                        .font(NeemaFont.manrope(10, .semibold)).foregroundColor(fg)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill(c.isDark || look == nil ? fg.dim(0.1) : look!.bg))
                        .roundedBorder(look?.border ?? c.hairline, radius: 4)
                        .accessibilityHint(tm?.title ?? "")
                    if let cadence = p.buyingRhythm?.cadenceLabel, !cadence.isEmpty {
                        Text("Buys \(cadence)").font(NeemaFont.manrope(10)).foregroundColor(c.textMid)
                    }
                    if p.buyingRhythm?.overdue == true {
                        Text("⏰ Overdue").font(NeemaFont.manrope(10, .semibold)).foregroundColor(Palette.amber700.themed(c.isDark))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(RoundedRectangle(cornerRadius: 4).fill(c.isDark ? Palette.amber500.dim(0.1) : Palette.amber50))
                            .roundedBorder(Palette.amber300, radius: 4)
                            .accessibilityHint("Past their usual buying gap — a good moment to reach out")
                    }
                }
                .padding(.top, 8)
            }

            // Channel chips (tap → that channel's thread), the WhatsApp invite, "+N merged".
            FlowLayout(spacing: 4, lineSpacing: 4) {
                ForEach(Array(p.channels.enumerated()), id: \.offset) { _, ch in
                    let label = Crm.channelLabel(ch.channel, identifier: ch.identifier)
                    Button {
                        // Non-WhatsApp channels have no wa_id identifier; this thread's own handle stands in.
                        let handle = ch.identifier ?? (ch.channel == conversation.channel ? conversation.handle : "")
                        onOpenIdentity(ch.channel, handle)
                    } label: {
                        HStack(spacing: 4) {
                            ChannelBadge(channel: Crm.badgeKey(ch.channel, identifier: ch.identifier), size: 20)
                            Text(label).font(NeemaFont.manrope(10)).foregroundColor(c.text)
                        }
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill(c.isDark ? c.bg3 : Palette.slate100))
                        .roundedBorder(c.border, radius: 4)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Open \(label) conversation")
                }
                // A captured phone gives this customer a WhatsApp door before their first WhatsApp message —
                // shown only when no WhatsApp thread exists yet (a web visitor's thread is not one).
                let hasWa = p.channels.contains { $0.channel == "whatsapp" && !Inbox.isWebVisitor($0.identifier) }
                if !hasWa, let digits = phoneDigits, ctx.canReply {
                    Button { vm.inviteToWhatsApp(digits) { url in if let u = URL(string: url) { openURL(u) } } } label: {
                        HStack(spacing: 4) {
                            ChannelBadge(channel: "whatsapp", size: 20)
                            Text(ui.inviteBusy ? "Sending invite…" : "Invite to WhatsApp").font(NeemaFont.manrope(10, .semibold)).foregroundColor(.white)
                        }
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(RoundedRectangle(cornerRadius: 4).fill(WA_GREEN))
                        .roundedBorder(Palette.whatsAppDeep, radius: 4)
                    }
                    .buttonStyle(.plain)
                    .disabled(ui.inviteBusy)
                    .accessibilityHint("Send this customer a WhatsApp invite (delivers the approved template to their number)")
                }
                if !p.mergedIds.isEmpty {
                    Text("+\(p.mergedIds.count) merged").font(NeemaFont.manrope(10, .medium)).foregroundColor(Palette.violet600.themed(c.isDark))
                }
            }
            .padding(.top, 8)

            // Reach-out actions: a voice call + the approved template. A WhatsApp chat calls on WhatsApp;
            // a Messenger chat calls on Messenger while the server says Messenger calling is on; otherwise —
            // and on Instagram, which has no calling API — Call opens a sheet that offers a WhatsApp call instead.
            if let b = button, ctx.canReply {
                HStack(spacing: 8) {
                    ReachCallButton(button: b, busy: ui.callBusy) {
                        switch b {
                        case .onMessenger(let psid): vm.callOnMessenger(psid)
                        case .sheet: platformSheet = true
                        case .onWhatsApp(let digits): vm.call(digits)
                        }
                    }
                    if let digits = phoneDigits {
                        Button { vm.sendTemplate(digits) } label: {
                            HStack(spacing: 6) {
                                Image(systemName: "bubble.left").font(.system(size: 13))
                                Text(ui.templateBusy ? "Sending…" : "Send template").font(NeemaFont.manrope(12, .semibold)).lineLimit(2).multilineTextAlignment(.center)
                            }
                            .foregroundColor(c.isDark ? c.textMid : Palette.sageDeep)
                            .padding(.horizontal, 8).frame(maxWidth: .infinity, minHeight: 36)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? c.bg3 : Palette.sageButton))
                            .roundedBorder(c.bg4, radius: 8)
                        }
                        .buttonStyle(.plain)
                        .disabled(ui.templateBusy)
                    }
                }
                .padding(.top, 12)
            }
        }
        .padding(.leading, 16).padding(.trailing, 16).padding(.top, 16).padding(.bottom, 12)
        .background(c.bg2)
        .sheet(isPresented: $platformSheet) {
            if case .sheet(let platform)? = button {
                CallOnWhatsAppContent(platform: platform, first: firstNameOf(p.name), phone: phoneDigits,
                                      onCall: { platformSheet = false; if let d = phoneDigits { vm.call(d) } },
                                      onAsk: { platformSheet = false; vm.askForWhatsAppNumber() },
                                      onDismiss: { platformSheet = false })
                    .presentationDetents([.medium])
                    .presentationDragIndicator(.visible)
            }
        }
    }
}

private struct QuickStats: View {
    let ctx: PanelCtx
    @Environment(\.neema) private var c
    var body: some View {
        let convs = max(1, ctx.profile.channels.reduce(0) { $0 + $1.conversationCount })
        let cells: [(String, String)] = [("Orders", String(ctx.orderCount)), ("Spent", Fmt.currency(ctx.totalSpent)), ("Convs", String(convs))]
        HStack(spacing: 0) {
            ForEach(Array(cells.enumerated()), id: \.offset) { i, cell in
                VStack(spacing: 2) {
                    Text(cell.1).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text).lineLimit(1).minimumScaleFactor(0.8)
                    Text(cell.0).font(NeemaFont.manrope(10)).foregroundColor(c.textMid)
                }
                .padding(.horizontal, 8).padding(.vertical, 10)
                .frame(maxWidth: .infinity)
                if i < 2 { Rectangle().fill(c.hairline).frame(width: 1) }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .background(c.bg2)
    }
}

private struct TabsBar: View {
    let active: CustomerTab
    let onSelect: (CustomerTab) -> Void
    @Environment(\.neema) private var c
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                ForEach(CustomerTab.allCases, id: \.self) { t in
                    let on = t == active
                    Button { onSelect(t) } label: {
                        VStack(spacing: 0) {
                            // One line each, even at a large text size — the three labels never run together.
                            Text(t.rawValue.uppercased()).font(NeemaFont.manrope(10, .semibold)).tracking(1).foregroundColor(on ? c.text : c.muted).lineLimit(1)
                                .padding(.horizontal, 4).padding(.vertical, 8)
                            Rectangle().fill(on ? c.text : .clear).frame(height: 2)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(on ? .isSelected : [])
                }
            }
            .background(c.bg2)
            CrmHairline()
        }
    }
}

// ── Pinned footer ───────────────────────────────────────────────────────────

/// Made-to-order enquiry (measurement form → hub production).
private struct EnquiryCard: View {
    @ObservedObject var model: CustomerPanelModel
    let canProduce: Bool
    let inline: Bool
    @Environment(\.neema) private var c
    var body: some View {
        if let e = model.ui.enquiry {
            let pushing = model.ui.pushing
            let green = c.isDark ? c.gold2 : Palette.forestInk
            VStack(spacing: 0) {
                if !inline { CrmHairline() }
                VStack(alignment: .leading, spacing: 0) {
                    Text("🧵 MADE-TO-ORDER REQUEST").font(NeemaFont.manrope(10, .bold)).tracking(1.2).foregroundColor(c.textMid).padding(.bottom, 8)
                    VStack(alignment: .leading, spacing: 4) {
                        Text((e.productName?.isEmpty == false ? e.productName : nil) ?? "Custom item").font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
                        if !e.measurements.isEmpty {
                            Text(e.measurements.keys.sorted().map { "\($0): \(CustomerWords.display(e.measurements[$0]!))" }.joined(separator: " · "))
                                .font(NeemaFont.manrope(10)).foregroundColor(green)
                        }
                        if let n = e.notes, !n.isEmpty { Text("Notes: \(n)").font(NeemaFont.manrope(10)).foregroundColor(green) }
                        if e.status == "pushed" {
                            Text("✓ In production" + (e.hubOrderNumber.map { " · \($0)" } ?? "")).font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.gold2).padding(.top, 4)
                        } else if e.status == "declined" {
                            Text("Dismissed").font(NeemaFont.manrope(10)).foregroundColor(c.muted).padding(.top, 4)
                        } else if canProduce {
                            HStack(spacing: 6) {
                                TintButton(text: pushing ? "Sending…" : "→ Push to production", color: c.gold, filled: true, enabled: !pushing && e.pushable) { model.vm.pushProduction() }
                                NeutralButton(text: "Dismiss", textColor: c.textMid, enabled: !pushing, fill: false) { model.vm.declineProduction() }
                            }
                            .padding(.top, 4)
                            if !e.pushable {
                                Text("No linked hub product — set this order up in the hub manually.").font(NeemaFont.manrope(9)).foregroundColor(c.muted).padding(.top, 2)
                            }
                        }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.goldDim))
                    .roundedBorder(c.hairline, radius: 8)
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(c.bg2)
                if inline { CrmHairline() }
            }
        }
    }
}

private struct QuickActions: View {
    @ObservedObject var model: CustomerPanelModel
    let ctx: PanelCtx
    @Environment(\.neema) private var c
    var body: some View {
        if ctx.canEdit {
            // A stage move in flight: an impatient second tap on Advance must not skip a stage.
            let busy = model.ui.stageBusy
            VStack(spacing: 0) {
                CrmHairline()
                VStack(alignment: .leading, spacing: 6) {
                    Text("QUICK ACTIONS").font(NeemaFont.manrope(10, .bold)).tracking(1.2).foregroundColor(c.textMid).padding(.bottom, 2)
                    HStack(spacing: 6) {
                        TintButton(text: "✓ Mark Won", color: Palette.emerald700.themed(c.isDark), enabled: !busy) { model.vm.setStage("won") }
                        TintButton(text: "✕ Mark Lost", color: Palette.red600.themed(c.isDark), enabled: !busy) { model.vm.setStage("lost") }
                    }
                    NeutralButton(text: "→ Advance Stage", enabled: !busy) {
                        // Next along the forward path (custom stages included); Lost re-opens at Won, as on the web.
                        let next = Crm.nextStage(ctx.stage, customs: ctx.customStages)
                        if next != ctx.stage { model.vm.setStage(next) }
                    }
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(c.bg2)
            }
        }
    }
}

/// The panel's Call button in its app's look: WhatsApp's deep green, Messenger's darker blue while
/// Messenger calling is on, else the platform's ink for the "call on WhatsApp instead" sheet.
struct ReachCallButton: View {
    let button: CustomerWords.CallButton
    let busy: Bool
    let action: () -> Void

    var body: some View {
        // White text only on a fill it reads on (the web's #008069 / the platform's deep ink), never #25D366.
        let fill: Color = {
            switch button {
            case .onMessenger: return Color(hex: 0x0066D6)
            case .sheet(let p): return p == .messenger ? Color(hex: 0x0066E0) : Color(hex: 0xD62976)
            case .onWhatsApp: return Palette.waDeep
            }
        }()
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: "phone.fill").font(.system(size: 13))
                Text(busy ? "Calling…" : "Call").font(NeemaFont.manrope(12, .semibold)).lineLimit(1)
            }
            .foregroundColor(.white)
            .padding(.horizontal, 8).frame(maxWidth: .infinity, minHeight: 36)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(fill.opacity(busy ? 0.55 : 1)))
        }
        .buttonStyle(.plain)
        // One call at a time: a second tap while dialling would say "Already in a call".
        .disabled(busy)
        .accessibilityLabel({ if case .onMessenger = button { return "Call on Messenger" } else { return "Call" } }())
    }
}
