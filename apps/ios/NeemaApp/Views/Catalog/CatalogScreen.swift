import SwiftUI
import UIKit
import NeemaCore

/// Port of components/views/CatalogView.tsx (Android `CatalogScreen`): a
/// READ-ONLY look at the live hub catalogue — exactly what Neema quotes.
/// Products, prices and stock are maintained in the hub, so nothing is edited
/// here. Tapping a card opens the whole product (every variant's price),
/// which the web's card only counts.
struct CatalogScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.catalogScreen {
            GeometryReader { g in CatalogBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}


struct CatalogBody: View {
    @ObservedObject var model: CatalogScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @Environment(\.sizeCategory) private var sizeCategory
    @SceneStorage("catalog.ui") private var savedUi: String = ""
    /// The open product, by id: it comes back after a reclaim (once the catalogue it names is on hand).
    @SceneStorage("catalog.product") private var detailId: String = ""
    /// The product as it was when tapped: the sheet keeps showing it if a poll drops it from the list.
    @State private var opened: CatalogItem?

    private var vm: CatalogViewModel { model.vm }
    private var ui: CatalogUi { model.ui }
    private var wide: Bool { width >= 600 }
    private var pad: CGFloat { wide ? 24 : 16 }
    private var fontScale: Double { Double(UIFontMetrics.default.scaledValue(for: 100)) / 100 }
    /// The web's gap-4: 16 between cards, both ways.
    private let gap: CGFloat = 16

    /// The open product: the live row, else the one tapped.
    private var detail: CatalogItem? {
        guard !detailId.isEmpty else { return nil }
        return model.catalog.first { $0.id == detailId } ?? (opened?.id == detailId ? opened : nil)
    }

    var body: some View {
        let view = model.view
        let cols = CatalogRules.columns(width: Double(width - pad * 2), fontScale: fontScale)
        let grid = CatalogRules.gridRows(view.filtered, cols: cols)
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                if let a = ui.audit, !a.currencyGaps.isEmpty || !a.perPiece.isEmpty {
                    PriceAuditBanner(audit: a, open: ui.auditOpen) { vm.toggleAudit() }.padding(.bottom, 16)
                }
                header(view).padding(.bottom, 16)
                sourceBanner.padding(.bottom, 20)
                filters(view.categories).padding(.bottom, 20)
                // Rows of equal height, like the web's CSS grid: every card in a row stretches to the tallest one in it.
                ForEach(Array(grid.rows.enumerated()), id: \.offset) { i, row in
                    HStack(alignment: .top, spacing: gap) {
                        ForEach(row) { item in
                            ProductCard(item: item, imageAspect: cols == 1 ? 4.0 / 3.0 : 1) { opened = item; detailId = item.id }
                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                        }
                        // A short last row keeps the full grid's column widths.
                        ForEach(0..<max(0, cols - row.count), id: \.self) { _ in Color.clear.frame(maxWidth: .infinity, maxHeight: 1) }
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, i < grid.rows.count - 1 ? gap : 0)
                }
                if model.catalog.isEmpty, let err = ui.catalogError {
                    // Nothing loaded and the last read failed: "No items found" would be untrue.
                    LoadProblem(message: err, title: "Couldn't load the catalogue", retrying: ui.refreshing, onRetry: { vm.retry() })
                } else if view.filtered.isEmpty {
                    VStack(spacing: 12) {
                        Text("📦").font(.system(size: 30))
                        Text("No items found").font(NeemaFont.manrope(14)).foregroundColor(c.muted)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 64)
                }
                Color.clear.frame(height: 24)
            }
            .padding(pad)
        }
        .refreshable { await pullToRefresh() }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        // A phone sheet, or a 440 pt panel beside the grid from 600 pt (Android `AdaptiveSheet`).
        .adaptiveSheet(item: detailItem, width: width, title: { $0.name }) { item in ProductDetailView(item: item) }
        .onAppear {
            vm.restoreIfFresh(JSONValue.parse(savedUi)?.objectValue)
            vm.life.shown.update(true)
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: ui) { savedUi = JSONValue.object(vm.saveUi()).text }
    }

    // ── Pieces ────────────────────────────────────────────────────────────────

    private func header(_ v: CatalogView) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Catalog").font(NeemaFont.manrope(20, .bold)).foregroundColor(c.text)
            countsLine(v).font(NeemaFont.manrope(14))
        }
    }

    /// "6 items · 5 in stock · 1 out of stock", each part in its own colour.
    private func countsLine(_ v: CatalogView) -> Text {
        let dot = Text("  ·  ").foregroundColor(Palette.stone200)
        var t = Text("\(v.total) items").foregroundColor(c.muted)
        t = t + dot + Text("\(v.inStock) in stock").foregroundColor(Palette.emerald600)
        if v.outStock > 0 { t = t + dot + Text("\(v.outStock) out of stock").foregroundColor(Palette.red500) }
        return t
    }

    private var sourceBanner: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "info.circle").font(.system(size: 14, weight: .medium)).foregroundColor(c.gold2).padding(.top, 2)
            (Text("Live from the Bethany House hub.").fontWeight(.semibold)
                + Text(" Prices and stock are maintained in the hub and shared with the POS and website — this is exactly what Neema quotes to customers. To change a product, edit it in the hub."))
                .font(NeemaFont.manrope(12)).foregroundColor(c.gold2)
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.isDark ? c.goldDim : Palette.sproutWash))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.bg4))
    }

    @ViewBuilder private func filters(_ categories: [String]) -> some View {
        let search = CompactSearchField(value: Binding(get: { ui.search }, set: { vm.setSearch($0) }), placeholder: "Search name, SKU or alias…", height: 44)
        let menu = CategoryMenu(categories: categories, selected: ui.filter) { vm.setFilter($0) }
        if wide {
            HStack(spacing: 8) {
                search
                // A set width: the button's label fills it, and would otherwise squeeze the search to nothing.
                menu.frame(width: 240)
            }
        } else {
            VStack(spacing: 8) {
                search
                menu
            }
        }
    }

    /// The open product (the row's live copy, or the copy kept when it left the catalogue); dismissing clears it.
    private var detailItem: Binding<CatalogItem?> {
        Binding(get: { detail }, set: { if $0 == nil { detailId = "" } })
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }
}

