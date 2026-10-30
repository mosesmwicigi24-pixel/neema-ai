import SwiftUI
import UIKit
import NeemaCore

/// Port of SettingsView.tsx (Android `SettingsScreen`) — platform configuration.
///
/// No permission gate — page.tsx renders SettingsView for anyone. The nav
/// lists Settings only with manage_settings, but the account menu's Settings
/// entry opens it for everyone. Every card loads; a save by someone who
/// isn't an admin gets the server's 403 and the web's "(admin only)" words
/// (crm.py checks role admin / superuser, not manage_settings).
struct SettingsScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.settingsScreen {
            GeometryReader { g in SettingsBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}

struct SettingsBody: View {
    @ObservedObject var model: SettingsScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    // Unsaved standing orders, offer and local fields come back after iOS reclaims the app.
    @SceneStorage("settings.ui") private var savedUi: String = ""
    @SceneStorage("settings.integration") private var expanded: String = ""

    private var vm: SettingsViewModel { model.vm }

    var body: some View {
        // The web's grid is one column on phones, two otherwise.
        let twoCols = width >= 720
        let inner = width - 32
        let column = (inner - 14) / 2
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Settings").font(NeemaFont.manrope(20, .bold)).tracking(-0.5).foregroundColor(c.text)
                    Text("Platform configuration and integrations").font(NeemaFont.manrope(12)).foregroundColor(c.textDim)
                }
                .padding(.bottom, 4)
                if twoCols {
                    // Two balanced columns: the tall offer form sits under standing orders on the
                    // left; the four shorter cards stack on the right (alternating left the right
                    // column half empty).
                    HStack(alignment: .top, spacing: 14) {
                        VStack(spacing: 14) {
                            StandingOrdersCard(model: model)
                            OfferCard(model: model, width: column)
                        }
                        .frame(maxWidth: .infinity)
                        VStack(spacing: 14) {
                            TranslationCard(model: model)
                            PipelineStagesCard(model: model)
                            BusinessCard(model: model, width: column)
                            AiCard(model: model, width: column)
                        }
                        .frame(maxWidth: .infinity)
                    }
                } else {
                    StandingOrdersCard(model: model)
                    TranslationCard(model: model)
                    OfferCard(model: model, width: inner)
                    PipelineStagesCard(model: model)
                    BusinessCard(model: model, width: inner)
                    AiCard(model: model, width: inner)
                }
                IntegrationsCard(model: model, twoCols: twoCols, width: inner, expanded: $expanded)
                // WhatsApp's own calling settings are the number's: admins only (manage_settings).
                if app.can(Perms.MANAGE_SETTINGS) {
                    WhatsAppCallingCard(m: vm.calling, u: model.calling)
                    CrashReportsCard()
                }
                DangerZoneCard { vm.dangerAction() }
                Spacer().frame(height: 24)
            }
            .padding(16)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        .refreshable { await pullToRefresh() }
        .onAppear {
            vm.restoreIfFresh(savedUi)
            vm.life.shown.update(true)
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: model.ui) { savedUi = vm.saveUi() }
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }
}

// ── Building blocks (SectionCard / Field / SmallInput) ─────────────────────────

/// The web's SectionCard: white, rounded-xl, #cee6b2 border, p-5, title block mb-4.
struct SettingsCard<Content: View>: View {
    let title: String
    var description: String? = nil
    @ViewBuilder let content: () -> Content
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text)
            if let d = description {
                Text(d).font(NeemaFont.manrope(12)).foregroundColor(c.textDim).lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true).padding(.top, 4)
            }
            Spacer().frame(height: 16)
            content()
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.isDark ? c.hairline : c.bg4))
    }
}

