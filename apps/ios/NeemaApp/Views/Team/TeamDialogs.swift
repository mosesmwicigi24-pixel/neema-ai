import SwiftUI
import NeemaCore

// The Team screen's form pieces (Android `TeamUi.kt`): the button variants
// AgentsView.tsx / ProfileView.tsx use, labelled inputs, the select, the
// web's Modal as a sheet, the permission picker, and the role chips.

/// SBtn variants from AgentsView.tsx (primary / danger / ghost / default),
/// plus the shared Btn variants ProfileView.tsx uses: amber (Btn "primary",
/// bg-amber-500), secondary (white, gray-700 text, gray-200 border) and
/// outline (transparent, gray-700 text, gray-300 border).
enum TeamBtnVariant { case primary, danger, ghost, standard, amber, secondary, outline }

/// (fill, content, border) for `variant` on the current theme (Android `btnColors`).
func teamBtnColors(_ variant: TeamBtnVariant, _ c: NeemaColors) -> (bg: Color, fg: Color, bd: Color) {
    switch variant {
    // By night the moss brightens (#84c13e): white on it is 2:1, so the theme's deep surface instead.
    case .primary: return (c.gold, onGold(c), c.gold2)
    // SBtn danger by day: #fff5f5 fill, #c0392b text, #fecaca border.
    case .danger: return c.isDark ? (c.red.opacity(0.12), c.red, c.red.opacity(0.3)) : (Palette.dangerWash, c.red, Palette.red200)
    case .ghost: return (.clear, c.textDim, c.border)
    case .standard: return (c.bg2, c.gold2, c.border)
    // White on amber-500 is 2.1:1; the brand navy on it reads at 7:1.
    case .amber: return (Brand.amber, Brand.navy, Brand.amber)
    case .secondary: return (c.bg2, c.text, c.hairline)
    case .outline: return (.clear, c.text, c.isDark ? c.border : Palette.gray300)
    }
}

/// Text and icons on a gold fill: white by day, the theme's deep surface by night.
func onGold(_ c: NeemaColors) -> Color { c.isDark ? c.bg : .white }

/// The web's pale greens (#9ccd65, #b5da8b) read at under 2:1 on a white card;
/// the theme's secondary green and muted grey-green keep the same quiet tone
/// at a readable contrast, by day and by night.
func teamFaint(_ c: NeemaColors) -> Color { c.isDark ? c.muted : c.textDim }

/// Card borders: #cee6b2 by day, the theme hairline by night.
func teamCardBorder(_ c: NeemaColors) -> Color { c.isDark ? c.hairline : c.bg4 }

/// "#589b31" → the colour; anything unparseable reads as the brand green.
func hexColor(_ hex: String?) -> Color { Color(hex: TeamColors.rgb(hex) ?? 0x589B31) }

/// Whichever of white or the brand ink reads on a role's colour (NeemaCore's 3:1 rule).
func roleInk(_ hex: String?) -> Color { TeamColors.contentOn(hex: hex) == .white ? .white : Palette.ink }

/// "admin" → "Admin" (Kotlin's `replaceFirstChar { it.uppercase() }`).
func capitalizeFirst(_ s: String) -> String { s.prefix(1).uppercased() + s.dropFirst() }

/// The dynamic-type scale, as Android's `fontScale`.
var teamFontScale: CGFloat { UIFontMetrics.default.scaledValue(for: 100) / 100 }

/// A view's width, measured for the layouts that pick their column count from it.
struct WidthKey: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

extension View {
    /// Reports this view's laid-out width into `width`.
    func measureWidth(_ width: Binding<CGFloat>) -> some View {
        background(GeometryReader { g in Color.clear.preference(key: WidthKey.self, value: g.size.width) })
            .onPreferenceChange(WidthKey.self) { w in if w > 0 && w != width.wrappedValue { width.wrappedValue = w } }
    }
}

// ── Buttons ──────────────────────────────────────────────────────────────────

