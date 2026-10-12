import SwiftUI
import NeemaCore

/// The "Offer running now" card (SettingsView.tsx; Android `OfferCard`): the
/// stored offer, what Neema says, and the form — name, discount, last day,
/// first day, scope with its categories or SKUs — with Start / Update and
/// End it now (confirmed).
struct OfferCard: View {
    @ObservedObject var model: SettingsScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @SceneStorage("settings.endOffer") private var confirmEnd = false
    @SceneStorage("settings.skuPicker") private var skuPicker = false
    /// Which date is being picked: "ends", "starts" or nothing.
    @SceneStorage("settings.datePicker") private var datePicker = ""

    private var vm: SettingsViewModel { model.vm }

    var body: some View {
        let ui = model.ui
        SettingsCard(title: "Offer running now",
                     description: "A discount you have given. Neema states it outright — the offer's name, the old price, the new one, and when it ends — and stops the day it expires.") {
            if let s = ui.offer {
                offerBody(s, ui)
            } else if let why = ui.loadErrors["offer"] {
                CardLoadProblem(why: why, title: "Couldn't load the offer") { vm.retry("offer") }
            } else {
                Text("Loading…").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
            }
        }
        .alert("End this offer?", isPresented: $confirmEnd) {
            Button("End it now", role: .destructive) { vm.saveOffer(nil) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Neema stops mentioning “\(ui.offer?.campaign?.name ?? "it")” from her next reply. You can start a new offer any time.")
        }
        .sheet(isPresented: $skuPicker) {
            SkuPickerSheet(catalog: model.catalog, selected: ui.draft.skus, onDismiss: { skuPicker = false }) { picked in
                vm.editDraft { $0.skus = picked }
                skuPicker = false
            }
            .environment(\.neema, c)
            .environmentObject(app)
        }
        .sheet(isPresented: pickerOpen) {
            OfferDateSheet(title: datePicker == "starts" ? "First day" : "Last day", initial: pickedDate(ui), onPick: { iso in
                let which = datePicker
                vm.editDraft { d in
                    if which == "starts" { d.startsOn = iso } else { d.endsOn = iso ?? "" }
                }
                datePicker = ""
            }, onCancel: { datePicker = "" })
            .environment(\.neema, c)
            .environmentObject(app)
        }
    }

    private var pickerOpen: Binding<Bool> {
        Binding(get: { !datePicker.isEmpty }, set: { if !$0 { datePicker = "" } })
    }

    private func pickedDate(_ ui: SettingsUi) -> String? {
        if datePicker == "starts" { return ui.draft.startsOn }
        return ui.draft.endsOn.isEmpty ? nil : ui.draft.endsOn
    }

    /// The whole percent as typed: the server keeps int(percent).
    private var percentBinding: Binding<String> {
        Binding(
            get: {
                let p = model.ui.draft.percent
                return p == p.rounded(.down) ? String(Int(p)) : String(p)
            },
            set: { v in
                let digits = String(v.filter { $0.isASCII && $0.isNumber }.prefix(3))
                vm.editDraft { $0.percent = Double(digits) ?? 0 }
            }
        )
    }

    private var knownCategories: [String] {
        var seen = Set<String>()
        var out: [String] = []
        for item in model.catalog {
            let cat = item.category
            if cat.isEmpty || !seen.insert(cat.lowercased()).inserted { continue }
            out.append(cat)
        }
        return out.sorted { $0.lowercased() < $1.lowercased() }
    }

    @ViewBuilder
    private func offerBody(_ s: OfferSetting, _ ui: SettingsUi) -> some View {
        let draft = ui.draft
        let campaign = s.campaign
        let max = SettingsViewModel.maxPercent(s)
        let pct = draft.percent
        let pctBad = pct < 1 || pct > Double(max)
        let stack = (width - 40) / teamFontScale < 340
        Group {
            if let camp = campaign {
                FlowLayout(spacing: 8, lineSpacing: 4) {
                    TeamPill(text: s.running ? "Running" : "Not running", color: s.running ? c.green : Palette.amber700)
                    Text("\(camp.name) · \(Int(camp.percent))% off").font(NeemaFont.manrope(12)).foregroundColor(c.textMid)
                }
                .padding(.bottom, 8)
            }
            if !s.says.trimmingCharacters(in: .whitespaces).isEmpty {
                saysLine(s.says)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.bg4))
                    .padding(.bottom, 12)
            }
            if let camp = campaign, !s.running {
                Text(notRunningNote(camp)).font(NeemaFont.manrope(11)).foregroundColor(Palette.amber700)
                    .fixedSize(horizontal: false, vertical: true).padding(.bottom, 12)
            }
        }
        SettingsField(label: "Offer name", hint: "What the customer hears it called.") {
            SettingsInput(text: model.draft(\.name), placeholder: "Harvest Offer")
        }
        SettingsPair(stack: stack) {
            SettingsField(label: "Discount %", hint: "1–\(max)", hintColor: pctBad ? c.red : nil) {
                SettingsInput(text: percentBinding, keyboard: .numberPad, isError: pctBad)
            }
        } b: {
            SettingsField(label: "Last day", hint: "Inclusive — it runs through this date.") {
                OfferDateButton(value: draft.endsOn.isEmpty ? nil : draft.endsOn, emptyLabel: "Pick a date", clearable: false,
                                onOpen: { datePicker = "ends" }, onClear: {})
            }
        }
        SettingsField(label: "First day (optional)", hint: "Leave empty to start straight away.") {
            OfferDateButton(value: draft.startsOn, emptyLabel: "Starts now", clearable: true,
                            onOpen: { datePicker = "starts" }, onClear: { vm.editDraft { $0.startsOn = nil } })
        }
        SettingsField(label: "Applies to") {
            SelectField(label: nil, options: [
                SelectOption("all", "Everything in the catalogue"),
                SelectOption("category", "Certain categories"),
                SelectOption("products", "Certain products"),
            ], selected: model.draft(\.scope))
        }
        if draft.scope == "category" {
            SettingsField(label: "Categories", hint: "As they appear in the hub. e.g. gowns, cassocks") {
                CategoryChips(known: knownCategories, selected: draft.categories) { list in vm.editDraft { $0.categories = list } }
            }
        }
        if draft.scope == "products" {
            SettingsField(label: "Product SKUs", hint: "Only these items get the offer.") {
                skuChips(draft)
            }
        }
        Text("Orders still reach the hub at the list price with the offer noted on them — a person applies it before payment.")
            .font(NeemaFont.manrope(11)).foregroundColor(c.muted).fixedSize(horizontal: false, vertical: true).padding(.bottom, 12)
        FlowLayout(spacing: 8, lineSpacing: 8) {
            SettingsSaveButton(label: campaign != nil ? "Update offer" : "Start offer", saving: ui.savingOffer) { vm.saveOffer(ui.draft) }
            if campaign != nil {
                TeamBtn(label: "End it now", variant: .outline, enabled: !ui.savingOffer) { confirmEnd = true }
            }
        }
    }

    private func saysLine(_ says: String) -> Text {
        Text("Neema says: ").font(NeemaFont.manrope(12)).foregroundColor(c.text)
            + Text(says).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
    }

    private func notRunningNote(_ camp: Campaign) -> String {
        if let s = camp.startsOn, let d = parseIsoDate(s), d > SettingsViewModel.today() {
            return "This offer starts on \(Fmt.date(s)) — it is saved, and Neema begins mentioning it that day."
        }
        return "This offer has passed its end date — it is saved, but Neema is not mentioning it."
    }

    @ViewBuilder
    private func skuChips(_ draft: Campaign) -> some View {
        FlowLayout(spacing: 6, lineSpacing: 6) {
            ForEach(Array(draft.skus.enumerated()), id: \.offset) { _, sku in skuChip(sku) }
            SettingsChipButton(label: "Choose products", icon: "plus", selected: false) { skuPicker = true }
        }
        Spacer().frame(height: 6)
        AddTextRow(placeholder: "Or type a SKU") { sku in
            vm.editDraft { d in
                if !d.skus.contains(where: { $0.caseInsensitiveCompare(sku) == .orderedSame }) { d.skus.append(sku) }
            }
        }
    }

    private func skuChip(_ sku: String) -> some View {
        let name = offerProductName(model.catalog, sku)
        return HStack(spacing: 0) {
            Text(name.map { "\(sku) · \($0)" } ?? sku).font(NeemaFont.manrope(12)).foregroundColor(c.gold2).lineLimit(1).padding(.leading, 10)
            Button { vm.editDraft { d in d.skus.removeAll { $0 == sku } } } label: {
                Image(systemName: "xmark").font(.system(size: 10, weight: .semibold)).foregroundColor(c.gold2)
                    .frame(width: 32, height: 32).frame(width: 44, height: 44).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Remove \(sku)")
        }
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? c.goldDim : c.bg3))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.border))
    }
}