/// The category picker: "All categories" or one with its glyph (Android `CategoryDropdown`).
struct CategoryMenu: View {
    let categories: [String]
    let selected: String
    let onSelect: (String) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Menu {
            Button("All categories") { onSelect("all") }
            ForEach(categories, id: \.self) { cat in
                Button("\(CatalogRules.glyph(cat)) \(cat)") { onSelect(cat) }
            }
        } label: {
            HStack(spacing: 6) {
                Text(selected == "all" ? "All categories" : "\(CatalogRules.glyph(selected)) \(selected)")
                    .font(NeemaFont.manrope(14, .medium)).foregroundColor(c.text).lineLimit(1)
                Spacer(minLength: 0)
                Image(systemName: "chevron.down").font(.system(size: 12, weight: .semibold)).foregroundColor(c.isDark ? c.muted : c.border2)
            }
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.border))
        }
        .accessibilityLabel("Category: \(selected == "all" ? "all" : selected)")
    }
}

// ── Category looks (the web's catEmoji / catColors) ───────────────────────────

/// Tailwind *-50 shades, as gradient stops (the web's catColors); softened on the night theme.
func categoryGradient(_ category: String?, dark: Bool) -> LinearGradient {
    let pairs: [String: (Color, Color)] = [
        "Anointing Oil": (Palette.amber50, Palette.yellow50), "Communion Wafers": (Palette.orange50, Palette.amber50),
        "Communion Cups": (Palette.sky50, Palette.blue50), "Prefilled Cups": (Palette.red50, Palette.rose50),
        "Communion Wine": (Palette.red50, Palette.pink50), "Communion Trays": (Palette.stone50, Palette.slate50),
        "Communion Accessories": (Palette.teal50, Palette.cyan50), "Clergy Apparel": (Palette.blue50, Palette.indigo50),
        "Clergy Vestments": (Palette.purple50, Palette.violet50),
        "anointing": (Palette.amber50, Palette.yellow50), "communion": (Palette.red50, Palette.rose50),
        "vestments": (Palette.purple50, Palette.violet50), "trays": (Palette.stone50, Palette.slate50),
        "wine": (Palette.red50, Palette.pink50), "apparel": (Palette.blue50, Palette.indigo50),
    ]
    let pair = pairs[category ?? ""] ?? (Palette.stone50, Palette.stone100)
    let alpha = dark ? 0.12 : 1.0
    return LinearGradient(colors: [pair.0.opacity(alpha), pair.1.opacity(alpha)], startPoint: .topLeading, endPoint: .bottomTrailing)
}

/// A product image that fills its box edge-to-edge; the category glyph when
/// missing or broken (and while it loads), which the image covers once it arrives.
struct ProductThumb: View {
    let item: CatalogItem
    var glyphSize: CGFloat = 56

    private var src: URL? {
        let s = [item.imageUrl, item.thumbnailUrl].compactMap { $0 }.first { !$0.isEmpty }
        return s.flatMap { URL(string: $0) }
    }