/// A labelled field with an optional hint under it (the web's Field; the label in Tailwind stone-600 by day).
struct SettingsField<Content: View>: View {
    let label: String
    var hint: String? = nil
    var hintColor: Color? = nil
    @ViewBuilder let content: () -> Content
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.isDark ? c.textMid : Palette.stone600)
            content()
            if let h = hint {
                Text(h).font(NeemaFont.manrope(11)).foregroundColor(hintColor ?? c.muted).fixedSize(horizontal: false, vertical: true).padding(.top, -2)
            }
        }
        .padding(.bottom, 12)
    }
}

/// The web's SmallInput by day: #f3f9ec fill, #b5da8b border (one line).
struct SettingsInput: View {
    @Binding var text: String
    var placeholder: String? = nil
    var keyboard: UIKeyboardType = .default
    var secret: Bool = false
    var isError: Bool = false
    @Environment(\.neema) private var c
    @FocusState private var focused: Bool

    var body: some View {
        let plain = secret || keyboard == .emailAddress || keyboard == .numberPad || keyboard == .phonePad
        Group {
            if secret {
                SecureField(placeholder ?? "", text: $text)
            } else {
                TextField(placeholder ?? "", text: $text)
            }
        }
        .font(NeemaFont.manrope(14)).foregroundColor(c.text)
        .keyboardType(secret ? .default : keyboard)
        .textInputAutocapitalization(plain ? .never : .sentences)
        .autocorrectionDisabled(plain)
        .focused($focused)
        .padding(.horizontal, 12).frame(minHeight: 48)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(isError ? c.red : focused ? c.gold : c.border, lineWidth: focused || isError ? 1.5 : 1))
    }
}

/// Two fields abreast (the web's two-column grid); on a narrow phone or at a large font they stack.
struct SettingsPair<A: View, B: View>: View {
    let stack: Bool
    @ViewBuilder let a: () -> A
    @ViewBuilder let b: () -> B

    var body: some View {
        if stack {
            VStack(alignment: .leading, spacing: 0) {
                a()
                b()
            }
        } else {
            HStack(alignment: .top, spacing: 12) {
                a().frame(maxWidth: .infinity, alignment: .leading)
                b().frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

/// The gold Save button: "Saving…" while the write is on the wire.
struct SettingsSaveButton: View {
    let label: String
    let saving: Bool
    var enabled: Bool = true
    let action: () -> Void

    var body: some View {
        TeamBtn(label: saving ? "Saving…" : label, variant: .primary, enabled: enabled && !saving, action: action)
    }
}

/// A live card whose read failed: the reason and a Retry for that card alone.
struct CardLoadProblem: View {
    let why: String
    let title: String
    let onRetry: () -> Void

    var body: some View {
        LoadProblem(message: why, title: title, onRetry: onRetry).padding(.bottom, 10)
    }
}

/// A 32pt pill button (the web's px-2.5 py-1.5) inside a 44pt touch target.
struct SettingsPillButton: View {
    let text: String
    let fg: Color
    let bg: Color
    let border: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(text).font(NeemaFont.manrope(11, .semibold)).foregroundColor(fg).lineLimit(1)
                .padding(.horizontal, 10).padding(.vertical, 7).frame(minHeight: 32)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(bg))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(border))
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// A selectable chip (Material's FilterChip / AssistChip): gold wash and a check when on.
struct SettingsChipButton: View {
    let label: String
    var icon: String? = nil
    let selected: Bool
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let i = icon { Image(systemName: i).font(.system(size: 12, weight: .semibold)) }
                Text(label).font(NeemaFont.manrope(12)).lineLimit(1)
            }
            .foregroundColor(selected ? c.gold2 : c.text)
            .padding(.horizontal, 12).frame(minHeight: 34)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(selected ? (c.isDark ? c.goldDim : c.bg3) : .clear))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.border))
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}

/// A text box with an Add button ("Or type a SKU", "Add a category"): Done on the keyboard adds too.
struct AddTextRow: View {
    let placeholder: String
    let onAdd: (String) -> Void
    @State private var text = ""
    @Environment(\.neema) private var c