/// The product (or variant) a SKU names, for the chips.
func offerProductName(_ catalog: [CatalogItem], _ sku: String) -> String? {
    for item in catalog {
        if item.sku.caseInsensitiveCompare(sku) == .orderedSame { return item.name }
        for v in item.variants where (v.sku ?? "").caseInsensitiveCompare(sku) == .orderedSame { return v.label ?? v.name ?? item.name }
    }
    return nil
}

/// Chips for the catalogue's categories, plus any typed category the catalogue doesn't list.
struct CategoryChips: View {
    let known: [String]
    let selected: [String]
    let onChange: ([String]) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let all = known + selected.filter { s in !known.contains { $0.caseInsensitiveCompare(s) == .orderedSame } }
        VStack(alignment: .leading, spacing: 6) {
            FlowLayout(spacing: 6, lineSpacing: 4) {
                ForEach(Array(all.enumerated()), id: \.offset) { _, cat in
                    let on = selected.contains { $0.caseInsensitiveCompare(cat) == .orderedSame }
                    SettingsChipButton(label: cat, icon: on ? "checkmark" : nil, selected: on) {
                        onChange(on ? selected.filter { $0.caseInsensitiveCompare(cat) != .orderedSame } : selected + [cat])
                    }
                }
            }
            if known.isEmpty {
                Text("The catalogue hasn't loaded — type the categories instead.").font(NeemaFont.manrope(11)).foregroundColor(c.muted)
            }
            AddTextRow(placeholder: "Add a category") { v in
                if !selected.contains(where: { $0.caseInsensitiveCompare(v) == .orderedSame }) { onChange(selected + [v]) }
            }
        }
    }
}