/// AgentsView's SBtn / the shared Btn (Android `TeamButton`): 8pt corners, semibold, a hairline in the variant's colour.
struct TeamBtn: View {
    let label: String
    var variant: TeamBtnVariant = .standard
    var small: Bool = false
    var enabled: Bool = true
    /// An SF Symbol before the label.
    var lead: String? = nil
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let col = teamBtnColors(variant, c)
        Button(action: action) {
            HStack(spacing: 5) {
                if let l = lead { Image(systemName: l).font(.system(size: small ? 12 : 14, weight: .semibold)) }
                Text(label).font(NeemaFont.manrope(small ? 12 : 13, .semibold)).lineLimit(1)
            }
            .foregroundColor(col.fg)
            .padding(.horizontal, small ? 10 : 14).padding(.vertical, small ? 4 : 8)
            // Small buttons sit in a row with 34pt icon buttons (the card footers); a large font may grow them.
            .frame(minHeight: small ? 34 : 40)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(col.bg))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(col.bd))
            .opacity(enabled ? 1 : 0.5)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

/// A 34pt icon button (the card footers' key and trash), drawn inside a 44pt touch target.
struct TeamIconBtn: View {
    let icon: String
    let label: String
    var variant: TeamBtnVariant = .ghost
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let col = teamBtnColors(variant, c)
        // Growing a little with a large font to keep level with the text buttons.
        let grow = min(1.4, max(1, 1 + (teamFontScale - 1) * 0.4))
        Button(action: action) {
            Image(systemName: icon).font(.system(size: 15 * grow, weight: .medium)).foregroundColor(col.fg)
                .frame(width: 34 * grow, height: 34 * grow)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(col.bg))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(col.bd))
                .frame(width: 44 * grow, height: 44 * grow)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// A small text-only button ("Select all", "Deselect").
struct TextLink: View {
    let label: String
    var size: CGFloat = 12
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: action) {
            Text(label).font(NeemaFont.manrope(size, .semibold)).foregroundColor(c.gold)
                .padding(.horizontal, 8).frame(minHeight: 40)
        }
        .buttonStyle(.plain)
    }
}

// ── Fields ───────────────────────────────────────────────────────────────────

/// Which web input a `LabeledInput` reproduces: `team` is AgentsView's
/// SmallInput (green label, #f3f9ec fill, #b5da8b border); `form` is the
/// shared InputField ProfileView uses (UPPERCASE tracked grey label, grey-50
/// fill, grey-200 border).
enum InputStyle { case team, form }

/// SmallInput / InputField: a labelled single-line field (Android `LabeledInput`).
struct LabeledInput: View {
    let label: String?
    @Binding var text: String
    var placeholder: String? = nil
    var password: Bool = false
    var keyboard: UIKeyboardType = .default
    var capitalization: TextInputAutocapitalization = .sentences
    var contentType: UITextContentType? = nil
    var isError: Bool = false
    var supporting: String? = nil
    var style: InputStyle = .team
    /// Next moves to the following field; the form's last field says Done and closes the keyboard.
    var submit: SubmitLabel = .next
    @Environment(\.neema) private var c
    @FocusState private var focused: Bool

    var body: some View {
        let form = style == .form
        let noAuto = password || keyboard == .emailAddress
        let edge: Color = isError ? c.red : focused ? (form ? Brand.amber : c.gold) : (form ? c.hairline : c.border)
        VStack(alignment: .leading, spacing: 6) {
            if let l = label {
                if form {
                    Text(l.uppercased()).font(NeemaFont.manrope(12, .medium)).tracking(0.6).foregroundColor(c.muted)
                } else {
                    Text(l).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.textDim)
                }
            }
            Group {
                if password {
                    SecureField(placeholder ?? "", text: $text)
                } else {
                    TextField(placeholder ?? "", text: $text)
                }
            }
            .font(NeemaFont.manrope(14)).foregroundColor(c.text)
            .keyboardType(password ? .default : keyboard)
            .textInputAutocapitalization(noAuto ? .never : capitalization)
            .autocorrectionDisabled(noAuto)
            .textContentType(contentType)
            .submitLabel(submit)
            .focused($focused)
            .padding(.horizontal, 12).frame(minHeight: 48)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(form ? c.surface : c.bg))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(edge, lineWidth: focused || isError ? 1.5 : 1))
            if let s = supporting {
                Text(s).font(NeemaFont.manrope(11)).foregroundColor(isError ? c.red : c.textDim)
            }
        }
        .padding(.bottom, form ? 12 : 10)
    }
}

