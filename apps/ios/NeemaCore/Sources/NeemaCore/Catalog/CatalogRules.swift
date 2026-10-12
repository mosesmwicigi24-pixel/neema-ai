import Foundation

/// What the grid shows: the filtered products, the category menu, and the header's counts.
public struct CatalogView: Equatable, Sendable {
    public let filtered: [CatalogItem]
    public let categories: [String]
    public let total: Int
    public let inStock: Int
    public var outStock: Int { total - inStock }
    public init(filtered: [CatalogItem], categories: [String], total: Int, inStock: Int) {
        self.filtered = filtered; self.categories = categories; self.total = total; self.inStock = inStock
    }
}

/// A catalogue with each product's searchable text lowercased once, so a
/// keystroke in the search box over 2,000 products compares strings instead
/// of lowercasing every name, SKU and alias again (Android `CatalogIndex`).
public final class CatalogIndex: @unchecked Sendable {
    public let items: [CatalogItem]
    private let haystacks: [[String]]
    public let categories: [String]
    public let inStock: Int

    public init(_ items: [CatalogItem]) {
        self.items = items
        haystacks = items.map { i in [i.name.lowercased(), i.sku.lowercased()] + i.aliases.map { $0.lowercased() } }
        categories = CatalogRules.categories(items)
        inStock = items.reduce(0) { $0 + ($1.inStock ? 1 : 0) }
    }

    /// Exactly `CatalogRules.filter`'s answer.
    public func filter(_ filter: String, _ search: String) -> [CatalogItem] {
        let q = search.lowercased()
        if filter == "all" && q.isEmpty { return items }
        var out: [CatalogItem] = []
        for (n, i) in items.enumerated() where (filter == "all" || i.category == filter) && (q.isEmpty || haystacks[n].contains { $0.contains(q) }) {
            out.append(i)
        }
        return out
    }

    public func view(filter: String, search: String) -> CatalogView {
        CatalogView(filtered: self.filter(filter, search), categories: categories, total: items.count, inStock: inStock)
    }
}

/// The pure rules of components/views/CatalogView.tsx (Android `CatalogViewModel.kt` / `CatalogScreen.kt`).
public enum CatalogRules {
    /// The web's category list: every distinct, non-empty category, in catalogue order.
    public static func categories(_ catalog: [CatalogItem]) -> [String] {
        var seen = Set<String>()
        var out: [String] = []
        for i in catalog where !i.category.isEmpty && seen.insert(i.category).inserted { out.append(i.category) }
        return out
    }

    /// The web's filter: the chosen category ("all" = any), then a case-insensitive
    /// match of the search text against name, SKU or any alias.
    public static func filter(_ catalog: [CatalogItem], filter: String, search: String) -> [CatalogItem] {
        let q = search.lowercased()
        return catalog.filter { i in
            (filter == "all" || i.category == filter) &&
                (q.isEmpty || i.name.lowercased().contains(q) || i.sku.lowercased().contains(q) || i.aliases.contains { $0.lowercased().contains(q) })
        }
    }

    /// The web's grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6, read
    /// against the width the catalogue actually has. At a large font a card
    /// needs more room for its name, badge and price: drop columns until each
    /// keeps ~118pt per 100% of font (the web never scales its text, so it
    /// never needs to).
    public static func columns(width: Double, fontScale: Double = 1) -> Int {
        let web = width < 640 ? 2 : width < 768 ? 3 : width < 1024 ? 4 : 6
        let minCell = 118 * max(fontScale, 1)
        for n in stride(from: web, through: 2, by: -1) where (width - 16 * Double(n - 1)) / Double(n) >= minCell { return n }
        return 1
    }

    /// Price or "KES min – KES max" when the variants differ.
    public static func priceText(_ i: CatalogItem) -> String {
        if let lo = i.priceMinKes, let hi = i.priceMaxKes, lo != hi { return "\(Fmt.currency(lo)) – \(Fmt.currency(hi))" }
        return Fmt.currency(i.price)
    }

    /// "KES 3,500 – KES 4,200" that wraps only at the dash, never inside an amount.
    public static func unbroken(_ price: String) -> String { price.replacingOccurrences(of: "KES ", with: "KES\u{00A0}") }

    /// "1,500" not "1500.0" — the web's toLocaleString().
    public static func num(_ v: Double) -> String { Fmt.number(v) }

    /// "1500" / "129.5" — a number the web interpolates bare (`${x}`).
    public static func plainNum(_ v: Double) -> String {
        v.isFinite && v == v.rounded(.down) && abs(v) < 1e15 ? String(Int64(v)) : String(v)
    }

    /// "$10" for whole dollars, "$9.50" otherwise (the audit's usd()).
    public static func usd(_ v: Double) -> String {
        if v == v.rounded(.down) { return "$" + Fmt.number(v) }
        let cents = Int64((v * 100).rounded())
        return "$" + Fmt.number(Double(cents / 100)) + "." + String(format: "%02d", abs(cents % 100))
    }

    /// Category glyphs (the web's catEmoji).
    public static let catEmoji: [String: String] = [
        "Anointing Oil": "🕯️", "Communion Wafers": "🍞", "Communion Cups": "🥛",
        "Prefilled Cups": "🍷", "Communion Wine": "🍾", "Communion Trays": "🫙",
        "Communion Accessories": "🧴", "Clergy Apparel": "👕", "Clergy Vestments": "👘",
        "anointing": "🕯️", "communion": "🍷", "vestments": "👘", "trays": "🫙",
        "wine": "🍾", "apparel": "👕",
    ]

    public static func glyph(_ category: String?) -> String { catEmoji[category ?? ""] ?? "📦" }

    /// Keys made unique within a list: a repeated one gets its position appended.
    public static func uniqueKeys(_ keys: [String]) -> [String] {
        var seen = Set<String>()
        return keys.enumerated().map { i, k in
            if seen.insert(k).inserted { return k }
            var n = 0
            while true {
                let candidate = n == 0 ? "\(k)#\(i)" : "\(k)#\(i).\(n)"
                if seen.insert(candidate).inserted { return candidate }
                n += 1
            }
        }
    }

    /// The grid's rows of `cols` products, each with a key unique within the grid.
    public static func gridRows(_ items: [CatalogItem], cols: Int) -> (rows: [[CatalogItem]], keys: [String]) {
        let c = max(1, cols)
        let rows = stride(from: 0, to: items.count, by: c).map { Array(items[$0..<min($0 + c, items.count)]) }
        return (rows, uniqueKeys(rows.map { r in r.map { $0.id }.joined(separator: "|") }))
    }

    /// The stock badge's words: the bare number ("1200 left"), else IN / OUT.
    public static func stockText(_ i: CatalogItem) -> String {
        if !i.inStock { return "OUT" }
        if let q = i.availableQty { return "\(plainNum(q)) left" }
        return "IN"
    }
}