    var body: some View {
        ZStack {
            Text(CatalogRules.glyph(item.rawCategory)).font(.system(size: glyphSize)).padding(4)
            if let u = src {
                AsyncImage(url: u) { phase in
                    if case .success(let img) = phase { img.resizable().scaledToFill() } else { Color.clear }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .clipped()
        .accessibilityHidden(true)
    }
}

/// IN / OUT / "1200 left" (the web's stock badge), light and dark.
struct StockBadge: View {
    let item: CatalogItem
    @Environment(\.neema) private var c

    var body: some View {
        let dark = c.isDark
        let fg = item.inStock ? (dark ? Palette.emerald400 : Palette.emerald600) : (dark ? Palette.red400 : Palette.red500)
        let bg = dark ? fg.opacity(0.12) : (item.inStock ? Palette.emerald50 : Palette.red50)
        let line = dark ? fg.opacity(0.35) : (item.inStock ? Palette.emerald200 : Palette.red200)
        Text(CatalogRules.stockText(item)).font(NeemaFont.manrope(10, .semibold)).foregroundColor(fg).lineLimit(1)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4).fill(bg))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(line))
    }
}

struct AliasChip: View {
    let text: String
    @Environment(\.neema) private var c
    var body: some View {
        Text(text).font(NeemaFont.manrope(10)).foregroundColor(c.textDim).lineLimit(1)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4).fill(c.bg))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(c.bg3))
    }
}

/// One product in the grid (Android `ProductCard`).
struct ProductCard: View {
    let item: CatalogItem
    var imageAspect: CGFloat = 1
    let onOpen: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: onOpen) {
            VStack(alignment: .leading, spacing: 0) {
                Rectangle().fill(categoryGradient(item.rawCategory, dark: c.isDark))
                    .aspectRatio(imageAspect, contentMode: .fit)
                    .overlay(ProductThumb(item: item))
                    .clipped()
                VStack(alignment: .leading, spacing: 0) {
                    // Name and stock badge side by side (the web's justify-between) when the
                    // card is wide enough; on a narrow card at a large font the badge goes under the name.
                    ViewThatFits(in: .horizontal) {
                        HStack(alignment: .top, spacing: 4) {
                            nameText
                            Spacer(minLength: 0)
                            StockBadge(item: item)
                        }
                        VStack(alignment: .leading, spacing: 4) {
                            nameText
                            StockBadge(item: item)
                        }
                    }
                    let hasDescription = !(item.description ?? "").isEmpty
                    if hasDescription {
                        Text(item.description ?? "").font(NeemaFont.manrope(12)).foregroundColor(c.muted).lineLimit(2).padding(.top, 4)
                    }
                    Text(CatalogRules.unbroken(CatalogRules.priceText(item))).font(NeemaFont.manrope(14, .bold))
                        .foregroundColor(c.isDark ? c.gold2 : Palette.moss800).monospacedDigit().padding(.top, hasDescription ? 8 : 4)
                    if !item.variants.isEmpty {
                        Text("\(item.variants.count) variants").font(NeemaFont.manrope(10)).foregroundColor(c.textDim).padding(.top, 2)
                    }
                    if !item.aliases.isEmpty {
                        FlowLayout(spacing: 4, lineSpacing: 4) {
                            ForEach(Array(item.aliases.prefix(3)), id: \.self) { AliasChip(text: $0) }
                        }
                        .padding(.top, 8)
                    }
                    HStack(spacing: 4) {
                        Text(item.sku).font(NeemaFont.mono(10)).foregroundColor(c.muted).lineLimit(1)
                        Spacer(minLength: 0)
                        if let id = item.hubProductId { Text("#\(id)").font(NeemaFont.mono(10)).foregroundColor(c.muted) }
                    }
                    .padding(.top, 8)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.bg3))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(item.name), \(CatalogRules.priceText(item)), \(item.inStock ? "in stock" : "out of stock")")
        .accessibilityHint("Opens the product")
    }

    private var nameText: some View {
        Text(item.name).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text).multilineTextAlignment(.leading)
    }
}

