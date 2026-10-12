import Foundation
@testable import NeemaCore

/// Two maps, the right one winning (Kotlin's `Map.plus`).
func + (lhs: [String: JSONValue], rhs: [String: JSONValue]) -> [String: JSONValue] { lhs.merging(rhs) { $1 } }

/// Orders, deals, planned actions and leads for the Orders / Deals / Leads
/// screens, built from what the backend handlers actually put on the wire
/// (Android `SalesFixtures`). Each builder cites its handler.
///
/// Serialisation facts these fixtures reproduce:
///  - Timestamps come from `timestamptz` columns, so Python's `isoformat()`
///    prints `2026-03-14T09:30:00.123456+00:00` — an explicit offset, six
///    fractional digits, and no fraction at all when the microseconds are 0.
///  - A `Numeric(12,2)` column (`subtotal`, `hub_total`) reaches the client
///    through FastAPI's `jsonable_encoder`, whose `decimal_encoder` turns
///    `Decimal("9800.00")` into the float `9800.0`.
///  - `list_orders` returns bare ORM rows: EVERY column is present (null when
///    unset), and nothing that isn't a column (no `contact_name`).
enum SalesFixtures {
    // ── wire helpers ────────────────────────────────────────────────────────

    private static func parts(_ d: Date) -> (secs: Int64, micros: Int64) {
        let total = Int64((d.timeIntervalSince1970 * 1_000_000).rounded())
        let secs = Int64((Double(total) / 1_000_000).rounded(.down))
        return (secs, total - secs * 1_000_000)
    }

    private static func stamp(_ d: Date, offset: String) -> String {
        let p = parts(d)
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let c = cal.dateComponents([.year, .month, .day, .hour, .minute, .second], from: Date(timeIntervalSince1970: Double(p.secs)))
        let base = String(format: "%04d-%02d-%02dT%02d:%02d:%02d", c.year!, c.month!, c.day!, c.hour!, c.minute!, c.second!)
        return (p.micros == 0 ? base : base + String(format: ".%06d", p.micros)) + offset
    }

    /// Python `datetime.isoformat()` of an aware UTC datetime (asyncpg hands back tz=UTC).
    static func pyIso(_ d: Date) -> String { stamp(d, offset: "+00:00") }

    /// The same for a NAIVE datetime (`datetime.utcnow()`): no offset at all.
    static func pyNaive(_ d: Date) -> String { stamp(d, offset: "") }

    /// `minutes` ago, as the server prints it (with microseconds). The sub-second
    /// part is taken OFF, never added, so a label never flips with machine speed.
    static func ago(_ minutes: Int64) -> String { pyIso(AppClock.date().addingTimeInterval(-Double(minutes) * 60 - 0.123456)) }

    static func inHours(_ h: Int64, extraMin: Int64 = 20) -> String {
        pyIso(AppClock.date().addingTimeInterval(Double(h * 60 + extraMin) * 60 + 0.654321))
    }

    /// A fixed creation time for the order detail (its "Date" cell prints the day); 0 µs → no fraction.
    static let FIXED_AT = "2026-03-14T09:30:00+00:00"

    static func s(_ v: String?) -> JSONValue { v.map { .string($0) } ?? .null }
    static func n(_ v: Double?) -> JSONValue { v.map { .number($0) } ?? .null }
    static func obj(_ pairs: [(String, JSONValue)]) -> JSONValue { .object(Dictionary(pairs, uniquingKeysWith: { $1 })) }

    // ── Orders ──────────────────────────────────────────────────────────────

    /// An n8n (Tier 1) cart line — n8n_bridge.py `upsert_order_event` stores
    /// `OrderEventDto.items` verbatim, in the `{name, qty, unit, total, sku}`
    /// shape the web's `ApiOrder` was written against.
    static func legacyLine(_ name: String, _ qty: Int, _ unit: Int, _ sku: String? = nil) -> JSONValue {
        obj([("name", .string(name)), ("qty", .number(Double(qty))), ("unit", .number(Double(unit))), ("total", .number(Double(qty * unit))), ("sku", s(sku))])
    }