    var body: some View {
        HStack(spacing: 6) {
            TextField(placeholder, text: $text)
                .font(NeemaFont.manrope(14)).foregroundColor(c.text).submitLabel(.done).onSubmit(submit)
                .padding(.horizontal, 12).frame(minHeight: 48)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.border))
            TeamBtn(label: "Add", variant: .standard, enabled: !text.trimmingCharacters(in: .whitespaces).isEmpty, action: submit)
        }
    }

    private func submit() {
        let t = text.trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return }
        onAdd(t)
        text = ""
    }
}

/// The web's toFixed(2): always a point, whatever the phone's language.
func settingsMoney(_ v: Double) -> String {
    if v > 0 && v < 0.01 { return "under $0.01" }
    return "$" + String(format: "%.2f", locale: Locale(identifier: "en_US_POSIX"), v)
}

// ── Standing orders ───────────────────────────────────────────────────────────

struct StandingOrdersCard: View {
    @ObservedObject var model: SettingsScreenModel
    @Environment(\.neema) private var c

    private var vm: SettingsViewModel { model.vm }

    var body: some View {
        let ui = model.ui
        let text = ui.directives
        let max = ui.maxChars
        SettingsCard(title: "Standing Orders",
                     description: "Live steering — Neema reads this before every reply. Emphasis only; pricing & payment rules always win.") {
            if let why = ui.loadErrors["directives"] {
                CardLoadProblem(why: why, title: "Couldn't load the standing orders") { vm.retry("directives") }
            }
            ZStack(alignment: .topLeading) {
                if text.isEmpty {
                    Text("e.g. \"Push copes this week — Easter is close. Quote 3-week lead times on made-to-order. Mention the new Ladies Princess Cassock to lady customers.\"")
                        .font(NeemaFont.manrope(13)).foregroundColor(c.muted)
                        .padding(.horizontal, 13).padding(.vertical, 12)
                        .allowsHitTesting(false)
                }
                TextEditor(text: model.directives)
                    .font(NeemaFont.manrope(14)).foregroundColor(c.text)
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 104, maxHeight: 240)
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .disabled(!ui.directivesLoaded)
            }
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg2))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.isDark ? c.border : c.hairline))
            .opacity(ui.directivesLoaded ? 1 : 0.6)
            Spacer().frame(height: 6)
            // The counter left, Save right; at a large font the button drops under the counter.
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center) {
                    counter(text.count, max)
                    Spacer(minLength: 12)
                    saveButton(ui)
                }
                VStack(alignment: .leading, spacing: 6) {
                    counter(text.count, max)
                    saveButton(ui)
                }
            }
        }
    }

    private func counter(_ n: Int, _ max: Int) -> some View {
        Text("\(n)/\(max)").font(NeemaFont.manrope(11)).monospacedDigit().foregroundColor(n >= max ? Palette.amber700 : c.muted)
    }

    private func saveButton(_ ui: SettingsUi) -> some View {
        SettingsSaveButton(label: "Save standing orders", saving: ui.savingDirectives, enabled: ui.directivesLoaded) { vm.saveDirectives() }
    }
}

// ── Translation ───────────────────────────────────────────────────────────────

struct TranslationCard: View {
    @ObservedObject var model: SettingsScreenModel
    @Environment(\.neema) private var c

    var body: some View {
        let s = model.ui.translation
        SettingsCard(title: "Translation for the team",
                     description: "Shows an English line under any message that is not English or Swahili — in both directions, so you can follow a whole conversation. Customers never see it.") {
            if let why = model.ui.loadErrors["translation"] {
                CardLoadProblem(why: why, title: "Couldn't load the translation setting") { model.vm.retry("translation") }
            } else {
                HStack(alignment: .center, spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(stateWord(s)).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
                        Text(spendLine(s)).font(NeemaFont.manrope(11)).foregroundColor(c.muted)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Toggle("Translation for the team", isOn: Binding(get: { s?.enabled == true }, set: { _ in model.vm.toggleTranslation() }))
                        .labelsHidden().tint(c.gold).disabled(s == nil)
                        .accessibilityLabel("Translation for the team")
                }
                if let t = s, !t.enabled {
                    Text("Translations already saved stay visible — turning this off only stops new ones being bought.")
                        .font(NeemaFont.manrope(11)).foregroundColor(c.muted).fixedSize(horizontal: false, vertical: true).padding(.top, 12)
                }
            }
        }
    }

