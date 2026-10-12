import SwiftUI
import NeemaCore

/// The lead detail (Android `LeadDetail`): who they are, a shortcut to the
/// thread, the stage chips, tags and notes, their stats — and Save / Cancel
/// pinned under the fields, so with the keyboard up (the sheet shrinks to the
/// space above it) they are still one tap away instead of scrolled out of sight.
struct LeadDetailView: View {
    let lead: Lead
    let stages: [LeadStage]
    /// The fields as typed and the lead as the sheet opened (the model's, so they outlive a reclaim).
    let draft: LeadSheetDraft
    /// A save is in flight: the fields wait and Save shows progress.
    let saving: Bool
    /// Why the last save failed — shown above the buttons; the fields keep what was typed.
    let error: String?
    let onDraft: (LeadSheetDraft) -> Void
    let onClose: () -> Void
    let onOpenChat: () -> Void
    /// Only the fields that changed are set — an untouched stage must not lock the AI out.
    let onSave: (LeadEdit) -> Void
    @Environment(\.neema) private var c
    @FocusState private var focus: Field?

    private enum Field { case tags, notes }

    private var name: String {
        if let n = lead.name, !n.trimmingCharacters(in: .whitespaces).isEmpty { return n }
        return "Unknown customer"
    }

    /// Email · location, whichever the lead has.
    private var extra: String {
        [lead.email, lead.location].compactMap { $0?.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var facts: String {
        var out: [String] = []
        if let t = lead.tierLabel, !t.isEmpty { out.append(t) }
        if let r = lead.buyingRhythm {
            if let cad = r.cadenceLabel, !cad.isEmpty { out.append("buys \(cad)") }
            if r.overdue { out.append("overdue") }
        }
        return out.joined(separator: " · ")
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    who
                    LeadFieldLabel(text: "Lead Stage").padding(.top, 12)
                    stageChips
                    LeadFieldLabel(text: "Tags (comma separated)").padding(.top, 16)
                    tagsField
                    LeadFieldLabel(text: "Notes").padding(.top, 16)
                    notesField
                    stats.padding(.top, 16)
                }
                .padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 12)
            }
            // ── Pinned footer: the save error and the buttons ──────────────────
            Hairline(color: c.isDark ? c.hairline : Palette.gray100)
            VStack(alignment: .leading, spacing: 4) {
                if let e = error { InlineError(message: e) }
                HStack(spacing: 8) {
                    WebBtn(label: saving ? "Saving…" : "Save Changes", variant: .primary, enabled: !saving, busy: saving, size: .md, fill: true) {
                        onSave(draft.edit())
                    }
                    WebBtn(label: "Cancel", variant: .outline, size: .md, action: onClose)
                }
            }
            .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 20)
        }
    }

    // ── Pieces ────────────────────────────────────────────────────────────────

    private var who: some View {
        HStack(alignment: .top, spacing: 12) {
            AvatarView(name: Fmt.displayName(lead.name, lead.handle), size: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(name).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text)
                Text(Fmt.formatPhone(lead.handle).unbroken).font(NeemaFont.mono(12)).foregroundColor(c.textDim)
                if !extra.isEmpty { Text(extra).font(NeemaFont.manrope(11)).foregroundColor(c.muted) }
                Button(action: onOpenChat) {
                    Text("Open chat →").font(NeemaFont.manrope(13, .semibold)).foregroundColor(c.gold2).frame(minHeight: 44)
                }
                .buttonStyle(.plain)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 2)
            // A plain ✕ as on the web, in a 44pt touch target that VoiceOver names.
            Button(action: onClose) {
                Image(systemName: "xmark").font(.system(size: 18, weight: .medium)).foregroundColor(c.isDark ? c.muted : Palette.stone400)
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .offset(x: 12, y: -8)
            .accessibilityLabel("Close")
        }
    }

    private var stageChips: some View {
        FlowLayout(spacing: 6, lineSpacing: 6) {
            ForEach(stages) { s in
                StageChip(stage: s, on: s.id == draft.stage, enabled: !saving) { change { $0.stage = s.id } }
            }
        }
    }

    private func change(_ f: (inout LeadSheetDraft) -> Void) {
        var d = draft
        f(&d)
        onDraft(d)
    }

    private var tagsBinding: Binding<String> { Binding(get: { draft.tags }, set: { v in change { $0.tags = v } }) }
    private var notesBinding: Binding<String> { Binding(get: { draft.notes }, set: { v in change { $0.notes = v } }) }

    private func fieldBox(focused: Bool) -> some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(focused ? c.gold : c.border)
    }

    private var tagsField: some View {
        TextField("church, wholesale, repeat-buyer", text: tagsBinding)
            .font(NeemaFont.manrope(14)).foregroundColor(c.text)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
            .focused($focus, equals: .tags)
            .disabled(saving)
            .padding(.horizontal, 12).padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg))
            .overlay(fieldBox(focused: focus == .tags))
    }

    private var notesField: some View {
        TextField("Internal notes about this lead…", text: notesBinding, axis: .vertical)
            .font(NeemaFont.manrope(14)).foregroundColor(c.text).lineLimit(3...8)
            .focused($focus, equals: .notes)
            .disabled(saving)
            .padding(.horizontal, 12).padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg))
            .overlay(fieldBox(focused: focus == .notes))
    }

    /// grid-cols-2 gap-3 p-3
    private var stats: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                stat("Orders", String(lead.totalOrders))
                stat("Total spent", leadMoney(lead.totalSpent))
            }
            HStack(spacing: 12) {
                stat("Lead score", "\(lead.leadScore)/100")
                stat("Channels", String(lead.channels.count))
            }
            if !facts.isEmpty { Text(facts).font(NeemaFont.manrope(11)).foregroundColor(c.textMid) }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.bg3))
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label).font(NeemaFont.manrope(10)).foregroundColor(c.textDim)
            Text(value).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text).monospacedDigit()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A stage chip in the sheet: the web's px-2.5 py-1.5 look in a 44pt touch cell.
private struct StageChip: View {
    let stage: LeadStage
    let on: Bool
    let enabled: Bool
    let action: () -> Void
    @Environment(\.neema) private var c

    private var look: LeadStageLook { LeadStageLook.of(stage) }
    private var fg: Color { on ? look.textC(c.isDark) : (c.isDark ? c.muted : Palette.stone400) }
    private var border: Color { on ? look.borderC(c.isDark) : (c.isDark ? c.hairline : Palette.stone200) }

    var body: some View {
        Button(action: action) {
            Text(stage.label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(fg)
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(on ? look.bgC(c.isDark) : c.bg2))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(border))
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityAddTraits(on ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}

/// The sheet's field label: uppercase, 12pt semibold, tracked (Android `FieldLabel`).
struct LeadFieldLabel: View {
    let text: String
    @Environment(\.neema) private var c

    var body: some View {
        Text(text.uppercased()).font(NeemaFont.manrope(12, .semibold)).tracking(0.6).foregroundColor(c.textDim).padding(.bottom, 6)
    }
}