/// A date field that opens the picker; values are YYYY-MM-DD.
struct OfferDateButton: View {
    let value: String?
    let emptyLabel: String
    let clearable: Bool
    let onOpen: () -> Void
    let onClear: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        HStack(spacing: 4) {
            Button(action: onOpen) {
                HStack(spacing: 8) {
                    Image(systemName: "calendar").font(.system(size: 16)).foregroundColor(c.textDim)
                    Text(value.map { Fmt.date($0) } ?? emptyLabel).font(NeemaFont.manrope(14))
                        .foregroundColor(value != nil ? c.text : c.muted).lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.horizontal, 12).frame(minHeight: 52)
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.isDark ? c.border : Palette.gray300))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if clearable && value != nil {
                Button(action: onClear) {
                    Image(systemName: "xmark").font(.system(size: 14, weight: .medium)).foregroundColor(c.textDim).frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear date")
            }
        }
    }
}

/// The date picker, in UTC like the Material one: a YYYY-MM-DD in, a YYYY-MM-DD out.
struct OfferDateSheet: View {
    let title: String
    let onPick: (String?) -> Void
    let onCancel: () -> Void
    @State private var date: Date
    @Environment(\.neema) private var c
    private static let utc = TimeZone(identifier: "UTC")!

    init(title: String, initial: String?, onPick: @escaping (String?) -> Void, onCancel: @escaping () -> Void) {
        self.title = title
        self.onPick = onPick
        self.onCancel = onCancel
        let ms = isoDateToUtcMillis(initial) ?? Int64(Date().timeIntervalSince1970 * 1000)
        _date = State(initialValue: Date(timeIntervalSince1970: TimeInterval(ms) / 1000))
    }

