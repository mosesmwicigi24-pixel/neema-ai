import Foundation

public struct OrderItem: Equatable, Hashable, Sendable {
    public var name: String
    public var qty: Double
    /// Unit price.
    public var unit: Double
    /// Line total.
    public var total: Double
    public var sku: String?
    public init(name: String = "", qty: Double = 0, unit: Double = 0, total: Double = 0, sku: String? = nil) {
        self.name = name; self.qty = qty; self.unit = unit; self.total = total; self.sku = sku
    }

    /// `order_events.items` is free-form JSONB, and two writers disagree on its
    /// shape (OrderItemsSerializer on Android): orders Neema places store
    /// `{hub_product_id, name, sku, qty, unit_price, price_usd, …}` with no
    /// `unit` and no `total`; the hub bridge stores `{name, qty, unit, total}`.
    /// Each line is normalised: the unit price from `unit`, else `unit_price`,
    /// else `price`; the quantity from `qty`, else `quantity`; the total from
    /// `total`, else qty × unit. Anything that isn't an object is dropped.
    public static func normalise(_ raw: JSONValue?) -> [OrderItem] {
        guard let rows = raw?.arrayValue else { return [] }
        return rows.compactMap { row -> OrderItem? in
            guard let o = row.objectValue else { return nil }
            let qty = o["qty"]?.lenientDouble ?? o["quantity"]?.lenientDouble ?? 0
            let unit = o["unit"]?.lenientDouble ?? o["unit_price"]?.lenientDouble ?? o["price"]?.lenientDouble ?? 0
            let total = o["total"]?.lenientDouble ?? (qty * unit)
            return OrderItem(name: o["name"]?.content ?? "", qty: qty, unit: unit, total: total, sku: o["sku"]?.content)
        }
    }
}

public struct Order: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var waId: String
    public var sessionId: String?
    public var eventType: String?
    public var items: [OrderItem]
    public var subtotal: Double
    public var currency: String
    /// Raw: "open" | "pending" | "confirmed" | "delivered" | "cancelled"
    public var rawStatus: String
    public var paymentStatus: String?
    public var fulfillmentStatus: String?
    public var replyText: String?
    public var channel: String
    public var state: JSONValue?
    public var createdAt: String
    public var updatedAt: String?
    public var contactName: String?
    public var contactPhone: String?
    public var hubOrderId: Int64?
    public var hubOrderNumber: String?
    public var hubPushStatus: String?
    public var hubLastError: String?
    public var hubPublicToken: String?
    public var hubPublicUrl: String?
    /// What the HUB says — distinct from `status`, our own triage flag.
    public var hubStatus: String?
    public var hubPaymentStatus: String?

    public init(id: String, waId: String = "", sessionId: String? = nil, eventType: String? = nil, items: [OrderItem] = [], subtotal: Double = 0,
                currency: String = "KES", rawStatus: String = "open", paymentStatus: String? = nil, fulfillmentStatus: String? = nil, replyText: String? = nil,
                channel: String = "whatsapp", state: JSONValue? = nil, createdAt: String = "", updatedAt: String? = nil, contactName: String? = nil,
                contactPhone: String? = nil, hubOrderId: Int64? = nil, hubOrderNumber: String? = nil, hubPushStatus: String? = nil, hubLastError: String? = nil,
                hubPublicToken: String? = nil, hubPublicUrl: String? = nil, hubStatus: String? = nil, hubPaymentStatus: String? = nil) {
        self.id = id; self.waId = waId; self.sessionId = sessionId; self.eventType = eventType; self.items = items; self.subtotal = subtotal
        self.currency = currency; self.rawStatus = rawStatus; self.paymentStatus = paymentStatus; self.fulfillmentStatus = fulfillmentStatus
        self.replyText = replyText; self.channel = channel; self.state = state; self.createdAt = createdAt; self.updatedAt = updatedAt
        self.contactName = contactName; self.contactPhone = contactPhone; self.hubOrderId = hubOrderId; self.hubOrderNumber = hubOrderNumber
        self.hubPushStatus = hubPushStatus; self.hubLastError = hubLastError; self.hubPublicToken = hubPublicToken; self.hubPublicUrl = hubPublicUrl
        self.hubStatus = hubStatus; self.hubPaymentStatus = hubPaymentStatus
    }

    /// mapOrder(): "open" is a cart snapshot that was never an order → shown as pending.
    public var status: String { rawStatus == "open" ? "pending" : rawStatus }
    public var customerName: String { contactName ?? waId }
    public var total: Double { subtotal }

    enum K: String, CodingKey {
        case id, wa_id, session_id, event_type, items, subtotal, currency, status, payment_status, fulfillment_status, reply_text, channel, state,
             created_at, updated_at, contact_name, contact_phone, hub_order_id, hub_order_number, hub_push_status, hub_last_error, hub_public_token,
             hub_public_url, hub_status, hub_payment_status
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), waId: c.string(.wa_id, default: ""), sessionId: c.string(.session_id), eventType: c.string(.event_type),
                  items: OrderItem.normalise(c.value(.items)), subtotal: c.double(.subtotal, default: 0), currency: c.string(.currency, default: "KES"),
                  rawStatus: c.string(.status, default: "open"), paymentStatus: c.string(.payment_status), fulfillmentStatus: c.string(.fulfillment_status),
                  replyText: c.string(.reply_text), channel: c.string(.channel, default: "whatsapp"), state: c.value(.state)?.objectValue.map { JSONValue.object($0) },
                  createdAt: c.string(.created_at, default: ""), updatedAt: c.string(.updated_at), contactName: c.string(.contact_name), contactPhone: c.string(.contact_phone),
                  hubOrderId: c.int64(.hub_order_id), hubOrderNumber: c.string(.hub_order_number), hubPushStatus: c.string(.hub_push_status), hubLastError: c.string(.hub_last_error),
                  hubPublicToken: c.string(.hub_public_token), hubPublicUrl: c.string(.hub_public_url), hubStatus: c.string(.hub_status), hubPaymentStatus: c.string(.hub_payment_status))
    }
}