struct SelectOption: Identifiable, Equatable {
    let id: String
    let text: String
    init(_ id: String, _ text: String) { self.id = id; self.text = text }
}

/// A native-select look-alike: a field that opens a menu (Android `SelectField`).
struct SelectField: View {
    let label: String?
    let options: [SelectOption]
    @Binding var selected: String
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let l = label { Text(l).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.textDim) }
            Menu {
                ForEach(options) { o in
                    Button { selected = o.id } label: {
                        if o.id == selected { Label(o.text, systemImage: "checkmark") } else { Text(o.text) }
                    }
                }
            } label: {
                HStack(spacing: 8) {
                    Text(options.first { $0.id == selected }?.text ?? selected).font(NeemaFont.manrope(14)).foregroundColor(c.text).lineLimit(2)
                    Spacer(minLength: 4)
                    Image(systemName: "chevron.down").font(.system(size: 12, weight: .semibold)).foregroundColor(c.textDim)
                }
                .padding(.horizontal, 12).frame(minHeight: 48)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg))
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.border))
                .contentShape(Rectangle())
            }
            .accessibilityLabel(label ?? "Select")
            .accessibilityValue(options.first { $0.id == selected }?.text ?? selected)
        }
        .padding(.bottom, 10)
    }
}

// ── The modal ────────────────────────────────────────────────────────────────

/// The web's Modal as a sheet (Android `FormDialog`): a titled card with a
/// scrolling body and a button row. The title and the buttons stay while the
/// body scrolls above the keyboard, and the buttons wrap onto a second line
/// rather than squeeze at a large font.
struct FormSheet<Content: View, Buttons: View>: View {
    let title: String
    /// The pickers' sheets open at full height; a short form starts at half.
    var tall: Bool = false
    @ViewBuilder let buttons: () -> Buttons
    @ViewBuilder let content: () -> Content
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title).font(NeemaFont.manrope(16, .semibold)).foregroundColor(c.text).lineLimit(2)
                .padding(.horizontal, 20).padding(.top, 20).padding(.bottom, 14)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) { content() }
                    .padding(.horizontal, 20).padding(.bottom, 8)
            }
            Hairline(color: c.isDark ? c.hairline : c.bg3)
            FlowLayout(spacing: 8, lineSpacing: 8) { buttons() }
                .padding(.horizontal, 20).padding(.vertical, 14)
        }
        .frame(maxWidth: 560)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.bg2.ignoresSafeArea())
        .presentationDetents(tall ? [.large] : [.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

// ── Role chips ───────────────────────────────────────────────────────────────

/// A role's initial on a square of its colour (40pt on the role list, 32pt in the assign dialog).
struct RoleSquare: View {
    let role: CustomRole
    let size: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: size >= 40 ? 12 : 8, style: .continuous).fill(hexColor(role.color))
            .frame(width: size, height: size)
            .overlay(Text(role.name.isEmpty ? "?" : String(role.name.prefix(1)).uppercased())
                .font(NeemaFont.fixed(14, .bold)).foregroundColor(roleInk(role.color)))
            .accessibilityHidden(true)
    }
}

/// The agent card's role chip: 11pt semibold on a full pill (a custom role's colour, or the base role's pale green).
struct RoleBadge: View {
    let text: String
    let fill: Color
    let content: Color

    var body: some View {
        Text(text).font(NeemaFont.manrope(11, .semibold)).foregroundColor(content).lineLimit(1)
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(Capsule().fill(fill))
    }
}

/// Rounded status pill (Android `Pill`): `color` drives both text and tint.
struct TeamPill: View {
    let text: String
    let color: Color
    var filled: Bool = false

    var body: some View {
        Text(text).font(NeemaFont.manrope(11, .semibold)).lineLimit(1)
            .foregroundColor(filled ? contentOn(color) : color)
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(Capsule().fill(filled ? color : color.opacity(0.13)))
    }
}

/// A role's permission on the role list: 10pt medium, green on the gold wash.
struct PermChip: View {
    let label: String
    @Environment(\.neema) private var c

