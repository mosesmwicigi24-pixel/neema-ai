import Foundation

/// A Tailwind-style tone the orders (and leads) badges are drawn in — the
/// web's `text-amber-700 bg-amber-50 border-amber-200`; the app maps each to
/// its light and dark colours (Android `Tones`).
public enum StatusTone: String, Sendable, Equatable, CaseIterable { case amber, blue, emerald, red, sky, green }

public struct StatusMeta: Equatable, Sendable {
    public let label: String
    public let tone: StatusTone
    public init(_ label: String, _ tone: StatusTone) { self.label = label; self.tone = tone }
}

/// The header's and the status cards' figures, from one pass over the orders.
public struct OrderStats: Equatable, Sendable {
    /// Orders per status (every one of `ORDER_STATUSES`, zero included).
    public let counts: [String: Int]
    /// Money per status (`o.total || o.subtotal`), for the card under each count.
    public let revenueBy: [String: Double]
    /// "Total Revenue": everything but the cancelled.
    public let revenue: Double
    public init(counts: [String: Int], revenueBy: [String: Double], revenue: Double) {
        self.counts = counts; self.revenueBy = revenueBy; self.revenue = revenue
    }
}

/// The pure rules of components/views/OrdersView.tsx (Android `feature/orders/OrderUi.kt`).
public enum OrderUi {
    /// Our own triage statuses, in the web's order (OrderStatus).
    public static let ORDER_STATUSES = ["pending", "confirmed", "delivered", "cancelled"]

    /// STATUS_META
    public static let STATUS_META: [String: StatusMeta] = [
        "pending": StatusMeta("Pending", .amber),
        "confirmed": StatusMeta("Confirmed", .blue),
        "delivered": StatusMeta("Delivered", .emerald),
        "cancelled": StatusMeta("Cancelled", .red),
    ]

    /// STATUS_ACTIONS — the moves open from each status.
    public static let STATUS_ACTIONS: [String: [String]] = [
        "pending": ["confirmed", "cancelled"],
        "confirmed": ["delivered", "cancelled"],
        "delivered": [],
        "cancelled": [],
    ]

    public static func statusMeta(_ status: String) -> StatusMeta { STATUS_META[status] ?? STATUS_META["pending"]! }

    /// The moves open from `status` (none for an unknown one).
    public static func actions(from status: String) -> [String] { STATUS_ACTIONS[status] ?? [] }

    /// Where the hub lives, for "Open in hub" links (NEXT_PUBLIC_HUB_URL's default).
    public static let HUB_URL = "https://hub.bethanyhouse.co.ke"

    /// The link into the hub for one order: /handoff/orders/{id}, carrying the
    /// order's public token in the URL FRAGMENT — a fragment never reaches a
    /// server or a log, so a colleague with a hub login lands on the admin page
    /// and one without lands on the customer's view of the same order.
    ///
    /// Nil when the order was never pushed: a link to a hub order that does not
    /// exist is worse than no link.
    public static func hubOrderHref(_ order: Order) -> String? {
        guard let id = order.hubOrderId else { return nil }
        var base = HUB_URL
        while base.hasSuffix("/") { base.removeLast() }
        base += "/handoff/orders/\(id)"
        if let t = order.hubPublicToken, !t.trimmingCharacters(in: .whitespaces).isEmpty { return "\(base)#v=\(t)" }
        return base
    }

    /// The hub's own word for this order's state — "Completed" when it is done.
    public static func hubMeta(_ order: Order) -> StatusMeta? {
        let s = (order.hubStatus ?? "").lowercased()
        if order.hubOrderId == nil || s.isEmpty { return nil }
        switch s {
        case "confirmed", "processing": return StatusMeta("Confirmed", .amber)
        case "shipped": return StatusMeta("Shipped", .sky)
        case "delivered", "completed": return StatusMeta("Completed", .green)
        case "cancelled", "voided": return StatusMeta("Cancelled", .red)
        default: return nil
        }
    }

    /// The phone line under an order's name, or nil when it would only repeat
    /// the name. The API sends no `contact_name` (admin.py `list_orders`), so
    /// the name shown is the bare wa_id (mapOrder's `contact_name ?? wa_id`)
    /// and this line is its formatted form, as on the web.
    public static func phoneLine(_ order: Order, displayedName: String) -> String? {
        let p = Fmt.formatPhone(order.waId)
        return (!p.isEmpty && p != displayedName) ? p : nil
    }