// ── Stats & attribution ─────────────────────────────────────────────────────

public struct ChannelCount: Equatable, Hashable, Sendable, Decodable {
    public var channel: String
    public var count: Int
    public var open: Int
    public init(channel: String = "", count: Int = 0, open: Int = 0) { self.channel = channel; self.count = count; self.open = open }
    enum K: String, CodingKey { case channel, count, open }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(channel: c.string(.channel, default: ""), count: c.int(.count, default: 0), open: c.int(.open, default: 0))
    }
}

public struct Stats: Equatable, Sendable, Decodable {
    public var openConversations: Int, humanConversations: Int, aiConversations: Int, activeAgents: Int, totalAgents: Int
    public var totalRevenue: Double
    public var totalOrders: Int, pendingOrders: Int, deliveredOrders: Int, confirmedOrders: Int, cancelledOrders: Int, inStockItems: Int, totalItems: Int
    public var channelBreakdown: [ChannelCount]
    public init(openConversations: Int = 0, humanConversations: Int = 0, aiConversations: Int = 0, activeAgents: Int = 0, totalAgents: Int = 0,
                totalRevenue: Double = 0, totalOrders: Int = 0, pendingOrders: Int = 0, deliveredOrders: Int = 0, confirmedOrders: Int = 0,
                cancelledOrders: Int = 0, inStockItems: Int = 0, totalItems: Int = 0, channelBreakdown: [ChannelCount] = []) {
        self.openConversations = openConversations; self.humanConversations = humanConversations; self.aiConversations = aiConversations
        self.activeAgents = activeAgents; self.totalAgents = totalAgents; self.totalRevenue = totalRevenue; self.totalOrders = totalOrders
        self.pendingOrders = pendingOrders; self.deliveredOrders = deliveredOrders; self.confirmedOrders = confirmedOrders
        self.cancelledOrders = cancelledOrders; self.inStockItems = inStockItems; self.totalItems = totalItems; self.channelBreakdown = channelBreakdown
    }
    enum K: String, CodingKey {
        case open_conversations, human_conversations, ai_conversations, active_agents, total_agents, total_revenue, total_orders, pending_orders,
             delivered_orders, confirmed_orders, cancelled_orders, in_stock_items, total_items, channel_breakdown
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(openConversations: c.int(.open_conversations, default: 0), humanConversations: c.int(.human_conversations, default: 0),
                  aiConversations: c.int(.ai_conversations, default: 0), activeAgents: c.int(.active_agents, default: 0), totalAgents: c.int(.total_agents, default: 0),
                  totalRevenue: c.double(.total_revenue, default: 0), totalOrders: c.int(.total_orders, default: 0), pendingOrders: c.int(.pending_orders, default: 0),
                  deliveredOrders: c.int(.delivered_orders, default: 0), confirmedOrders: c.int(.confirmed_orders, default: 0), cancelledOrders: c.int(.cancelled_orders, default: 0),
                  inStockItems: c.int(.in_stock_items, default: 0), totalItems: c.int(.total_items, default: 0), channelBreakdown: c.list(.channel_breakdown))
    }
}