/// The hub's prices, checked against themselves (Android `PriceAuditBanner`).
/// A USD row that is not KES ÷ rate, or a pack good priced per single piece,
/// is a wrong quote waiting to happen. Nothing here is editable: the fix is in the hub.
struct PriceAuditBanner: View {
    let audit: PriceAudit
    let open: Bool
    let onToggle: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let dark = c.isDark
        let gaps = audit.currencyGaps
        let pp = audit.perPiece
        let fg900 = dark ? Palette.amber200 : Palette.amber900
        let fg800 = dark ? Palette.amber300 : Palette.amber800
        let fg950 = dark ? Palette.amber100 : Palette.amber950
        let rate = CatalogRules.plainNum(audit.rate)
        VStack(alignment: .leading, spacing: 0) {
            // The web's toggle is the heading button only: a tap on the list below leaves it open.
            Button(action: onToggle) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(headline(gaps.count, pp.count, rate)).font(NeemaFont.manrope(14, .semibold)).foregroundColor(fg900)
                    Text("Neema quotes exactly what the hub holds — these are wrong quotes waiting to happen. Fix the rows in the hub. \(open ? "Hide" : "Show") the list.")
                        .font(NeemaFont.manrope(12)).foregroundColor(fg800)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16).padding(.top, 16).padding(.bottom, open ? 0 : 16)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityHint(open ? "Hides the list" : "Shows the list")
            if open {
                VStack(alignment: .leading, spacing: 0) {
                    if !gaps.isEmpty {
                        HStack(spacing: 4) {
                            Text("Product").frame(maxWidth: .infinity, alignment: .leading)
                            Text("KES").frame(maxWidth: .infinity, alignment: .trailing)
                            Text("USD in hub").frame(maxWidth: .infinity, alignment: .trailing)
                            Text("KES ÷ \(rate)").frame(maxWidth: .infinity, alignment: .trailing)
                        }
                        .font(NeemaFont.manrope(12, .bold)).foregroundColor(fg900.opacity(0.7))
                        ForEach(Array(gaps.enumerated()), id: \.offset) { _, g in
                            Hairline(color: Palette.amber200).padding(.vertical, 4)
                            HStack(spacing: 4) {
                                gapName(g, ink: fg950, dark: dark).font(NeemaFont.manrope(12)).frame(maxWidth: .infinity, alignment: .leading)
                                Text(CatalogRules.num(g.kes)).font(NeemaFont.manrope(12)).foregroundColor(fg950).monospacedDigit().frame(maxWidth: .infinity, alignment: .trailing)
                                Text(CatalogRules.usd(g.usd)).font(NeemaFont.manrope(12, .semibold)).monospacedDigit()
                                    // red-700 / blue-700 by day; red-400 / blue-400 so they read on the night banner.
                                    .foregroundColor(g.usd > g.usdExpected ? (dark ? Palette.red400 : Palette.red700) : (dark ? Palette.blue400 : Palette.blue700))
                                    .frame(maxWidth: .infinity, alignment: .trailing)
                                Text(CatalogRules.usd(g.usdExpected)).font(NeemaFont.manrope(12)).foregroundColor(fg950).monospacedDigit().frame(maxWidth: .infinity, alignment: .trailing)
                            }
                        }
                    }
                    if !pp.isEmpty {
                        perPieceLine(pp).font(NeemaFont.manrope(12)).foregroundColor(fg900)
                            .padding(.top, gaps.isEmpty ? 0 : 12)
                    }
                }
                .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 16)
            }
        }
        .frame(maxWidth: .infinity)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(dark ? Palette.amber500.opacity(0.2) : Palette.amber50))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Palette.amber300))
    }

    /// The product's name, and its category after a dot when the hub has one (an
    /// uncategorised product's "" or an older row's null would print a dangling " · ").
    private func gapName(_ g: PriceGap, ink: Color, dark: Bool) -> Text {
        let name = Text(g.name).foregroundColor(ink)
        guard let cat = g.category, !cat.isEmpty else { return name }
        return name + Text(" · \(cat)").foregroundColor((dark ? Palette.amber400 : Palette.amber700).opacity(0.7))
    }

    private func perPieceLine(_ pp: [PerPieceRow]) -> Text {
        let rows = pp.map { row -> String in
            let kes = row.kes.map { CatalogRules.plainNum($0) } ?? "?"
            return "\(row.name) (KES \(kes))"
        }.joined(separator: ", ")
        let lead = Text("Priced per piece, no pack size in the name:").fontWeight(.semibold)
        return lead + Text(" " + rows) + Text(". Neema says \"each\" and asks how many — she will not invent a pack price. Give these rows a pack quantity and a pack price in the hub.")
    }

    private func headline(_ gaps: Int, _ pp: Int, _ rate: String) -> String {
        var parts: [String] = []
        if gaps > 0 { parts.append("\(gaps) product\(gaps == 1 ? "" : "s") whose USD price in the hub disagrees with KES ÷ \(rate)") }
        if pp > 0 { parts.append("\(pp) pack good\(pp == 1 ? "" : "s") priced per single piece") }
        return parts.joined(separator: " · ")
    }
}