    private func stateWord(_ s: TranslationSetting?) -> String {
        guard let s = s else { return "Loading…" }
        return s.enabled ? "On" : "Off"
    }

    private func spendLine(_ s: TranslationSetting?) -> String {
        guard let s = s else { return " " }
        if s.calls30d > 0 { return "\(settingsMoney(s.spend30dUsd)) over the last 30 days · \(s.calls30d) call\(s.calls30d == 1 ? "" : "s")" }
        return "Nothing spent in the last 30 days"
    }
}

// ── Pipeline stages ───────────────────────────────────────────────────────────

/// The pipeline chips' line colour (the web's #e3cf9b).
private let settingsPipeChipLine = Color(hex: 0xE3CF9B)

struct PipelineStagesCard: View {
    @ObservedObject var model: SettingsScreenModel
    @Environment(\.neema) private var c
    @FocusState private var typing: Bool

    private var vm: SettingsViewModel { model.vm }

    var body: some View {
        let ui = model.ui
        SettingsCard(title: "Pipeline stages",
                     description: "Your own stage labels, shown between Proposal and Won in every lead pipeline. Up to \(PIPELINE_CUSTOM_MAX); the built-in stages stay fixed.") {
            if let list = ui.stages {
                stages(list, ui)
            } else if let why = ui.loadErrors["stages"] {
                CardLoadProblem(why: why, title: "Couldn't load the pipeline stages") { vm.retry("stages") }
            } else {
                Text("Loading…").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
            }
        }
    }

    @ViewBuilder
    private func stages(_ list: [String], _ ui: SettingsUi) -> some View {
        let blank = ui.newStage.trimmingCharacters(in: .whitespaces).isEmpty
        // The order a lead moves through, customs in place.
        Text((CANONICAL_BEFORE + list + ["Won"]).joined(separator: " → ") + " / Lost")
            .font(NeemaFont.manrope(11)).foregroundColor(c.textMid).fixedSize(horizontal: false, vertical: true).padding(.bottom, 10)
        if list.isEmpty {
            Text("No custom stages yet.").font(NeemaFont.manrope(12)).foregroundColor(c.muted).padding(.bottom, 8)
        } else {
            FlowLayout(spacing: 6, lineSpacing: 6) {
                ForEach(Array(list.enumerated()), id: \.offset) { _, s in stageChip(s, saving: ui.savingStages) }
            }
            .padding(.bottom, 8)
        }
        if list.count < PIPELINE_CUSTOM_MAX {
            HStack(alignment: .top, spacing: 6) {
                VStack(alignment: .leading, spacing: 4) {
                    TextField("Stage label (e.g. Sampling)…", text: model.newStage)
                        .font(NeemaFont.manrope(14)).foregroundColor(c.text).submitLabel(.done).onSubmit(add)
                        .focused($typing)
                        .padding(.horizontal, 12).frame(minHeight: 48)
                        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg))
                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(typing ? c.gold : c.border))
                    Text("\(ui.newStage.count)/\(PIPELINE_LABEL_MAX)").font(NeemaFont.manrope(10)).monospacedDigit().foregroundColor(c.muted)
                }
                Button(action: add) {
                    Text("Add").font(NeemaFont.manrope(13, .semibold)).foregroundColor(.white).lineLimit(1)
                        .padding(.horizontal, 16).frame(minHeight: 48)
                        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Palette.pipeGoldSolid))
                        .opacity(blank || ui.savingStages ? 0.5 : 1)
                }
                .buttonStyle(.plain)
                .disabled(blank || ui.savingStages)
            }
        } else {
            Text("That's the most custom stages — remove one to add another.").font(NeemaFont.manrope(11)).foregroundColor(c.muted)
        }
    }

    /// The typed label is cleared only once the server has kept it; a failed save leaves it to retry.
    private func add() {
        let sent = model.ui.newStage
        let v = vm
        v.addStage(sent) { if v.ui.newStage == sent { v.setNewStage("") } }
    }

    private func stageChip(_ s: String, saving: Bool) -> some View {
        HStack(spacing: 0) {
            Text(s).font(NeemaFont.manrope(12)).foregroundColor(c.isDark ? settingsPipeChipLine : Palette.pipeGoldInk).padding(.leading, 8)
            // 32pt drawn, inside a 44pt touch target.
            Button { vm.removeStage(s) } label: {
                Image(systemName: "xmark").font(.system(size: 11, weight: .semibold)).foregroundColor(c.muted)
                    .frame(width: 32, height: 32).frame(width: 44, height: 44).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(saving)
            .accessibilityLabel("Remove \(s)")
        }
        .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(c.isDark ? Palette.pipeGold.opacity(0.15) : Palette.pipeGoldWash))
        .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).stroke(c.isDark ? Palette.pipeGold.opacity(0.4) : settingsPipeChipLine))
    }
}