    /// A Tier 2 cart line — agent/tools.py `_cart_update` rows, persisted as
    /// `OrderEvent.items` by `create_order`: `unit_price`, no `unit`, no `total`.
    static func agentLine(_ name: String, _ qty: Int, _ unitPrice: Double, _ sku: String = "", productId: Int = 412) -> JSONValue {
        obj([
            ("hub_product_id", .number(Double(productId))), ("name", .string(name)), ("sku", .string(sku)), ("qty", .number(Double(qty))),
            ("unit_price", .number(unitPrice)), ("price_usd", .number(unitPrice / 130.0)),
            ("prices", obj([("KES", .number(unitPrice)), ("USD", .number(unitPrice / 130.0))])),
            ("in_stock", .bool(true)), ("made_to_order", .bool(false)),
        ])
    }

    /// One row of GET /admin/orders — admin.py `list_orders` returns
    /// `select(OrderEvent)` rows through `jsonable_encoder`: every column of
    /// models/order_event.py, in the model's defaults unless set.
    static func order(
        _ id: String, _ waId: String, _ status: String, _ subtotal: Double,
        items: [JSONValue]? = nil, channel: String = "whatsapp", createdAt: String? = nil, eventType: String? = "confirmed",
        currency: String = "KES", paymentStatus: String = "unpaid", fulfillmentStatus: String = "pending",
        replyText: String? = nil, sessionId: String? = nil, hub: [String: JSONValue] = [:]
    ) -> String {
        let created = createdAt ?? ago(60)
        let lines = items ?? [legacyLine("Clergy Shirt — Black, 16 inch", 1, Int(subtotal), "CS-BLK-16")]
        let tail = String(waId.suffix(12))
        let person = "5b0e6a52-3c1d-4f7e-9a44-" + String(repeating: "0", count: max(0, 12 - tail.count)) + tail
        var row: [String: JSONValue] = [
            "id": .string(id), "wa_id": .string(waId), "person_id": .string(person),
            "session_id": s(sessionId), "event_type": s(eventType), "items": .array(lines),
            "subtotal": .number(subtotal), "currency": .string(currency), "status": .string(status),
            "payment_status": .string(paymentStatus), "fulfillment_status": .string(fulfillmentStatus),
            "reply_text": s(replyText), "channel": .string(channel), "state": .object([:]),
            "created_at": .string(created), "updated_at": .string(created),
            "hub_order_id": .null, "hub_order_number": .null, "hub_push_status": .null,
            "hub_payment_url": .null, "hub_currency": .null, "hub_total": .null,
            "hub_last_error": .null, "hub_pushed_at": .null, "hub_public_url": .null,
            "hub_public_token": .null, "short_ref": .null, "hub_status": .null,
            "hub_payment_status": .null, "hub_fulfillment_status": .null, "hub_status_at": .null,
        ]
        for (k, v) in hub { row[k] = v }
        return JSONValue.object(row).text
    }

    /// The hub columns agent/tools.py `create_order` sets on a pushed order.
    static func pushed(_ number: Int, _ total: Double, at: String = FIXED_AT, withToken: Bool = true) -> [String: JSONValue] {
        var m: [String: JSONValue] = [
            "hub_order_id": .number(Double(number)), "hub_order_number": .string("BH-\(number)"), "hub_push_status": .string("pushed"),
            "hub_currency": .string("KES"), "hub_total": .number(total), "hub_pushed_at": .string(at),
        ]
        if withToken {
            m["hub_public_token"] = .string("tok\(number)")
            m["hub_public_url"] = .string("https://hub.bethanyhouse.co.ke/order/tok\(number)")
            m["short_ref"] = .string("r\(number)")
        }
        return m
    }

    /// What services/hub_events.py `_mirror_order_state` writes when the hub
    /// reports: `hub_status` / `hub_payment_status` / `hub_fulfillment_status`
    /// + `hub_status_at` (never our own `status`).
    static func mirrored(_ status: String, _ payment: String? = nil, _ fulfillment: String? = nil, at: String = FIXED_AT) -> [String: JSONValue] {
        ["hub_status": .string(status), "hub_payment_status": s(payment), "hub_fulfillment_status": s(fulfillment), "hub_status_at": .string(at)]
    }

