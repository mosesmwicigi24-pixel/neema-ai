import SwiftUI
import NeemaCore

// ── Metadata (the web's STAGE_META / TIER_META / CH_META), Android `CustomerWidgets.kt` ──

struct StageMeta {
    let label: String
    let color: Color
    let dot: Color
}

private let STAGE_META: [String: StageMeta] = [
    "new": StageMeta(label: "New", color: Palette.stone500, dot: Palette.stone400),
    "contacted": StageMeta(label: "Contacted", color: Palette.blue600, dot: Palette.blue500),
    "qualified": StageMeta(label: "Qualified", color: Palette.violet600, dot: Palette.violet500),
    "proposal": StageMeta(label: "Proposal", color: Palette.amber600, dot: Palette.amber500),
    "negotiation": StageMeta(label: "Negotiating", color: Palette.orange600, dot: Palette.orange500),
    "won": StageMeta(label: "Won ✓", color: Palette.emerald700, dot: Palette.emerald500),
    "lost": StageMeta(label: "Lost", color: Palette.red500, dot: Palette.red400),
]

/// A custom (operator-added) stage shows its own label in the pipeline's gold, not "New".
func stageMeta(_ stage: String) -> StageMeta {
    STAGE_META[stage] ?? StageMeta(label: CustomerWords.stageLabel(stage), color: PIPE_GOLD_SOLID, dot: PIPE_GOLD)
}

/// `bg` is the web's light Tailwind fill (amber-100, emerald-100, …); dark mode tints `color` instead.
struct TierLook {
    let color: Color
    let border: Color
    let bg: Color
}

let TIER_LOOK: [String: TierLook] = [
    "vip": TierLook(color: Palette.amber800, border: Palette.amber300, bg: Palette.amber100),
    "loyal": TierLook(color: Palette.emerald700, border: Palette.emerald300, bg: Palette.emerald100),
    "regular": TierLook(color: Palette.sky700, border: Palette.sky300, bg: Palette.sky100),
    "new": TierLook(color: Palette.stone600, border: Palette.stone300, bg: Palette.stone100),
    "prospect": TierLook(color: Palette.stone400, border: Palette.stone200, bg: Palette.stone50),
    "at_risk": TierLook(color: Palette.red700, border: Palette.red300, bg: Palette.red100),
]

/// Channel brand colour for the linked-identities list (CH_META).
func chColor(_ channel: String) -> Color { Color(hex: ChannelMeta.colorHex(channel)) }

// Goldenrod stepper palette (sampled by the web from its reference design).
let PIPE_GOLD = Palette.pipeGold
let PIPE_GOLD_SOLID = Palette.pipeGoldSolid
private let PIPE_IDLE = Palette.stone200
private let PIPE_IDLE_TEXT = Palette.stone400
private let PIPE_LOST = Palette.pipeLost
private let PIPE_LOST_ICON = Palette.pipeLostIcon
private let PIPE_LOST_TEXT = Palette.pipeLostText
private let LOST_RED = Palette.red500
let WA_GREEN = ChannelColors.whatsApp

extension Color {
    func dim(_ a: Double = 0.12) -> Color { opacity(a) }
    /// The web's Tailwind tints are tuned for white; on the Prussian-blue night they're lifted toward white to stay legible.
    func themed(_ dark: Bool) -> Color { dark ? lifted(0.45) : self }
}

// ── Small building blocks ───────────────────────────────────────────────────

/// A coloured circle standing in for the channel's logo (CHANNEL_ICON_SVG backgrounds).
struct ChannelBadge: View {
    let channel: String
    var size: CGFloat = 20