    var body: some View {
        FormSheet(title: title, tall: true, buttons: {
            TeamBtn(label: "OK", variant: .primary) { onPick(utcMillisToIsoDate(Int64(date.timeIntervalSince1970 * 1000))) }
            TeamBtn(label: "Cancel", action: onCancel)
        }) {
            DatePicker("", selection: $date, displayedComponents: .date)
                .datePickerStyle(.graphical)
                .labelsHidden()
                .tint(c.gold)
                .environment(\.timeZone, Self.utc)
        }
    }
}

/// Search the catalogue and tick products (and their variants) for the offer.
struct SkuPickerSheet: View {
    let catalog: [CatalogItem]
    let onDismiss: () -> Void
    let onDone: ([String]) -> Void
    @State private var query = ""
    @State private var picked: [String]
    @Environment(\.neema) private var c

    init(catalog: [CatalogItem], selected: [String], onDismiss: @escaping () -> Void, onDone: @escaping ([String]) -> Void) {
        self.catalog = catalog
        self.onDismiss = onDismiss
        self.onDone = onDone
        _picked = State(initialValue: selected)
    }

    private struct Row: Identifiable {
        let sku: String
        let name: String
        let category: String
        var id: String { sku }
    }

    /// One row per sellable SKU: the product itself, then each variant that has its own.
    private var rows: [Row] {
        var seen = Set<String>()
        var out: [Row] = []
        for item in catalog {
            var own: [Row] = []
            if !item.sku.isEmpty { own.append(Row(sku: item.sku, name: item.name, category: item.category)) }
            for v in item.variants {
                if let s = v.sku, !s.isEmpty, s != item.sku { own.append(Row(sku: s, name: v.label ?? v.name ?? item.name, category: item.category)) }
            }
            for r in own where seen.insert(r.sku.lowercased()).inserted { out.append(r) }
        }
        return out
    }

    var body: some View {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        let all = rows
        let shown = q.isEmpty ? all : all.filter { $0.sku.lowercased().contains(q) || $0.name.lowercased().contains(q) || $0.category.lowercased().contains(q) }
        FormSheet(title: "Choose products", tall: true, buttons: {
            TeamBtn(label: "Done", variant: .primary) { onDone(picked) }
            TeamBtn(label: "Cancel", action: onDismiss)
        }) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").font(.system(size: 14, weight: .medium)).foregroundColor(c.muted)
                TextField("Search name or SKU…", text: $query).font(NeemaFont.manrope(14)).foregroundColor(c.text)
                    .textInputAutocapitalization(.never).autocorrectionDisabled(true)
            }
            .padding(.horizontal, 12).frame(minHeight: 44)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.border))
            Text("\(picked.count) selected").font(NeemaFont.manrope(11)).foregroundColor(c.muted).padding(.top, 8)
            if all.isEmpty {
                Text("The catalogue hasn't loaded yet — type SKUs on the form instead.").font(NeemaFont.manrope(12)).foregroundColor(c.muted).padding(.top, 12)
            } else if shown.isEmpty {
                Text("No products match “\(query)”.").font(NeemaFont.manrope(12)).foregroundColor(c.muted).padding(.top, 12)
            }
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(shown) { r in pickRow(r) }
            }
            .padding(.top, 4)
        }
    }

    private func pickRow(_ r: Row) -> some View {
        let on = picked.contains { $0.caseInsensitiveCompare(r.sku) == .orderedSame }
        return Button {
            if on { picked.removeAll { $0.caseInsensitiveCompare(r.sku) == .orderedSame } } else { picked.append(r.sku) }
        } label: {
            HStack(alignment: .center, spacing: 8) {
                Image(systemName: on ? "checkmark.square.fill" : "square").font(.system(size: 20)).foregroundColor(on ? c.gold : c.muted)
                VStack(alignment: .leading, spacing: 2) {
                    Text(r.name).font(NeemaFont.manrope(13)).foregroundColor(c.text).lineLimit(2).multilineTextAlignment(.leading)
                    Text("\(r.sku) · \(r.category)").font(NeemaFont.manrope(11)).foregroundColor(c.muted).lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.vertical, 6)
            .frame(minHeight: 48)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}