    /// The order detail's subject: an n8n order pushed to the hub by
    /// n8n_bridge.py `_maybe_push_order_to_hub` (legacy priced lines), then
    /// mirrored as processing/paid by the hub, with the reply Neema sent.
    static let linkedOrder = order(
        "254712345678_1773480600000", "254712345678", "confirmed", 9800.0,
        items: [
            legacyLine("Clergy Shirt — Black, 16 inch", 2, 3500, "CS-BLK-16"),
            legacyLine("Roman Collar Tab", 4, 250, "RC-TAB"),
            legacyLine("Delivery — Nyeri", 1, 1800),
        ],
        createdAt: FIXED_AT,
        replyText: "Asante Father! Your order BH-1042 is confirmed — we deliver to Nyeri on Friday.",
        sessionId: "254712345678_1773480000",
        hub: pushed(1042, 9800.0) + mirrored("processing", "paid", "unfulfilled")
    )

    /// An order the agent placed (agent/tools.py `create_order`): status
    /// "pending", Tier 2 lines that carry `unit_price` only.
    static let agentOrder = order(
        "254799111222_1773484200000", "254799111222", "pending", 145000.0,
        items: [agentLine("Mitre — Gold embroidered", 1, 85000.0, "MIT-GLD"), agentLine("Cope — Festal white", 1, 60000.0, "COP-WHT")],
        createdAt: FIXED_AT, hub: pushed(1050, 145000.0)
    )

    /// A cart the hub refused: n8n_bridge.py `_save(hub_push_status="failed", hub_last_error=str(exc)[:500])`.
    static let failedOrder = order(
        "254722000111_1773480600000", "254722000111", "open", 12500.0,
        items: [legacyLine("Cassock — Purple, L", 1, 12500, "CAS-PUR-L")],
        createdAt: FIXED_AT,
        hub: ["hub_push_status": .string("failed"), "hub_last_error": .string("Variant CAS-PUR-L is out of stock in the hub (0 available)")]
    )

    /// The list's first page: every status, hub states, channels, both line shapes, a cart snapshot.
    static var orders: [String] {
        [
            order("o1", "254712345678", "confirmed", 8000.0,
                  items: [legacyLine("Clergy Shirt — Black, 16 inch", 2, 3500, "CS-BLK-16"), legacyLine("Roman Collar Tab", 4, 250), legacyLine("Stole — Green", 1, 0)],
                  createdAt: ago(45), hub: pushed(1042, 8000.0) + mirrored("processing")),
            order("o2", "254722000111", "open", 12500.0, items: [legacyLine("Cassock — Purple, L", 1, 12500)], createdAt: ago(180),
                  hub: ["hub_push_status": .string("failed"), "hub_last_error": .string("Variant out of stock in hub")]),
            order("o3", "255754333222", "delivered", 4800.0, items: [legacyLine("Stole — Green", 1, 4800)], createdAt: ago(60 * 30),
                  hub: pushed(1031, 4800.0, withToken: false) + mirrored("completed", "paid", "fulfilled")),
            order("o4", "254700999888", "cancelled", 18000.0, items: [agentLine("Alb — White, M", 3, 6000.0)], channel: "instagram", createdAt: ago(60 * 72)),
            // An n8n cart snapshot: no lines, status "open", event_type "cart".
            order("o5", "254733444555", "open", 3500.0, items: [], channel: "whatsapp", createdAt: ago(60 * 5), eventType: "cart"),
            order("o6", "260977123456", "pending", 1450.0,
                  items: [agentLine("Mitre — Gold embroidered", 1, 850.0), agentLine("Cope — Festal white", 1, 600.0)],
                  channel: "messenger", createdAt: ago(60 * 8), currency: "ZMW",
                  hub: pushed(1050, 1450.0) + ["hub_currency": .string("ZMW")] + mirrored("shipped")),
        ]
    }

    /// 100 orders: seven pages of fifteen, so the pager windows.
    static var manyOrders: [String] {
        (1...100).map { i in
            let st = ["open", "confirmed", "delivered", "cancelled"][i % 4]
            return order("m\(i)", "2547" + String(String(10_000_000 + i * 7919).prefix(8)), st, 1000.0 * Double(i), createdAt: ago(Int64(i) * 37))
        }
    }

