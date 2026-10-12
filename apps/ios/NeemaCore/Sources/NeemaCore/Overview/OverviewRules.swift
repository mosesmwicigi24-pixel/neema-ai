import Foundation

/// The headline cards' figures: the server's counts, or the phone's own estimate.
public struct Headline: Equatable, Sendable {
    public var openConvs: Int, humanConvs: Int, aiConvs: Int
    public var activeAgents: Int, totalAgents: Int
    public var revenue: Double, totalOrders: Int
    public var pendingOrders: Int, deliveredOrders: Int, confirmedOrders: Int, cancelledOrders: Int
    public var inStockItems: Int, totalItems: Int
    public init(openConvs: Int, humanConvs: Int, aiConvs: Int, activeAgents: Int, totalAgents: Int, revenue: Double, totalOrders: Int,
                pendingOrders: Int, deliveredOrders: Int, confirmedOrders: Int, cancelledOrders: Int, inStockItems: Int, totalItems: Int) {
        self.openConvs = openConvs; self.humanConvs = humanConvs; self.aiConvs = aiConvs; self.activeAgents = activeAgents; self.totalAgents = totalAgents
        self.revenue = revenue; self.totalOrders = totalOrders; self.pendingOrders = pendingOrders; self.deliveredOrders = deliveredOrders
        self.confirmedOrders = confirmedOrders; self.cancelledOrders = cancelledOrders; self.inStockItems = inStockItems; self.totalItems = totalItems
    }
}

public struct ChannelRow: Equatable, Sendable {
    public let ch: String
    public let count: Int
    public let open: Int
    public init(_ ch: String, _ count: Int, _ open: Int) { self.ch = ch; self.count = count; self.open = open }
}

/// One line of the Recent Activity feed; `icon` is the web's emoji: 📦 for an order, ⚡ for an intercept.
public struct ActivityEntry: Equatable, Sendable, Identifiable {
    public let id: String
    public let user: String
    public let action: String
    public let target: String?
    public let at: String
    public let icon: String
    public init(id: String, user: String, action: String, target: String?, at: String, icon: String) {
        self.id = id; self.user = user; self.action = action; self.target = target; self.at = at; self.icon = icon
    }
}

public struct DayBar: Equatable, Sendable {
    public let label: String
    public let value: Double
    public let isToday: Bool
    public init(_ label: String, _ value: Double, _ isToday: Bool) { self.label = label; self.value = value; self.isToday = isToday }
}

public struct TopProduct: Equatable, Sendable {
    public let name: String
    public let qty: Double
    public let revenue: Double
    public init(_ name: String, _ qty: Double, _ revenue: Double) { self.name = name; self.qty = qty; self.revenue = revenue }
}

/// OverviewView.tsx's computations (Android `OverviewScreen.kt`'s): the
/// API-first headline, its fallbacks, the feed and the charts.
public enum OverviewRules {
    /// lib/channels.tsx CHANNEL_CONFIG's keys, in its order.
    public static let ALL_CHANNELS = ["whatsapp", "messenger", "facebook", "instagram", "tiktok", "email", "sms"]

    /// API stats when available, computed from what the app holds as a fallback.
    public static func headline(_ s: Stats?, convs: [Conversation], agents: [Agent], orders: [Order], catalog: [CatalogItem]) -> Headline {
        Headline(
            openConvs: s?.openConversations ?? convs.filter { $0.status == "open" }.count,
            humanConvs: s?.humanConversations ?? convs.filter { $0.interceptMode == "human" }.count,
            aiConvs: s?.aiConversations ?? convs.filter { $0.interceptMode == "ai" }.count,
            activeAgents: s?.activeAgents ?? agents.filter { $0.isAvailable }.count,
            totalAgents: s?.totalAgents ?? agents.count,
            revenue: s?.totalRevenue ?? orders.filter { $0.status != "cancelled" }.reduce(0) { $0 + $1.subtotal },
            totalOrders: s?.totalOrders ?? orders.count,
            pendingOrders: s?.pendingOrders ?? orders.filter { $0.status == "pending" }.count,
            deliveredOrders: s?.deliveredOrders ?? orders.filter { $0.status == "delivered" }.count,
            confirmedOrders: s?.confirmedOrders ?? orders.filter { $0.status == "confirmed" }.count,
            cancelledOrders: s?.cancelledOrders ?? orders.filter { $0.status == "cancelled" }.count,
            inStockItems: s?.inStockItems ?? catalog.filter { $0.inStock }.count,
            totalItems: s?.totalItems ?? catalog.count
        )
    }