// ── Business / AI (local-only on the web) ─────────────────────────────────────

struct BusinessCard: View {
    @ObservedObject var model: SettingsScreenModel
    let width: CGFloat

    var body: some View {
        // The web's two-column grid; on a narrow phone or at a large font the fields stack.
        let stack = (width - 40) / teamFontScale < 340
        SettingsCard(title: "Business", description: "Core platform details") {
            SettingsPair(stack: stack) {
                SettingsField(label: "Business Name") { SettingsInput(text: model.biz(\.businessName), placeholder: "Bethany House") }
            } b: {
                SettingsField(label: "Currency") { SettingsInput(text: model.biz(\.currency), placeholder: "KES") }
            }
            SettingsPair(stack: stack) {
                SettingsField(label: "WhatsApp Number") { SettingsInput(text: model.biz(\.waNumber), placeholder: "+254...", keyboard: .phonePad) }
            } b: {
                SettingsField(label: "Timezone") { SettingsInput(text: model.biz(\.timezone), placeholder: "Africa/Nairobi") }
            }
            SettingsPair(stack: stack) {
                SettingsField(label: "Open Hours", hint: "Shown to customers") { SettingsInput(text: model.biz(\.openHours), placeholder: "08:00–18:00") }
            } b: {
                Color.clear.frame(height: 1)
            }
            SettingsSaveButton(label: "Save", saving: model.ui.savingBiz) { model.vm.saveBiz() }
        }
    }
}

struct AiCard: View {
    @ObservedObject var model: SettingsScreenModel
    let width: CGFloat
    @Environment(\.neema) private var c

    var body: some View {
        let stack = (width - 40) / teamFontScale < 340
        SettingsCard(title: "Neema", description: "How Neema handles conversations") {
            SettingsPair(stack: stack) {
                SettingsField(label: "Escalation Threshold", hint: "Messages before escalating") {
                    SettingsInput(text: digits(model.ai(\.autoInterceptThreshold)), keyboard: .numberPad)
                }
            } b: {
                SettingsField(label: "Response Delay (ms)", hint: "Typing simulation") {
                    SettingsInput(text: digits(model.ai(\.responseDelayMs)), keyboard: .numberPad)
                }
            }
            SettingsField(label: "Escalation Keywords", hint: "Comma-separated trigger words") {
                SettingsInput(text: model.ai(\.escalationKeywords), placeholder: "refund, complaint, manager")
            }
            Hairline(color: c.bg3)
            Toggle(isOn: model.ai(\.draftApproval)) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Require draft approval").font(NeemaFont.manrope(13, .medium)).foregroundColor(c.text)
                    Text("Neema's drafts need agent approval before sending").font(NeemaFont.manrope(11)).foregroundColor(c.muted)
                }
                .padding(.trailing, 8)
            }
            .tint(c.gold)
            .padding(.vertical, 10)
            .frame(minHeight: 48)
            Hairline(color: c.bg3)
            Spacer().frame(height: 12)
            SettingsSaveButton(label: "Save Neema settings", saving: model.ui.savingAi) { model.vm.saveAi() }
        }
    }

    /// Only digits reach the model (the web's number inputs).
    private func digits(_ b: Binding<String>) -> Binding<String> {
        Binding(get: { b.wrappedValue }, set: { v in b.wrappedValue = v.filter { $0.isASCII && $0.isNumber } })
    }
}