    static func ordersJson(_ list: [String]) -> String { "[" + list.joined(separator: ",") + "]" }

    /// PATCH /admin/orders/{id} — admin.py `update_order` sets the allowed
    /// keys and returns the same ORM row. `updated_at`'s Python-side
    /// `onupdate=datetime.utcnow` is what the instance holds after the flush,
    /// so it comes back NAIVE (no offset), unlike every other timestamp.
    static func patchedOrder(_ id: String, _ status: String) -> String {
        order(id, "254700000000", status, 1000.0, createdAt: FIXED_AT,
              hub: ["updated_at": .string(pyNaive(AppClock.date().addingTimeInterval(0.25)))])
    }

    // ── Deals & planned actions ─────────────────────────────────────────────

    /// GET /admin/deals — crm.py `list_deals`: `{"deals": [...]}`.
    static var deals: String {
        """
        {"deals":[
          {"id":"d1","conversation_id":"c1","customer":"Fr. Peter Kamau","wa_id":"254712345678","channel":"whatsapp","title":"Clergy Shirt — Black, 16 inch",
           "items":[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"price":null}],"stage":"proposal","blocking":"Neema owes the customer: confirm the Nyeri delivery date",
           "next_action":{"kind":"follow_up","owner":"ai","due_at":"\(inHours(3))","note":"confirm the Nyeri delivery date"},"guidance":"Offer free delivery to Nyeri","status":"open","updated_at":"\(ago(12))"},
          {"id":"d2","conversation_id":"c2","customer":"Rev. Mary Achieng","wa_id":"254722000111","channel":"messenger","title":"Cassock — Purple, L",
           "items":[],"stage":"qualified","blocking":null,"next_action":null,"guidance":null,"status":"open","updated_at":"\(ago(90))"},
          {"id":"d3","conversation_id":"c6","customer":"Deacon James Mwangi","wa_id":"254733444555","channel":"whatsapp","title":"Made-to-measure alb for the ordination on the 12th — needs chest, sleeve and length",
           "items":[],"stage":"new","blocking":"Waiting on the customer (tonight) — he promised to send the measurements after choir practice","next_action":{"kind":"customer_promise","owner":"ai","due_at":"\(inHours(20))","note":"they said: tonight"},"guidance":null,"status":"open","updated_at":"\(ago(300))"},
          {"id":"d4","conversation_id":null,"customer":"Unknown","wa_id":null,"channel":null,"title":"Choir robes ×24",
           "items":[],"stage":"negotiation","blocking":null,"next_action":{"kind":"follow_up","owner":"ai","due_at":"\(ago(30))","note":"send the robe quote"},"guidance":null,"status":"open","updated_at":"\(ago(60 * 26))"}
        ]}
        """
    }

    /// GET /admin/deals?status=won — the same row shape.
    static var wonDeals: String {
        """
        {"deals":[
          {"id":"w1","conversation_id":"c7","customer":"St. Mark's","wa_id":"254700111222","channel":"whatsapp","title":"Choir robes","items":[],"stage":"won","blocking":null,"next_action":null,"guidance":null,"status":"won","updated_at":"\(ago(600))"},
          {"id":"w2","conversation_id":null,"customer":"Unknown","wa_id":null,"channel":null,"title":null,"items":[],"stage":"won","blocking":null,"next_action":null,"guidance":null,"status":"won","updated_at":null}
        ]}
        """
    }

    /// GET /admin/actions — crm.py `list_actions`: `{"actions": [...]}`,
    /// `due_at` is never null (a NOT NULL column), `created_by` is the model default "ai".
    static var actions: String {
        """
        {"actions":[
          {"id":"x1","deal_id":"d1","conversation_id":"c1","due_at":"\(ago(20))","kind":"follow_up","reason":"Neema promised: confirm Friday delivery to Nyeri",
           "draft":"Hello Father Peter 🙏 Just confirming — we can deliver both shirts to Nyeri by Friday. Shall I send the M-Pesa details?","status":"needs_approval","created_by":"ai"},
          {"id":"x2","deal_id":"d3","conversation_id":"c6","due_at":"\(inHours(5))","kind":"customer_promise","reason":"Customer said they'd respond (tonight) — warm check-in if they haven't",
           "draft":null,"status":"planned","created_by":"ai"}
        ]}
        """
    }