    var body: some View {
        ZStack {
            if channel == "instagram" {
                Circle().fill(LinearGradient(colors: [Color(hex: 0xF9CE34), Color(hex: 0xEE2A7B), Color(hex: 0x6228D7)], startPoint: .topLeading, endPoint: .bottomTrailing))
            } else {
                Circle().fill(fill)
            }
            if channel == "web" {
                // A website visitor: a globe, never WhatsApp's mark.
                Image(systemName: "globe").font(.system(size: size * 0.55, weight: .semibold)).foregroundColor(.white)
            } else {
                Text(glyph).font(NeemaFont.fixed(size * 0.5, .bold)).foregroundColor(.white)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    private var fill: Color {
        switch channel {
        case "whatsapp": return WA_GREEN
        case "messenger": return Palette.messengerSky
        case "facebook": return ChannelColors.facebook
        case "email": return Palette.indigo500
        case "web": return Palette.slate500
        default: return Palette.moss800
        }
    }

    private var glyph: String {
        switch channel {
        case "whatsapp": return "W"
        case "messenger": return "m"
        case "facebook": return "f"
        case "instagram": return "◎"
        case "email": return "@"
        case "tiktok": return "♪"
        default: return "…"
        }
    }
}

/// A titled block in the tab body (the web's <Section>).
struct CrmSection<Content: View, Action: View>: View {
    let title: String
    @ViewBuilder let action: () -> Action
    @ViewBuilder let content: () -> Content
    @Environment(\.neema) private var c

    init(_ title: String, @ViewBuilder action: @escaping () -> Action, @ViewBuilder content: @escaping () -> Content) {
        self.title = title; self.action = action; self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(title.uppercased()).font(NeemaFont.manrope(10, .bold)).tracking(1.2).foregroundColor(c.textMid)
                Spacer()
                action()
            }
            .padding(.bottom, 8)
            content()
        }
        .padding(.bottom, 20)
    }
}

extension CrmSection where Action == EmptyView {
    init(_ title: String, @ViewBuilder content: @escaping () -> Content) {
        self.init(title, action: { EmptyView() }, content: content)
    }
}

struct CrmHairline: View {
    @Environment(\.neema) private var c
    var body: some View { Rectangle().fill(c.hairline).frame(height: 1) }
}

/// Label + value row in the Insights tab.
struct KvRow: View {
    let label: String
    let value: String
    @Environment(\.neema) private var c
    var body: some View {
        HStack {
            Text(label).font(NeemaFont.manrope(12)).foregroundColor(c.textMid)
            Spacer()
            Text(value).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
        }
        .padding(.vertical, 3)
    }
}

/// Read-only row in Contact Details (Source, Came via, Parish).
struct InfoRow: View {
    let label: String
    let value: String
    var hint: String? = nil
    @Environment(\.neema) private var c
    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top) {
                Text(label).font(NeemaFont.manrope(10)).foregroundColor(c.muted).frame(width: 80, alignment: .leading).padding(.top, 1)
                Spacer()
                Text(value).font(NeemaFont.manrope(11)).foregroundColor(c.text).multilineTextAlignment(.trailing)
            }
            .padding(.vertical, 6)
            .accessibilityElement(children: .combine)
            .accessibilityHint(hint ?? "")
            CrmHairline()
        }
    }
}

/// The panel's small input: the theme's surface on its border, Manrope 12.
struct SmallInput: View {
    @Binding var value: String
    let placeholder: String
    var keyboard: UIKeyboardType = .default
    var lines: ClosedRange<Int> = 1...1
    var fontSize: CGFloat = 12
    var onDone: (() -> Void)? = nil
    var focused: FocusState<Bool>.Binding? = nil
    @Environment(\.neema) private var c

    var body: some View {
        let field = TextField(placeholder, text: $value, axis: lines.upperBound > 1 ? .vertical : .horizontal)
            .lineLimit(lines)
            .font(NeemaFont.manrope(fontSize)).foregroundColor(c.text).tint(c.gold)
            .keyboardType(keyboard)
            .textInputAutocapitalization(keyboard == .emailAddress ? .never : .sentences)
            .submitLabel(lines.upperBound > 1 ? .return : .done)
            .onSubmit { onDone?() }
            .padding(.horizontal, 10).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg2))
            .roundedBorder(c.border, radius: 8)
        if let f = focused { field.focused(f) } else { field }
    }
}