public struct AttributionRow: Equatable, Hashable, Sendable, Decodable {
    public var source: String
    public var post: String?
    public var postTitle: String?
    public var leads: Int
    public var orders: Int
    public var revenue: Double
    public var paidRevenue: Double
    public init(source: String = "", post: String? = nil, postTitle: String? = nil, leads: Int = 0, orders: Int = 0, revenue: Double = 0, paidRevenue: Double = 0) {
        self.source = source; self.post = post; self.postTitle = postTitle; self.leads = leads; self.orders = orders; self.revenue = revenue; self.paidRevenue = paidRevenue
    }
    enum K: String, CodingKey { case source, post, post_title, leads, orders, revenue, paid_revenue }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(source: c.string(.source, default: ""), post: c.string(.post), postTitle: c.string(.post_title), leads: c.int(.leads, default: 0),
                  orders: c.int(.orders, default: 0), revenue: c.double(.revenue, default: 0), paidRevenue: c.double(.paid_revenue, default: 0))
    }
}

public struct Unattributed: Equatable, Sendable, Decodable {
    public var orders: Int, revenue: Double, paidRevenue: Double
    public init(orders: Int = 0, revenue: Double = 0, paidRevenue: Double = 0) { self.orders = orders; self.revenue = revenue; self.paidRevenue = paidRevenue }
    enum K: String, CodingKey { case orders, revenue, paid_revenue }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(orders: c.int(.orders, default: 0), revenue: c.double(.revenue, default: 0), paidRevenue: c.double(.paid_revenue, default: 0))
    }
}

public struct AttributionTotals: Equatable, Sendable, Decodable {
    public var leads: Int, orders: Int, revenue: Double
    public init(leads: Int = 0, orders: Int = 0, revenue: Double = 0) { self.leads = leads; self.orders = orders; self.revenue = revenue }
    enum K: String, CodingKey { case leads, orders, revenue }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(leads: c.int(.leads, default: 0), orders: c.int(.orders, default: 0), revenue: c.double(.revenue, default: 0))
    }
}

public struct Attribution: Equatable, Sendable, Decodable {
    public var sources: [AttributionRow]
    public var unattributed: Unattributed
    public var totals: AttributionTotals
    public init(sources: [AttributionRow] = [], unattributed: Unattributed = Unattributed(), totals: AttributionTotals = AttributionTotals()) {
        self.sources = sources; self.unattributed = unattributed; self.totals = totals
    }
    enum K: String, CodingKey { case sources, unattributed, totals }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(sources: c.list(.sources), unattributed: c.object(.unattributed) ?? Unattributed(), totals: c.object(.totals) ?? AttributionTotals())
    }
}

// ── Snapshots: orders written back as the wire has them ─────────────────────

extension OrderItem: Codable {
    enum K: String, CodingKey { case name, qty, unit, total, sku }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(name: c.string(.name, default: ""), qty: c.double(.qty, default: 0), unit: c.double(.unit, default: 0),
                  total: c.double(.total, default: 0), sku: c.string(.sku))
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encode(name, forKey: .name); try c.encode(qty, forKey: .qty); try c.encode(unit, forKey: .unit); try c.encode(total, forKey: .total)
        try c.encodeIfPresent(sku, forKey: .sku)
    }
}

extension Order: Encodable {
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encode(id, forKey: .id); try c.encode(waId, forKey: .wa_id)
        try c.encodeIfPresent(sessionId, forKey: .session_id); try c.encodeIfPresent(eventType, forKey: .event_type)
        try c.encode(items, forKey: .items); try c.encode(subtotal, forKey: .subtotal); try c.encode(currency, forKey: .currency)
        try c.encode(rawStatus, forKey: .status)
        try c.encodeIfPresent(paymentStatus, forKey: .payment_status); try c.encodeIfPresent(fulfillmentStatus, forKey: .fulfillment_status)
        try c.encodeIfPresent(replyText, forKey: .reply_text); try c.encode(channel, forKey: .channel); try c.encodeIfPresent(state, forKey: .state)
        try c.encode(createdAt, forKey: .created_at); try c.encodeIfPresent(updatedAt, forKey: .updated_at)
        try c.encodeIfPresent(contactName, forKey: .contact_name); try c.encodeIfPresent(contactPhone, forKey: .contact_phone)
        try c.encodeIfPresent(hubOrderId, forKey: .hub_order_id); try c.encodeIfPresent(hubOrderNumber, forKey: .hub_order_number)
        try c.encodeIfPresent(hubPushStatus, forKey: .hub_push_status); try c.encodeIfPresent(hubLastError, forKey: .hub_last_error)
        try c.encodeIfPresent(hubPublicToken, forKey: .hub_public_token); try c.encodeIfPresent(hubPublicUrl, forKey: .hub_public_url)
        try c.encodeIfPresent(hubStatus, forKey: .hub_status); try c.encodeIfPresent(hubPaymentStatus, forKey: .hub_payment_status)
    }
}