    var body: some View {
        Text(label).font(NeemaFont.manrope(10, .medium)).foregroundColor(c.gold2).lineLimit(1)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4).fill(c.goldDim))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(c.border))
    }
}

/// The role list's tag is an uppercase, tracked, bold pill; the assign
/// dialog's (`compact`) is "Protected" as typed, semibold, on a 4pt-cornered chip.
struct ProtectedTag: View {
    var compact: Bool = false
    @Environment(\.neema) private var c

    var body: some View {
        let fill = c.isDark ? c.goldDim : c.bg3
        if compact {
            Text("Protected").font(NeemaFont.manrope(9, .semibold)).foregroundColor(c.gold2)
                .padding(.horizontal, 4).padding(.vertical, 2)
                .background(RoundedRectangle(cornerRadius: 4).fill(fill))
        } else {
            Text("PROTECTED").font(NeemaFont.manrope(9, .bold)).tracking(0.8).foregroundColor(c.gold2)
                .padding(.horizontal, 6).padding(.vertical, 2)
                .background(Capsule().fill(fill))
        }
    }
}

// ── Permission picker ────────────────────────────────────────────────────────

/// The role editor's permission block: select/deselect all, per-group
/// toggles, a two-column checkbox grid, and the "n of N selected" line.
/// Also used for a single agent's permission override.
struct PermissionPicker: View {
    let selected: [String]
    let onChange: ([String]) -> Void
    @Environment(\.neema) private var c
    @State private var width: CGFloat = 320

    private var all: [String] { PermissionCatalog.ALL.map { $0.key } }

    var body: some View {
        let hasAll = all.allSatisfy { selected.contains($0) }
        // Two columns as on the web, unless each would hold under ~110pt of text (a large font on a phone).
        let perRow = ((width - 6) / 2) / teamFontScale < 110 ? 1 : 2
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text("Permissions").font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.textDim)
                Spacer(minLength: 4)
                TextLink(label: hasAll ? "Deselect all" : "Select all", size: 12) { onChange(hasAll ? [] : all) }
            }
            ForEach(PermissionCatalog.GROUPS, id: \.self) { group in
                groupBlock(group, perRow: perRow)
            }
            Text("\(selected.filter { all.contains($0) }.count) of \(all.count) permissions selected")
                .font(NeemaFont.manrope(11)).foregroundColor(c.textDim).padding(.top, 4)
        }
        .measureWidth($width)
    }

    private func groupBlock(_ group: String, perRow: Int) -> some View {
        let gp = PermissionCatalog.inGroup(group)
        let allSel = gp.allSatisfy { selected.contains($0.key) }
        let rows = stride(from: 0, to: gp.count, by: perRow).map { Array(gp[$0..<min($0 + perRow, gp.count)]) }
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(group.uppercased()).font(NeemaFont.manrope(10, .bold)).tracking(0.8).foregroundColor(c.gold2)
                Spacer(minLength: 4)
                TextLink(label: allSel ? "Deselect" : "Select all", size: 11) {
                    onChange(allSel ? selected.filter { k in !gp.contains { $0.key == k } } : uniqueStrings(selected + gp.map { $0.key }))
                }
            }
            ForEach(Array(rows.enumerated()), id: \.offset) { _, pair in
                HStack(alignment: .top, spacing: 6) {
                    ForEach(pair) { perm in permCell(perm) }
                    if pair.count < perRow { Spacer(minLength: 0) }
                }
                .padding(.bottom, 6)
            }
        }
        .padding(.bottom, 4)
    }

    private func permCell(_ perm: PermissionDef) -> some View {
        let checked = selected.contains(perm.key)
        return Button {
            onChange(checked ? selected.filter { $0 != perm.key } : selected + [perm.key])
        } label: {
            HStack(spacing: 8) {
                ZStack {
                    RoundedRectangle(cornerRadius: 4).fill(checked ? c.gold : c.bg2)
                    // Unticked, the box's edge must read at 3:1: the pale green by day, grey-green by night.
                    RoundedRectangle(cornerRadius: 4).stroke(checked ? c.gold : (c.isDark ? c.muted : c.border2), lineWidth: 1.5)
                    if checked { Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundColor(onGold(c)) }
                }
                .frame(width: 18, height: 18)
                Text(perm.label).font(NeemaFont.manrope(12, .medium)).foregroundColor(checked ? c.gold2 : c.textMid)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 10).padding(.vertical, 8)
            .frame(maxWidth: .infinity, minHeight: 48)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(checked ? c.bg3 : c.surface))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(checked ? c.border : c.hairline))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(perm.label)
        .accessibilityValue(checked ? "Checked" : "Unchecked")
        .accessibilityAddTraits(checked ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}