    // ── Leads ───────────────────────────────────────────────────────────────

    /// crm.py `_customer_tier`.
    private static func tier(orders: Int, spent: Double, daysSinceLast: Int?) -> (String, String) {
        let dsl = daysSinceLast ?? 0
        let t: String
        if orders == 0 { t = "prospect" }
        else if orders >= 3 && dsl > 120 { t = "at_risk" }
        else if spent >= 500_000 || orders >= 20 { t = "vip" }
        else if orders >= 5 { t = "loyal" }
        else if orders <= 1 { t = "new" }
        else { t = "regular" }
        let labels = ["prospect": "Prospect", "new": "New", "regular": "Regular", "loyal": "Loyal", "vip": "VIP", "at_risk": "At risk"]
        return (t, labels[t]!)
    }

    /// One row of GET /admin/leads — crm.py `list_leads` (a bare array).
    static func lead(
        _ id: String, _ waId: String, _ name: String?, _ stage: String, _ score: Int, spent: Double = 0.0, orders: Int = 0,
        channels: [String] = ["whatsapp"], tags: JSONValue = .array([]), seen: String?? = nil,
        notes: String? = nil, email: String? = nil, location: String? = nil, phone: String?? = nil,
        daysSinceLast: Int?? = nil, avgInterval: Double?? = nil
    ) -> String {
        let seenAt: String? = seen ?? ago(30)
        let phoneV: String? = phone ?? waId
        let dsl: Int? = daysSinceLast ?? (orders > 0 ? 12 : nil)
        let avg: Double? = avgInterval ?? (orders >= 2 ? 30.5 : nil)
        let (t, label) = tier(orders: orders, spent: spent, daysSinceLast: dsl)
        let cadence: JSONValue = avg.map { .string("about every \(max(1, Int(($0 / 7).rounded()))) weeks") } ?? .null
        return obj([
            ("id", .string(id)), ("wa_id", .string(waId)), ("name", s(name)), ("phone", s(phoneV)), ("email", s(email)), ("location", s(location)),
            ("lead_stage", .string(stage)), ("lead_score", .number(Double(score))), ("tier", .string(t)), ("tier_label", .string(label)),
            ("tags", tags), ("channels", .array(channels.map { .string($0) })), ("total_orders", .number(Double(orders))),
            ("total_spent", .number(orders == 0 ? 0 : spent)),
            ("buying_rhythm", obj([("days_since_last", n(dsl.map(Double.init))), ("avg_interval_days", n(avg)), ("cadence_label", cadence), ("overdue", .bool(false))])),
            ("last_seen_at", s(seenAt)), ("notes", s(notes)),
        ]).text
    }

    static var leads: [String] {
        [
            lead("u1", "254712345678", "Fr. Peter Kamau", "proposal", 86, spent: 24500.0, orders: 3,
                 channels: ["whatsapp", "facebook"], tags: .array(["vip", "clergy", "repeat-buyer", "nyeri"].map { .string($0) }),
                 notes: "Buys for the whole parish. Prefers delivery on Fridays.", email: "peter@acknyeri.org", location: "Nyeri"),
            lead("u2", "254722000111", "Rev. Mary Achieng", "qualified", 55, channels: ["messenger"], seen: .some(ago(9))),
            lead("u3", "255754333222", nil, "new", 12, seen: .some(ago(34))),
            // An Instagram handle: not a plausible phone, so `phone` is null.
            lead("u4", "17840000000000001", "Sr. Lucy Njeri", "contacted", 38, channels: ["instagram"], tags: .array([.string("convent")]), phone: .some(nil)),
            lead("u5", "254733444555", "Deacon James Mwangi", "negotiation", 71, spent: 18000.0, orders: 1,
                 channels: ["whatsapp", "sms", "email"], seen: .some(ago(60 * 5))),
            // A custom stage: stored as the operator typed it, read back lower-cased by normalise_stage.
            lead("u6", "254700111222", "St. Mark's Cathedral Choir", "measuring", 64, spent: 52000.0, orders: 2),
            lead("u7", "254799111222", "Bishop Samuel Kariuki", "won", 97, spent: 145000.0, orders: 6, tags: .array([.string("vip")])),
            lead("u8", "254700999888", "Mr. Otieno", "lost", 20, seen: .some(nil)),
        ]
    }