    /// OrdersView's `filtered`: the status filter, then a search over the name
    /// (`contact_name ?? wa_id`), the phone and the id.
    public static func filterOrders(_ orders: [Order], filter: String, search: String) -> [Order] {
        let q = search.lowercased()
        return orders.filter { o in
            if filter != "all" && o.status != filter { return false }
            if q.isEmpty { return true }
            return o.customerName.lowercased().contains(q) || o.waId.contains(q) || o.id.lowercased().contains(q)
        }
    }

    /// One page of `list` (1-based), without copying the rest of it.
    public static func pageOf<T>(_ list: [T], page: Int, size: Int) -> [T] {
        let from = min(max((page - 1) * size, 0), list.count)
        return Array(list[from..<min(from + size, list.count)])
    }

    /// OrdersView's `statusCounts`, per-status revenue and `totalRevenue` in a
    /// single pass — the web filters the whole list once per status card on
    /// every render, which a thousand orders make felt.
    public static func orderStats(_ orders: [Order]) -> OrderStats {
        var counts: [String: Int] = [:]
        var money: [String: Double] = [:]
        var revenue = 0.0
        for o in orders {
            counts[o.status, default: 0] += 1
            let a = o.amount
            money[o.status, default: 0] += a
            if o.status != "cancelled" { revenue += a }
        }
        var c: [String: Int] = [:], m: [String: Double] = [:]
        for s in ORDER_STATUSES { c[s] = counts[s] ?? 0; m[s] = money[s] ?? 0 }
        return OrderStats(counts: c, revenueBy: m, revenue: revenue)
    }

    /// How many status cards sit side by side: the web's four (`md:grid-cols-4`)
    /// from 600pt, but only while each card still holds its label and a revenue
    /// figure like "KES 1,284,750" whole at the user's font size — at 200% text
    /// on an upright tablet four cards broke "Confirmed" across two lines, so it
    /// goes two-up there. One column when even two can't fit the words.
    public static func statusColumns(width: Double, gutter: Double, fontScale: Double) -> Int {
        let four = (width - gutter * 2 - 36) / 4
        if width >= 600 && four >= 100 * fontScale + 28 { return 4 }
        if width / fontScale < 240 { return 1 }
        return 2
    }

    /// The pager's numbered buttons: at most five, windowed around `page`.
    public static func pageWindow(page: Int, totalPages: Int) -> [Int] {
        (0..<min(totalPages, 5)).map { i in
            if totalPages <= 5 { return i + 1 }
            if page <= 3 { return i + 1 }
            if page >= totalPages - 2 { return totalPages - 4 + i }
            return page - 2 + i
        }
    }

    /// `fmtCurrency`: "KES 1,234". An order's own figures carry its own currency
    /// (a Zambian order is ZMW); the revenue sums stay KES as on the web.
    public static func money(_ n: Double?, _ currency: String = "KES") -> String {
        let cur = currency.trimmingCharacters(in: .whitespaces)
        return Fmt.currency(n ?? 0, cur.isEmpty ? "KES" : cur)
    }

    /// 2.0 → "2", 1.5 → "1.5".
    public static func qtyText(_ q: Double) -> String { q == q.rounded(.down) ? String(Int64(q)) : String(q) }

    /// The row's one-line item summary: the first two lines (with "×n" past one) and how many more there are.
    public static func itemSummary(_ order: Order) -> (text: String, more: Int) {
        let text = order.items.prefix(2).map { i in i.name + (i.effectiveQty > 1 ? " ×\(qtyText(i.effectiveQty))" : "") }.joined(separator: ", ")
        return (text, max(0, order.items.count - 2))
    }

    /// The last eight characters of the id, upper-cased — the detail's "Order ID" cell.
    public static func shortId(_ order: Order) -> String { String(order.id.suffix(8)).uppercased() }
}

public extension OrderItem {
    /// `i.qty || i.quantity || 1`.
    var effectiveQty: Double { qty > 0 ? qty : 1 }

    /// The line's unit price: `unit`, else the line total over its quantity
    /// (the modern `unit_price` is normalised into `unit` on decode).
    var effectiveUnit: Double {
        if unit > 0 { return unit }
        if total > 0 { return total / effectiveQty }
        return 0
    }

    /// Whether the row says what this line costs (a legacy `unit`/`total`).
    var priceKnown: Bool { unit > 0 || total > 0 }

    /// The line's money: its `total` when the row has one, else unit × qty (the web's formula).
    var lineTotal: Double { total > 0 ? total : effectiveUnit * effectiveQty }
}

public extension Order {
    /// The order's money: `o.total || o.subtotal`.
    var amount: Double { total != 0 ? total : subtotal }
}