// ── Integrations ──────────────────────────────────────────────────────────────

/// A platform's 36pt tile: its brand colour (Instagram's gradient) and a glyph, or the M-PESA wordmark.
struct IntegrationTile: View {
    let key: String

    private var fill: AnyShapeStyle {
        switch key {
        case "whatsapp": return AnyShapeStyle(ChannelColors.whatsApp)
        case "messenger": return AnyShapeStyle(Color(hex: 0x0099FF))
        case "instagram":
            return AnyShapeStyle(LinearGradient(colors: [Color(hex: 0xFEDA75), Color(hex: 0xFA7E1E), Color(hex: 0xD62976), Color(hex: 0x962FBF), Color(hex: 0x4F5BD5)],
                                                startPoint: .topLeading, endPoint: .bottomTrailing))
        case "mpesa": return AnyShapeStyle(Palette.mpesaGreen)
        case "email": return AnyShapeStyle(Palette.indigo500)
        case "slack": return AnyShapeStyle(Palette.slackAubergine)
        default: return AnyShapeStyle(Palette.sheetsGreen)
        }
    }

    private var symbol: String {
        switch key {
        case "whatsapp": return "bubble.left"
        case "messenger": return "bubble.left.and.bubble.right"
        case "instagram": return "camera"
        case "email": return "envelope"
        case "slack": return "number"
        default: return "tablecells"
        }
    }

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12, style: .continuous).fill(fill)
            if key == "mpesa" {
                // A logo, not text: it keeps its size inside the 36pt tile at any font scale.
                Text("M-PESA").font(.system(size: 7, weight: .bold)).foregroundColor(.white).lineLimit(1)
            } else {
                Image(systemName: symbol).font(.system(size: 18, weight: .medium)).foregroundColor(.white)
            }
        }
        .frame(width: 36, height: 36)
        .accessibilityHidden(true)
    }
}

struct IntegrationsCard: View {
    @ObservedObject var model: SettingsScreenModel
    let twoCols: Bool
    let width: CGFloat
    @Binding var expanded: String
    @Environment(\.neema) private var c

    var body: some View {
        SettingsCard(title: "Integrations", description: "Connected platforms and services") {
            VStack(spacing: 6) {
                ForEach(model.ui.integrations) { integ in row(integ) }
            }
        }
    }