/// `distinct()`: the first occurrence of each, in order.
func uniqueStrings(_ list: [String]) -> [String] {
    var seen = Set<String>()
    return list.filter { seen.insert($0).inserted }
}

// ── Assign role ──────────────────────────────────────────────────────────────

struct AssignRoleDialog: View {
    let agent: Agent
    let roles: [CustomRole]
    @ObservedObject var model: TeamScreenModel
    let saving: Bool
    let onDismiss: () -> Void
    let onSave: (String, [String]?) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let forms = model.ui.forms
        let roleId = forms.assignRole
        // Per-agent override (agents.custom_permissions): off = exactly the role's permissions.
        let override = forms.assignOverride
        let perms = forms.assignPerms
        FormSheet(title: "Assign Role — \(agent.name)", tall: true, buttons: {
            TeamBtn(label: saving ? "Assigning…" : "Assign Role", variant: .primary, enabled: !saving && !roleId.isEmpty) {
                onSave(roleId, override ? perms : nil)
            }
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            Text("Select a role. The agent will immediately receive those permissions.")
                .font(NeemaFont.manrope(12)).foregroundColor(c.textDim).padding(.bottom, 12)
            ForEach(roles) { role in roleRow(role, selected: roleId == role.id) }
            if roles.isEmpty {
                Text("No roles yet — create one on the Roles tab.").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
            }
            Hairline(color: c.isDark ? c.hairline : c.bg3).padding(.top, 6)
            Toggle(isOn: Binding(get: { override }, set: { on in
                model.vm.editForms { f in
                    f.assignOverride = on
                    if on && agent.customPermissions == nil { f.assignPerms = roles.first { $0.id == f.assignRole }?.permissions ?? f.assignPerms }
                }
            })) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Custom permissions for this agent").font(NeemaFont.manrope(13, .semibold)).foregroundColor(c.text)
                    Text(override ? "This agent gets exactly the permissions ticked below, instead of the role's." : "Off — the agent gets the role's permissions.")
                        .font(NeemaFont.manrope(11)).foregroundColor(c.textDim)
                }
            }
            .tint(c.gold)
            .padding(.vertical, 8)
            if override {
                // getAgentPermissions reads an empty list as "none set": the agent
                // falls back to their base role's defaults, not to nothing.
                if !perms.contains(where: { k in PermissionCatalog.ALL.contains { $0.key == k } }) {
                    Text("With nothing ticked, the agent falls back to the default permissions of their base role (\(capitalizeFirst(agent.role))) — not to none.")
                        .font(NeemaFont.manrope(11)).foregroundColor(c.isDark ? Palette.amber300 : Palette.amber800)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 10).padding(.vertical, 8)
                        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? Palette.amber950.opacity(0.45) : Palette.amber50))
                        .padding(.bottom, 8)
                }
                PermissionPicker(selected: perms) { next in model.vm.editForms { $0.assignPerms = next } }
            }
        }
    }

    private func roleRow(_ role: CustomRole, selected sel: Bool) -> some View {
        Button {
            model.vm.editForms { f in
                f.assignRole = role.id
                // A fresh override starts from the chosen role's set.
                if !f.assignOverride { f.assignPerms = role.permissions }
            }
        } label: {
            HStack(alignment: .top, spacing: 12) {
                RoleSquare(role: role, size: 32)
                VStack(alignment: .leading, spacing: 2) {
                    FlowLayout(spacing: 8, lineSpacing: 2) {
                        Text(role.name).font(NeemaFont.manrope(13, .bold)).foregroundColor(c.text)
                        if role.isProtected { ProtectedTag(compact: true) }
                    }
                    if !role.description.isEmpty {
                        Text(role.description).font(NeemaFont.manrope(11)).foregroundColor(c.textDim).multilineTextAlignment(.leading)
                    }
                    Text("\(role.permissions.count) permission\(role.permissions.count != 1 ? "s" : "")").font(NeemaFont.manrope(11)).foregroundColor(c.muted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if sel {
                    Image(systemName: "checkmark").font(.system(size: 15, weight: .bold)).foregroundColor(c.gold).padding(.leading, 8)
                        .accessibilityLabel("Selected")
                }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(sel ? c.bg : c.bg2))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(sel ? hexColor(role.color) : (c.isDark ? c.hairline : c.bg3), lineWidth: sel ? 2 : 1))
        }
        .buttonStyle(.plain)
        .padding(.bottom, 8)
        .accessibilityAddTraits(sel ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}

// ── Create / edit / password / remove ────────────────────────────────────────

struct CreateAgentDialog: View {
    @ObservedObject var model: TeamScreenModel
    let saving: Bool
    let onDismiss: () -> Void
    let onCreate: (String, String, String, String) -> Void
    @Environment(\.neema) private var c
    private static let roles = [SelectOption("agent", "Agent"), SelectOption("admin", "Admin"), SelectOption("readonly", "Read Only")]

    var body: some View {
        let f = model.ui.forms
        FormSheet(title: "Add Agent", tall: true, buttons: {
            TeamBtn(label: saving ? "Creating…" : "Create Agent", variant: .primary, enabled: !saving) {
                onCreate(f.createName, f.createEmail, f.createPassword, f.createRole)
            }
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            LabeledInput(label: "Full Name", text: model.bind(\.createName), placeholder: "Jane Doe", capitalization: .words)
            LabeledInput(label: "Email", text: model.bind(\.createEmail), placeholder: "jane@bethanyhouse.co.ke", keyboard: .emailAddress)
            LabeledInput(label: "Password", text: model.bind(\.createPassword), placeholder: "Min. 8 characters", password: true, submit: .done)
            SelectField(label: "Base Role", options: Self.roles, selected: model.bind(\.createRole))
            Text("Assign a detailed custom role after creating the agent using the Role button.")
                .font(NeemaFont.manrope(11)).foregroundColor(teamFaint(c)).padding(.top, 4)
        }
    }
}

struct EditAgentDialog: View {
    let agent: Agent
    @ObservedObject var model: TeamScreenModel
    let saving: Bool
    let onDismiss: () -> Void
    let onSave: (String, String) -> Void

    var body: some View {
        let f = model.ui.forms
        FormSheet(title: "Edit — \(agent.name)", buttons: {
            TeamBtn(label: saving ? "Saving…" : "Save Changes", variant: .primary, enabled: !saving) { onSave(f.editName, f.editEmail) }
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            LabeledInput(label: "Full Name", text: model.bind(\.editName), placeholder: "Jane Doe", capitalization: .words)
            LabeledInput(label: "Email", text: model.bind(\.editEmail), placeholder: "jane@bethanyhouse.co.ke", keyboard: .emailAddress, submit: .done)
        }
    }
}

struct ResetPasswordDialog: View {
    let agent: Agent
    @ObservedObject var model: TeamScreenModel
    let saving: Bool
    let onDismiss: () -> Void
    let onSave: (String, String) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let f = model.ui.forms
        let mismatch = !f.confirm.isEmpty && f.password != f.confirm
        FormSheet(title: "Reset Password — \(agent.name)", buttons: {
            TeamBtn(label: saving ? "Saving…" : "Update Password", variant: .primary, enabled: !saving && !mismatch) { onSave(f.password, f.confirm) }
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            setFor(agent.email).padding(.bottom, 12)
            LabeledInput(label: "New Password", text: model.bind(\.password), placeholder: "Min. 8 characters", password: true)
            LabeledInput(label: "Confirm Password", text: model.bind(\.confirm), placeholder: "Repeat new password", password: true,
                         isError: mismatch, supporting: mismatch ? "Passwords do not match" : nil, submit: .done)
        }
    }

    /// "Set a new password for **email**."
    private func setFor(_ email: String) -> Text {
        Text("Set a new password for ").font(NeemaFont.manrope(12)).foregroundColor(c.textDim)
            + Text(email).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
            + Text(".").font(NeemaFont.manrope(12)).foregroundColor(c.textDim)
    }
}

struct RemoveAgentDialog: View {
    let agent: Agent
    let saving: Bool
    let onDismiss: () -> Void
    let onRemove: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        FormSheet(title: "Remove Agent", buttons: {
            TeamBtn(label: saving ? "Removing…" : "Remove Agent", variant: .danger, enabled: !saving, action: onRemove)
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            boldQuestion("Remove ", agent.name, "?")
            Text("This cannot be undone. Their conversations will be unassigned.")
                .font(NeemaFont.manrope(12)).foregroundColor(c.textDim).padding(.top, 4)
        }
    }

    private func boldQuestion(_ pre: String, _ bold: String, _ post: String) -> Text {
        Text(pre).font(NeemaFont.manrope(14)).foregroundColor(c.text)
            + Text(bold).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text)
            + Text(post).font(NeemaFont.manrope(14)).foregroundColor(c.text)
    }
}

// ── Role editor / delete ─────────────────────────────────────────────────────

struct RoleEditorDialog: View {
    /// nil = a new role.
    let editing: CustomRole?
    @ObservedObject var model: TeamScreenModel
    let saving: Bool
    let onDismiss: () -> Void
    let onSave: (RoleForm) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let f = model.ui.forms
        // One id per opened editor: a retry after a timeout updates the role the
        // first attempt may have created instead of adding a second one.
        let form = RoleForm(name: f.roleName, description: f.roleDescription, color: f.roleColor, permissions: f.rolePerms,
                            id: editing == nil ? f.roleDraftId : nil)
        FormSheet(title: editing.map { "Edit Role — \($0.name)" } ?? "New Role", tall: true, buttons: {
            TeamBtn(label: saving ? "Saving…" : (editing == nil ? "Create Role" : "Save Role"), variant: .primary, enabled: !saving) { onSave(form) }
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            LabeledInput(label: "Role Name", text: model.bind(\.roleName), placeholder: "e.g. Sales Agent", capitalization: .words)
            LabeledInput(label: "Description", text: model.bind(\.roleDescription), placeholder: "Brief description", submit: .done)
            Text("Colour").font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.textDim).padding(.bottom, 6)
            FlowLayout(spacing: 4, lineSpacing: 4) {
                ForEach(Array(ROLE_COLORS.enumerated()), id: \.offset) { i, hex in
                    swatch(i, hex, selected: f.roleColor.caseInsensitiveCompare(hex) == .orderedSame)
                }
            }
            .padding(.bottom, 14)
            PermissionPicker(selected: f.rolePerms) { next in model.vm.editForms { $0.rolePerms = next } }
        }
    }

    /// A 32pt swatch (the web's) inside a 40pt tap target; the ring marks the chosen one.
    private func swatch(_ i: Int, _ hex: String, selected sel: Bool) -> some View {
        let col = hexColor(hex)
        return Button { model.vm.editForms { $0.roleColor = hex } } label: {
            ZStack {
                if sel { Circle().stroke(col, lineWidth: 2).frame(width: 32, height: 32) }
                Circle().fill(col).frame(width: 24, height: 24)
                if sel { Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundColor(roleInk(hex)) }
            }
            .frame(width: 40, height: 40)
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Colour \(i + 1) of \(ROLE_COLORS.count)")
        .accessibilityAddTraits(sel ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}

struct DeleteRoleDialog: View {
    let role: CustomRole
    let agentCount: Int
    let saving: Bool
    let onDismiss: () -> Void
    let onDelete: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        FormSheet(title: "Delete Role", buttons: {
            TeamBtn(label: saving ? "Deleting…" : "Delete Role", variant: .danger, enabled: !saving, action: onDelete)
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            question
            Text("\(agentCount) agent(s) will be unassigned from this role.")
                .font(NeemaFont.manrope(12)).foregroundColor(c.textDim).padding(.top, 4)
        }
    }

    private var question: Text {
        Text("Delete role ").font(NeemaFont.manrope(14)).foregroundColor(c.text)
            + Text(role.name).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text)
            + Text("?").font(NeemaFont.manrope(14)).foregroundColor(c.text)
    }
}