/// Tap to edit, ✓ / Done saves, ✕ cancels (the web's EditableField). Read-only when `enabled` is false.
struct EditableField: View {
    let label: String
    let value: String
    let onSave: (String) -> Void
    let placeholder: String
    let enabled: Bool
    var keyboard: UIKeyboardType = .default
    /// Text of a save that did not land: the editor reopens with it (then `onRestored` takes it).
    var restore: String? = nil
    var onRestored: () -> Void = {}
    @Environment(\.neema) private var c
    @State private var editing = false
    // Seeded when the edit starts, never re-keyed on `value`: a live reload that
    // brings a new value mid-edit must not wipe what the agent is typing.
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 4) {
                Text(label).font(NeemaFont.manrope(10)).foregroundColor(c.textMid).frame(width: 64, alignment: .leading)
                if editing {
                    SmallInput(value: $draft, placeholder: placeholder, keyboard: keyboard, onDone: commit, focused: $focused)
                    Button(action: commit) { Image(systemName: "checkmark").font(.system(size: 14, weight: .semibold)).foregroundColor(Palette.emerald600).frame(width: 32, height: 32) }
                        .accessibilityLabel("Save")
                    Button { draft = value; editing = false } label: { Image(systemName: "xmark").font(.system(size: 14, weight: .semibold)).foregroundColor(c.muted).frame(width: 32, height: 32) }
                        .accessibilityLabel("Cancel")
                } else {
                    Button {
                        if enabled { draft = value; editing = true; focused = true }
                    } label: {
                        Group {
                            if !value.isEmpty {
                                Text(value).font(NeemaFont.manrope(12)).foregroundColor(c.text).lineLimit(1)
                            } else {
                                Text(placeholder.isEmpty ? "—" : placeholder).font(NeemaFont.manrope(12)).italic().foregroundColor(c.muted.opacity(0.6)).lineLimit(1)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 6).padding(.horizontal, 2)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(!enabled)
                    .accessibilityLabel("\(label): \(value.isEmpty ? "empty" : value)")
                    .accessibilityHint(enabled ? "Tap to edit" : "")
                }
            }
            .frame(minHeight: 32)
            .padding(.vertical, 4)
            CrmHairline()
        }
        .onChange(of: restore) { _, r in
            if let r = r { draft = r; editing = true; focused = true; onRestored() }
        }
        .onAppear { if let r = restore { draft = r; editing = true; onRestored() } }
    }

    private func commit() { onSave(draft); editing = false }
}

struct ScoreBar: View {
    let score: Int
    @Environment(\.neema) private var c
    var body: some View {
        let color: Color = score >= 70 ? Palette.emerald500 : score >= 40 ? Palette.amber500 : Palette.stone300
        HStack(spacing: 0) {
            ProgressBar(fraction: Double(score) / 100, color: color).frame(height: 6)
            Text(String(score)).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.textMid).frame(width: 28, alignment: .trailing)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Lead score \(score) of 100")
    }
}

struct ProgressBar: View {
    let fraction: Double
    let color: Color
    @Environment(\.neema) private var c
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(c.hairline)
                Capsule().fill(color).frame(width: g.size.width * min(1, max(0, fraction)))
            }
        }
    }
}

/// Filled small action button with the web's tints.
struct TintButton: View {
    let text: String
    let color: Color
    var filled: Bool = false
    var enabled: Bool = true
    var height: CGFloat = 32
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            // Grows (and wraps) with the font scale rather than clipping the label.
            Text(text).font(NeemaFont.manrope(11, .semibold)).foregroundColor(filled ? .white : color).lineLimit(2).multilineTextAlignment(.center)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .frame(maxWidth: .infinity, minHeight: height)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(filled ? (enabled ? color : color.opacity(0.55)) : color.dim(0.1)))
                .overlay(Group { if !filled { RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(color.dim(0.35)) } })
                .opacity(enabled || filled ? 1 : 0.55)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

/// The web's quiet outline button (#f8fafc fill, #b5da8b border, slate text): Advance Stage, add-tag "+".
struct NeutralButton: View {
    let text: String
    var height: CGFloat = 32
    var textColor: Color? = nil
    var enabled: Bool = true
    var fill: Bool = true
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: action) {
            Text(text).font(NeemaFont.manrope(11, .semibold)).foregroundColor(textColor ?? c.text).lineLimit(2).multilineTextAlignment(.center)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .frame(maxWidth: fill ? .infinity : nil, minHeight: height)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.surface))
                .roundedBorder(c.border, radius: 8)
                .opacity(enabled ? 1 : 0.55)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

/// A single-line input + action, with a result bubble underneath (Ask Neema / Answer via Neema).
struct NeemaBox: View {
    let placeholder: String
    let actionLabel: String
    let busy: Bool
    let result: String?
    /// Held by the view model: a failure, a tab switch or a reload never loses it.
    @Binding var text: String
    let onSubmit: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                SmallInput(value: $text, placeholder: placeholder, onDone: { if !busy && !text.trimmingCharacters(in: .whitespaces).isEmpty { onSubmit() } })
                TintButton(text: busy ? "…" : actionLabel, color: c.gold, filled: true, enabled: !busy && !text.trimmingCharacters(in: .whitespaces).isEmpty, action: onSubmit)
                    .fixedSize(horizontal: true, vertical: false)
            }
            if let r = result {
                Text(r).font(NeemaFont.manrope(12)).foregroundColor(c.text)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.surface))
                    .roundedBorder(c.hairline, radius: 8)
                    .textSelection(.enabled)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .roundedBorder(c.hairline, radius: 12)
        .padding(.bottom, 16)
    }
}