    static func leadsJson(_ list: [String]? = nil) -> String { "[" + (list ?? leads).joined(separator: ",") + "]" }

    private static let statusRegex = try! NSRegularExpression(pattern: "\"status\":\"([a-z]+)\"")

    /// The `status` a PATCH body asks for ("open" when it says nothing).
    static func statusIn(_ body: String?) -> String {
        guard let b = body, let m = statusRegex.firstMatch(in: b, range: NSRange(b.startIndex..., in: b)), let r = Range(m.range(at: 1), in: b) else { return "open" }
        return String(b[r])
    }

    /// Registers every route these screens call, over `Fixtures.withFixtures()`'s base set.
    static func install(_ f: FakeNeema, orderList: [String]? = nil) {
        // admin.py list_orders
        f.on("GET", "/admin/orders", body: ordersJson(orderList ?? orders))
        // admin.py update_order — the updated OrderEvent row (naive updated_at).
        f.on("PATCH", "/admin/orders/[^/]+") { r, body in (200, patchedOrder(r.url.lastPathComponent, statusIn(body))) }
        // crm.py list_deals / update_deal
        f.on("GET", "/admin/deals") { r, _ in (200, r.param("status") == "won" ? wonDeals : deals) }
        f.on("PATCH", "/admin/deals/[^/]+", body: #"{"ok":true}"#)
        // crm.py list_actions / approve_action / veto_action
        f.on("GET", "/admin/actions", body: actions)
        f.on("POST", "/admin/actions/[^/]+/approve") { _, body in
            let draft = JSONValue.parse(body ?? "{}")?.objectValue?["draft"]?.stringValue ?? "Hello 🙏"
            return (200, JSONValue.object(["ok": .bool(true), "sent": .string(draft)]).text)
        }
        f.on("POST", "/admin/actions/[^/]+/veto", body: #"{"ok":true}"#)
        // crm.py list_leads / update_lead
        f.on("GET", "/admin/leads", body: leadsJson())
        f.on("PATCH", "/admin/leads/[^/]+", body: #"{"ok":true}"#)
        // crm.py get_pipeline_stages — labels as the operator typed them.
        f.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages":["Measuring"]}"#)
    }

    /// A signed-in agent whose role grants `perms` only (read-only variants).
    static func agentsWithRole(_ perms: [String]) -> String {
        "[" + Fixtures.agentRow(Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", "agent", true, false, 0, 1000, 1,
                                customRole: "viewer", roleName: "Viewer", roleColor: "#94a3b8",
                                rolePermissions: "[" + perms.map { "\"\($0)\"" }.joined(separator: ",") + "]") + "]"
    }

    static func installReadOnly(_ f: FakeNeema, perms: [String]) {
        let agents = agentsWithRole(perms)
        f.on("GET", "/admin/agents", body: agents)
        f.on("GET", "/admin/me", body: String(agents.dropFirst().dropLast()))
    }
}

/// A busy shop, for the Orders / Leads / Deals stress tests — a thousand
/// orders, five hundred leads across every column and a queue of two hundred
/// planned actions. Every row is built by the same wire-true builders as
/// `SalesFixtures`; the values cycle deterministically (no randomness), so a
/// failing assertion is reproducible. (Android `SalesStressFixtures`; its
/// thousand-call log arrives with the calls screen.)
enum SalesStressFixtures {
    private static let names = [
        "Fr. Peter Kamau", "Rev. Mary Achieng", "Sr. Lucy Njeri", "Deacon James Mwangi", "Bishop Samuel Kariuki",
        "Canon Joseph Kiprono", "Mrs. Faith Chebet", "Dr. Samuel Mutua", "Mama 🌸 Njeri", "Bro. Kevin Ouma",
    ]
    private static let statuses = ["pending", "confirmed", "delivered", "cancelled"]
    private static let channels = ["whatsapp", "messenger", "instagram", "facebook", "email", "sms"]

    static func orderId(_ i: Int) -> String { String(format: "0a0b0c0d-0000-4000-8000-%012d", i) }
    static func waId(_ i: Int) -> String { String(format: "2547%08d", 10_000_000 + i * 37) }

    /// `n` orders, newest first, statuses cycling pending → confirmed → delivered → cancelled.
    static func orders(_ n: Int = 1_000) -> [String] {
        (0..<n).map { i in
            SalesFixtures.order(
                orderId(i), waId(i), statuses[i % statuses.count], orderSubtotal(i),
                items: [SalesFixtures.legacyLine("Clergy Shirt — Black, \(14 + i % 6) inch", 1 + i % 3, 1_000 + (i % 50) * 250, "CS-\(i)")],
                channel: channels[i % channels.count], createdAt: SalesFixtures.ago(5 + Int64(i) * 7)
            )
        }
    }

    /// Pure sums of `orders`' figures, to check the screen's arithmetic against.
    static func orderSubtotal(_ i: Int) -> Double { 1_000.0 + Double(i % 50) * 250.0 }
    static func orderStatus(_ i: Int) -> String { statuses[i % statuses.count] }

    static let leadStages = ["new", "contacted", "qualified", "proposal", "negotiation", "measuring", "won", "lost"]

    static func leadId(_ i: Int) -> String { String(format: "u%04d", i) }

    /// `n` leads spread over every canonical column plus the custom "Measuring", score-descending as `list_leads` sorts.
    static func leads(_ n: Int = 500) -> [String] {
        (0..<n).map { i in
            let orders = i % 5
            return SalesFixtures.lead(
                leadId(i), waId(i), i % 11 == 0 ? nil : names[i % names.count] + " \(i)",
                leadStages[i % leadStages.count], 100 - (i * 100 / n),
                spent: orders == 0 ? 0.0 : 2_500.0 * Double(orders), orders: orders,
                channels: Array(channels.prefix(1 + i % 3)), tags: .array(Array(["parish", "t\(i)"].prefix(1 + i % 2)).map { .string($0) }),
                seen: .some(SalesFixtures.ago(3 + Int64(i)))
            )
        }
    }

    static func actionId(_ i: Int) -> String { String(format: "x%04d", i) }

    /// One row of GET /admin/actions: every third needs approval, the rest are scheduled.
    static func actionRow(_ i: Int) -> String {
        let needs = i % 3 == 0
        let draft = i % 4 == 0 ? "null" : "\"Hello \(names[i % names.count]) 🙏 — checking in on order #\(i).\""
        return """
        {"id":"\(actionId(i))","deal_id":"d\(i)","conversation_id":"c\(i)","due_at":"\(needs ? SalesFixtures.ago(5) : SalesFixtures.inHours(1 + Int64(i % 40)))",
          "kind":"\(i % 2 == 0 ? "follow_up" : "customer_promise")","reason":"Follow up #\(i): confirm the delivery date for the parish order",
          "draft":\(draft),"status":"\(needs ? "needs_approval" : "planned")","created_by":"ai"}
        """
    }

    /// crm.py `list_actions`' envelope around `rows`.
    static func actionsJson(_ rows: [String]) -> String { "{\"actions\":[" + rows.joined(separator: ",") + "]}" }

    /// GET /admin/actions with `n` rows.
    static func actions(_ n: Int = 200) -> String { actionsJson((0..<n).map(actionRow)) }

    /// GET /admin/deals with `n` open deals over the three columns (and a stray stage that lands under New).
    static func deals(_ n: Int = 60) -> String {
        "{\"deals\":[" + (0..<n).map { i -> String in
            let stage = ["new", "qualified", "proposal", "negotiation"][i % 4]
            let blocking = i % 3 == 0 ? "\"Waiting on the measurements\"" : "null"
            return """
            {"id":"d\(i)","conversation_id":"c\(i)","customer":"\(names[i % names.count])","wa_id":"\(waId(i))","channel":"whatsapp",
              "title":"Order #\(i) — clergy shirts","items":[],"stage":"\(stage)","blocking":\(blocking),
              "next_action":null,"guidance":null,"status":"open","updated_at":"\(SalesFixtures.ago(10 + Int64(i)))"}
            """
        }.joined(separator: ",") + "]}"
    }

    /// Every sales route, with the stress data.
    static func install(_ f: FakeNeema, orders n: Int = 1_000, leads l: Int = 500, actions a: Int = 200) {
        SalesFixtures.install(f, orderList: orders(n))
        f.on("GET", "/admin/leads", body: SalesFixtures.leadsJson(leads(l)))
        f.on("GET", "/admin/actions", body: actions(a))
        f.on("GET", "/admin/deals") { r, _ in (200, r.param("status") == "won" ? SalesFixtures.wonDeals : deals()) }
    }
}

/// The permission personas, as the server describes them: the signed-in
/// agent's /admin/agents row (routers/admin.py `list_agents`, where the custom
/// role's and the per-agent permissions are joined in) and the bare ORM row
/// /admin/me returns (no permission columns at all). (Android `SalesPersona`.)
enum SalesPersona: CaseIterable {
    case superuser, admin, legacyAgent, legacyReadonly
    /// A custom "Sales" role: conversations and orders, no leads.
    case salesRole
    /// The Sales role, overridden per agent to view-only leads and conversations.
    case override
    /// An empty override on a readonly agent: `[]` falls back to the legacy readonly set.
    case emptyOverride

    var role: String {
        switch self {
        case .superuser, .admin: return "admin"
        case .legacyAgent, .salesRole, .override: return "agent"
        case .legacyReadonly, .emptyOverride: return "readonly"
        }
    }
    var superuser: Bool { self == .superuser }
    /// The joined custom role's permissions (`role_permissions`), JSON or "null".
    var rolePermissions: String {
        switch self {
        case .salesRole, .override: return #"["view_conversations","reply_conversations","view_orders","manage_orders"]"#
        default: return "null"
        }
    }
    /// The per-agent override (`custom_permissions`), JSON or "null".
    var customPermissions: String {
        switch self {
        case .override: return #"["view_conversations","view_leads"]"#
        case .emptyOverride: return "[]"
        default: return "null"
        }
    }
    var roleName: String? { self == .salesRole || self == .override ? "Sales" : nil }

    /// The persona's own row in GET /admin/agents.
    func agentRow() -> String {
        Fixtures.agentRow(Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", role, true, superuser, 4, 60 * 24 * 200, 1,
                          customRole: roleName?.lowercased(), roleName: roleName, roleColor: roleName.map { _ in "#3b82f6" },
                          rolePermissions: rolePermissions, customPermissions: customPermissions)
    }

    /// GET /admin/me: the ORM row — role and superuser flag only.
    func meOrm() -> String {
        Fixtures.meOrm.replacingOccurrences(of: "\"role\":\"admin\"", with: "\"role\":\"\(role)\"")
            .replacingOccurrences(of: "\"is_superuser\":true", with: "\"is_superuser\":\(superuser)")
    }

    /// The persona as the shell resolves it (`ShellRules.access` over its own team row).
    var agent: Agent { try! NeemaJSON.decode(Agent.self, from: agentRow()) }
}

enum SalesPersonaFixtures {
    /// Serve `p` as the signed-in agent (on top of `SalesFixtures.install`).
    static func install(_ f: FakeNeema, _ p: SalesPersona) {
        f.on("GET", "/admin/agents", body: "[\(p.agentRow())]")
        f.on("GET", "/admin/me", body: p.meOrm())
    }

    /// The server refusing everything a Sales screen writes, with FastAPI's
    /// `{"detail": …}` — what a future role check would send. None of these
    /// routes checks a permission today (crm.py / admin.py only depend on
    /// `get_current_agent`), so this exists to prove the 403 path.
    static func refuseWrites(_ f: FakeNeema, detail: String? = "Not allowed for your role") {
        let body = detail.map { "{\"detail\":\"\($0)\"}" } ?? "{}"
        f.on("PATCH", "/admin/orders/[^/]+", code: 403, body: body)
        f.on("PATCH", "/admin/deals/[^/]+", code: 403, body: body)
        f.on("POST", "/admin/actions/[^/]+/approve", code: 403, body: body)
        f.on("POST", "/admin/actions/[^/]+/veto", code: 403, body: body)
        f.on("PATCH", "/admin/leads/[^/]+", code: 403, body: body)
    }
}