    /// The server's channel breakdown without its empty rows, or the local rows per known channel.
    public static func channelRows(_ s: Stats?, convs: [Conversation]) -> [ChannelRow] {
        if let s = s { return s.channelBreakdown.filter { $0.count > 0 }.map { ChannelRow($0.channel, $0.count, $0.open) } }
        return ALL_CHANNELS.map { ch in
            ChannelRow(ch, convs.filter { $0.channel == ch }.count, convs.filter { $0.channel == ch && $0.status == "open" }.count)
        }.filter { $0.count > 0 }
    }

    /// The latest four orders and three human intercepts, newest first, eight at most.
    public static func activityFeed(orders: [Order], human: [Conversation], agents: [Agent]) -> [ActivityEntry] {
        var out: [ActivityEntry] = []
        // Recent orders — each date parsed once, not once per comparison of the sort.
        let recentOrders = orders.map { ($0, Fmt.millis($0.createdAt) ?? 0) }.sorted { $0.1 > $1.1 }.prefix(4).map { $0.0 }
        for o in recentOrders {
            // mapOrder() makes contact_name fall back to the wa_id (and contact_phone the wa_id):
            // an unnamed buyer reads as their bare number, as on the web — never "Unknown".
            let phone = (o.contactPhone?.isEmpty == false) ? o.contactPhone! : o.waId
            out.append(ActivityEntry(id: "order-\(o.id)", user: Fmt.displayName(o.customerName, phone), action: "placed an order",
                                     target: Fmt.currency(o.total), at: o.createdAt, icon: "📦"))
        }
        // Recent human intercepts. mapConversation() dates a thread with no messages yet
        // from its creation, so the web's `c.last_message_at` test only drops a thread with neither.
        let recentHuman = human.filter { $0.interceptMode == "human" && !(($0.lastMessageAt ?? $0.createdAt) ?? "").isEmpty }
            .map { ($0, Fmt.millis($0.lastMessageAt ?? $0.createdAt) ?? 0) }.sorted { $0.1 > $1.1 }.prefix(3).map { $0.0 }
        for conv in recentHuman {
            out.append(ActivityEntry(id: "conv-\(conv.id)", user: agents.first { $0.id == conv.assignedAgentId }?.name ?? "An agent",
                                     action: "intercepted conversation with", target: Fmt.displayName(conv.name, conv.waId),
                                     at: (conv.lastMessageAt ?? conv.createdAt) ?? "", icon: "⚡"))
        }
        return out.map { ($0, Fmt.millis($0.at) ?? 0) }.sorted { $0.1 > $1.1 }.prefix(8).map { $0.0 }
    }

    /// Revenue per day from real orders over the last 7 days (cancelled excluded).
    public static func sevenDayRevenue(_ orders: [Order], today: LocalDay, zone: TimeZone) -> [DayBar] {
        var byDay: [LocalDay: Double] = [:]
        for o in orders where o.status != "cancelled" {
            if let d = LocalDay.of(o.createdAt, zone: zone) { byDay[d, default: 0] += o.total }
        }
        return (0..<7).map { i in
            let d = today.minusDays(6 - i)
            return DayBar(d.weekdayShort, byDay[d] ?? 0, i == 6)
        }
    }

    /// The five products with the most revenue over the non-cancelled orders, merged by name.
    public static func topProducts(_ orders: [Order]) -> [TopProduct] {
        var order: [String] = []
        var qtyOf: [String: Double] = [:]
        var revOf: [String: Double] = [:]
        for o in orders where o.status != "cancelled" {
            for item in o.items {
                // `item.qty || item.quantity || 1`: only a zero (missing) quantity counts as one.
                let qty = item.qty != 0 ? item.qty : 1
                let rev = item.total != 0 ? item.total : item.unit * qty
                if qtyOf[item.name] == nil { order.append(item.name) }
                qtyOf[item.name, default: 0] += qty
                revOf[item.name, default: 0] += rev
            }
        }
        // A stable sort: ties keep their first-seen order.
        return order.map { TopProduct($0, qtyOf[$0] ?? 0, revOf[$0] ?? 0) }
            .enumerated().sorted { a, b in a.element.revenue != b.element.revenue ? a.element.revenue > b.element.revenue : a.offset < b.offset }
            .prefix(5).map { $0.element }
    }

    /// "×3", "×1.5": a whole quantity without its ".0".
    public static func qtyText(_ q: Double) -> String { q == q.rounded(.down) ? String(Int64(q)) : String(q) }

    /// CSS `capitalize`: the first letter of every word upper-cased, the rest as written.
    public static func capitalizeWords(_ s: String) -> String {
        var out = ""
        var atWordStart = true
        for ch in s {
            if ch.isWhitespace { out.append(ch); atWordStart = true; continue }
            out.append(atWordStart ? String(ch).uppercased() : String(ch))
            atWordStart = false
        }
        return out
    }
}