// ── Lead-pipeline stepper ───────────────────────────────────────────────────

private enum StepState { case active, done, future }

private func stepState(_ stage: String, _ active: String, _ forward: [String]) -> StepState {
    if stage == active { return .active }
    if stage == "lost" { return .future } // Lost is only ever active when current
    if active == "lost" { return stage == "won" ? .future : .done }
    guard let a = forward.firstIndex(of: active), let s = forward.firstIndex(of: stage) else { return .future }
    return s < a ? .done : .future
}

/// New → Contacted → Qualified → Proposal → (custom…) → Won, with Lost as a
/// faded terminal branch — fixed 24 pt nodes, flexible gold connectors between
/// them, each label centred under its node. Tapping a node sets the stage. Only
/// when a narrow pane can't give every node ~38 pt does it scroll sideways.
struct PipelineStepper: View {
    let stages: [String]
    let forward: [String]
    let active: String
    let enabled: Bool
    let onSelect: (String) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        GeometryReader { g in
            let needed = CGFloat(38 * stages.count + 16)
            let fits = g.size.width >= needed
            let slot = (fits ? (g.size.width - 16) / CGFloat(stages.count) : 38) - 3
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 0) {
                    ForEach(Array(stages.enumerated()), id: \.element) { i, stage in
                        let state = stepState(stage, active, forward)
                        let isLost = stage == "lost"
                        let reached = state == .done || state == .active
                        if i > 0 {
                            // The segment into this node takes this node's colour, as on the web.
                            let conn: Color = isLost ? PIPE_LOST : reached ? PIPE_GOLD : (c.isDark ? c.border2 : PIPE_IDLE)
                            Capsule().fill(conn).frame(height: 2).frame(maxWidth: .infinity)
                        }
                        node(stage: stage, state: state, isLost: isLost, reached: reached, slot: slot)
                    }
                }
                .padding(.horizontal, 8)
                .frame(width: fits ? g.size.width : needed)
            }
        }
        .frame(height: 58)
    }

    private func node(stage: String, state: StepState, isLost: Bool, reached: Bool, slot: CGFloat) -> some View {
        let (fill, border, icon): (Color, Color, Color) = {
            if state == .active && isLost { return (LOST_RED, LOST_RED, .white) }
            if state == .active { return (PIPE_GOLD_SOLID, PIPE_GOLD_SOLID, .white) }
            if state == .done { return (c.bg2, PIPE_GOLD, PIPE_GOLD) }
            if isLost { return (c.bg2, PIPE_LOST, PIPE_LOST_ICON) }
            return (c.bg2, c.isDark ? c.border2 : PIPE_IDLE, .clear)
        }()
        let labelColor: Color = state == .active ? (isLost ? LOST_RED : PIPE_GOLD_SOLID) : state == .done ? PIPE_GOLD : isLost ? PIPE_LOST_TEXT : PIPE_IDLE_TEXT
        let showCheck = reached && !isLost
        let showX = isLost && (state == .active || state == .future)
        return Button { if enabled { onSelect(stage) } } label: {
            VStack(spacing: 3) {
                ZStack {
                    Circle().fill(fill)
                    Circle().stroke(border, lineWidth: 2)
                    if showCheck { Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundColor(icon) }
                    if showX { Image(systemName: "xmark").font(.system(size: 11, weight: .bold)).foregroundColor(icon) }
                }
                .frame(width: 24, height: 24)
                // The label hangs under the node and may be wider than it; a long label in a crowded row steps down rather than running into its neighbour.
                Text(CustomerWords.stageLabel(stage)).font(NeemaFont.fixed(9, state == .active ? .bold : .semibold)).foregroundColor(labelColor)
                    .lineLimit(1).minimumScaleFactor(0.75)
                    .frame(width: max(slot, 24))
                    .fixedSize(horizontal: true, vertical: false)
            }
            .frame(width: 24)
            .contentShape(Rectangle().size(width: 40, height: 48))
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(CustomerWords.stageLabel(stage))
        .accessibilityAddTraits(state == .active ? .isSelected : [])
    }
}