    private func row(_ integ: Integration) -> some View {
        let isExpanded = expanded == integ.key
        // Too narrow for name and buttons abreast (a phone at a large font): the buttons go under the name.
        let stacked = (width - 40) / teamFontScale < 330
        return VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                IntegrationTile(key: integ.key)
                VStack(alignment: .leading, spacing: 2) {
                    Text(integ.name).font(NeemaFont.manrope(13, .semibold)).foregroundColor(c.text).lineLimit(2)
                    HStack(spacing: 5) {
                        Circle().fill(integ.connected ? c.gold : Palette.stone300).frame(width: 6, height: 6)
                        Text(integ.connected ? "Connected" : "Not connected").font(NeemaFont.manrope(11, .medium))
                            .foregroundColor(integ.connected ? c.gold : c.muted).lineLimit(1)
                        Text("· \(integ.description)").font(NeemaFont.manrope(11)).foregroundColor(c.muted).lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if !stacked {
                    HStack(spacing: 6) { actions(integ, isExpanded) }
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 10)
            if stacked {
                FlowLayout(spacing: 6, lineSpacing: 6) { actions(integ, isExpanded) }
                    .padding(.leading, 60).padding(.trailing, 12).padding(.bottom, 10)
            }
            if isExpanded {
                Hairline(color: c.bg3)
                configForm(integ)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.isDark ? c.hairline : c.bg3))
    }

    @ViewBuilder
    private func actions(_ integ: Integration, _ isExpanded: Bool) -> some View {
        if !integ.fields.isEmpty {
            SettingsPillButton(text: isExpanded ? "Close" : "Configure", fg: c.gold, bg: isExpanded ? c.bg3 : c.bg2, border: c.border) {
                expanded = isExpanded ? "" : integ.key
            }
        }
        if integ.connected {
            SettingsPillButton(text: "Disconnect", fg: c.red, bg: c.isDark ? c.redDim : Palette.dangerWash,
                               border: c.isDark ? c.red.opacity(0.3) : Palette.red200) { model.vm.toggleIntegration(integ.key) }
        } else {
            SettingsPillButton(text: "Connect", fg: c.gold, bg: c.goldDim, border: c.border) { model.vm.toggleIntegration(integ.key) }
        }
    }

    private func configForm(_ integ: Integration) -> some View {
        // (perRow is 2 only on the two-column layout, where the card is wide enough.)
        let perRow = twoCols ? 2 : 1
        let fields = integ.fields
        let rows = stride(from: 0, to: fields.count, by: perRow).map { Array(fields[$0..<min($0 + perRow, fields.count)]) }
        return VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .top, spacing: 12) {
                    ForEach(row) { f in
                        SettingsField(label: f.label) {
                            SettingsInput(text: model.config(integ.key, f.key), placeholder: f.placeholder, secret: f.secret)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    if row.count < perRow { Color.clear.frame(maxWidth: .infinity, maxHeight: 1) }
                }
            }
            TeamBtn(label: "Save Configuration", variant: .primary, small: true) {
                model.vm.saveIntegConfig(integ.key)
                expanded = ""
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(c.bg)
    }
}

// ── Danger zone ───────────────────────────────────────────────────────────────

struct DangerZoneCard: View {
    let onAction: () -> Void
    @Environment(\.neema) private var c

    private let rows: [(label: String, sub: String, action: String)] = [
        ("Clear conversation history", "Permanently delete messages older than 90 days", "Clear"),
        ("Reset Neema's memory", "Clear all customer facts and session history", "Reset"),
    ]

    var body: some View {
        let light = !c.isDark
        let rowFill = light ? Palette.red50 : c.redDim
        let rowEdge = light ? Palette.red100 : c.red.opacity(0.2)
        let labelColor = light ? Palette.red800 : c.red
        let subColor = light ? Palette.red500 : c.red.opacity(0.75)
        let btnFill = light ? Palette.red100 : c.red.opacity(0.12)
        let btnText = light ? Palette.red700 : c.red
        let btnEdge = light ? Palette.red200 : c.red.opacity(0.3)
        SettingsCard(title: "Danger Zone", description: "Irreversible actions. Proceed with caution.") {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                HStack(alignment: .center, spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.label).font(NeemaFont.manrope(12, .medium)).foregroundColor(labelColor)
                        Text(r.sub).font(NeemaFont.manrope(11)).foregroundColor(subColor).fixedSize(horizontal: false, vertical: true)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    SettingsPillButton(text: r.action, fg: btnText, bg: btnFill, border: btnEdge, action: onAction)
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(rowFill))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(rowEdge))
                .padding(.bottom, 8)
            }
        }
    }
}
