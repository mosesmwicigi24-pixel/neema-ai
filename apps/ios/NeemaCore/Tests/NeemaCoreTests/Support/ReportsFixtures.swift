import Foundation
@testable import NeemaCore

/// Data for Reports / Analytics / Catalog, pinned to a FIXED "now" (Friday
/// 25 Sep 2026, 12:00 in Nairobi) so per-day charts, weekday labels and
/// "3h ago" texts never change from one day's run to the next (Android
/// `ReportsFixtures`). Every body is built from what the API handler actually
/// returns: Python `isoformat()` datetimes, Numeric columns as floats, the
/// exact keys each handler emits, and no keys it doesn't.
enum ReportsFixtures {
    static let NOW = PINNED
    static let NAIROBI = TimeZone(identifier: "Africa/Nairobi")!

    /// Nairobi for date formatting and the pinned clock; pair with `restoreTimeZone`.
    static func pinTimeZone() {
        AppClock.pin(to: NOW)
        Fmt.timeZone = NAIROBI
    }

    static func restoreTimeZone() {
        Fmt.timeZone = .current
        AppClock.reset()
    }

    /// The API's datetime `minutes` (and a fraction of a second) before NOW —
    /// rows carry microseconds; landing just before the minute keeps "2h ago" reading 2h.
    static func ago(_ minutes: Int64) -> String { SalesFixtures.pyIso(NOW.addingTimeInterval(-Double(minutes) * 60 - 0.123456)) }
    static let H: Int64 = 60
    static let D: Int64 = 24 * 60

    private static func q(_ s: String?) -> String { s.map { "\"\($0)\"" } ?? "null" }

    /// One inbox row — admin.py `_conversation_rows()`, the shape both the bare
    /// list (no `limit`) and each page's `items` carry. Every key it emits.
    static func conv(
        _ id: String, _ name: String?, _ waId: String?, _ channel: String, _ mode: String, _ at: String?,
        agent: String? = nil, agentName: String? = nil, status: String = "open", created: String? = nil,
        person: String? = nil, externalId: String?? = nil, preview: String = "Asante sana",
        country: String?? = nil, tags: [String] = [], ordersCount: Int = 0, stage: String? = nil
    ) -> String {
        let createdAt = created ?? ago(90 * D)
        let ext: String? = externalId ?? waId
        let iso: String? = country ?? "KE"
        return """
        {"id":"\(id)","wa_id":\(q(waId)),"person_id":\(q(person)),"external_id":\(q(ext)),
        "intercept_mode":"\(mode)","assigned_agent_id":\(q(agent)),"assigned_agent_name":\(q(agentName)),
        "intercept_since":\(mode == "human" ? q(at) : "null"),"last_message_at":\(q(at)),
        "last_message":"\(preview)","last_message_preview":"\(preview)","status":"\(status)",
        "created_at":"\(createdAt)","updated_at":"\(at ?? createdAt)","name":\(q(name)),"avatar_url":null,
        "country_iso":\(q(iso)),"flag_url":\(iso.map { "\"https://flagcdn.com/\($0.lowercased()).svg\"" } ?? "null"),
        "channel":"\(channel)","unread":0,"orders_count":\(ordersCount),"lead_stage":\(q(stage)),
        "tags":[\(tags.map { "\"\($0)\"" }.joined(separator: ","))]}
        """
    }

    /// Every thread (the un-paged list Reports asks for), newest activity first as the handler sorts.
    static var conversations: [String] {
        [
            conv("r1", "Fr. Peter Kamau", "254712345678", "whatsapp", "human", ago(2 * H), agent: Fixtures.ME_ID,
                 agentName: "Moses Mwicigi", person: "p0000001-0000-4000-8000-000000000001", tags: ["clergy"], ordersCount: 2, stage: "negotiating"),
            conv("r2", "Rev. Mary Achieng", nil, "messenger", "ai", ago(1 * D + 3 * H), person: "p0000002-0000-4000-8000-000000000002",
                 externalId: .some("7012345678901234"), country: .some(nil)),
            conv("r3", nil, "255754333222", "whatsapp", "paused", ago(2 * D), country: .some("TZ")),
            conv("r4", "Sr. Lucy Njeri", nil, "instagram", "ai", ago(3 * D), status: "closed", externalId: .some("17840000000000001"), country: .some(nil)),
            conv("r5", "Deacon James Mwangi", "254733444555", "whatsapp", "human", ago(5 * D), agent: Fixtures.AGENT2_ID,
                 agentName: "Grace Wanjiru", person: "p0000005-0000-4000-8000-000000000005"),
            // A Facebook comment thread: no wa_id, the PSID is the handle.
            conv("r6", "Bishop Samuel Kariuki", nil, "facebook", "human", ago(12 * D), agent: Fixtures.AGENT2_ID,
                 agentName: "Grace Wanjiru", externalId: .some("6123456789012345"), preview: "How much is the cope?", country: .some(nil)),
            conv("r7", "St. Mark's Parish Office", "254711000999", "whatsapp", "ai", ago(20 * D)),
            // Outside 30 days, inside 90.
            conv("r8", "Fr. Joseph Otieno", "254722333444", "whatsapp", "ai", ago(45 * D), agent: Fixtures.ME_ID, agentName: "Moses Mwicigi"),
            // No messages yet: last_message_at is null and the preview empty; dates from created_at (the web's mapConversation).
            conv("r9", "New Enquiry", "254799888777", "whatsapp", "ai", nil, created: ago(4 * H), preview: ""),
        ]
    }

    /// admin.py `list_orders()` returns bare `OrderEvent` ORM rows: every column, nothing joined.
    static func order(_ id: String, _ waId: String, _ status: String, _ subtotal: Double, _ at: String, _ items: String,
                      channel: String = "whatsapp", hub: Int? = nil, payment: String = "unpaid") -> String {
        """
        {"id":"\(id)","wa_id":"\(waId)","person_id":null,"session_id":\(hub == nil ? "\"sess-\(id)\"" : "null"),
        "event_type":\(hub == nil ? "\"order_snapshot\"" : "\"confirmed\""),"items":\(items),"subtotal":\(subtotal),
        "currency":"KES","status":"\(status)","payment_status":"\(payment)","fulfillment_status":"pending","reply_text":null,
        "channel":"\(channel)","state":{},"created_at":"\(at)","updated_at":"\(at)",
        "hub_order_id":\(hub.map { "\($0)" } ?? "null"),"hub_order_number":\(hub.map { "\"BH-\($0)\"" } ?? "null"),
        "hub_push_status":\(hub != nil ? "\"pushed\"" : "null"),"hub_payment_url":null,"hub_currency":\(hub != nil ? "\"KES\"" : "null"),
        "hub_total":\(hub != nil ? "\(subtotal)" : "null"),"hub_last_error":null,"hub_pushed_at":\(hub != nil ? "\"\(at)\"" : "null"),
        "hub_public_url":null,"hub_public_token":null,"short_ref":null,
        "hub_status":null,"hub_payment_status":null,"hub_fulfillment_status":null,"hub_status_at":null}
        """
    }

    static func n8nLine(_ name: String, _ qty: Int, _ unit: Double) -> String { "{\"name\":\"\(name)\",\"qty\":\(qty),\"unit\":\(unit),\"total\":\(unit * Double(qty))}" }
    static func cartLine(_ name: String, _ qty: Int, _ unit: Double, _ product: Int, _ sku: String) -> String {
        "{\"hub_product_id\":\(product),\"name\":\"\(name)\",\"sku\":\"\(sku)\",\"qty\":\(qty),\"unit_price\":\(unit),\"price_usd\":null,\"prices\":{\"KES\":\(unit)},\"in_stock\":true,\"made_to_order\":false}"
    }

    static var orders: [String] {
        [
            order("o1", "254712345678", "confirmed", 8000.0, ago(1 * H), "[\(n8nLine("Clergy Shirt — Black, 16 inch", 2, 3500.0)),\(n8nLine("Roman Collar Tab", 4, 250.0))]", payment: "paid"),
            // The agent's own order: pushed to the hub, cart lines priced by unit_price (no unit / total).
            order("o2", "254722000111", "pending", 12500.0, ago(1 * D + 2 * H), "[\(cartLine("Cassock — Purple, L", 1, 12500.0, 502, "CAS-PUR-L"))]", channel: "messenger", hub: 1042),
            order("o3", "254733444555", "delivered", 18000.0, ago(3 * D), "[\(n8nLine("Alb — White, M", 3, 6000.0))]", payment: "paid"),
            order("o4", "254700111222", "cancelled", 9600.0, ago(4 * D), "[\(n8nLine("Stole — Green", 2, 4800.0))]"),
            // An n8n cart snapshot that never became an order: status "open" (shown as pending).
            order("o5", "254711000999", "open", 4800.0, ago(6 * D), "[\(n8nLine("Stole — Green", 1, 4800.0))]"),
            order("o6", "254733444555", "delivered", 3500.0, ago(10 * D), "[\(n8nLine("Clergy Shirt", 1, 3500.0))]", payment: "paid"),
            // Outside 30 days.
            order("o7", "254722333444", "delivered", 25000.0, ago(40 * D), "[\(n8nLine("Clergy Shirt", 1, 25000.0))]", payment: "paid"),
        ]
    }

    /// admin.py `overview_stats()`.
    static let stats = """
    {"open_conversations":128,"human_conversations":9,"ai_conversations":119,"active_agents":2,"total_agents":3,
      "total_revenue":1284500.0,"total_orders":284,"pending_orders":21,"delivered_orders":203,"confirmed_orders":48,"cancelled_orders":12,
      "in_stock_items":187,"total_items":214,
      "channel_breakdown":[{"channel":"whatsapp","count":96,"open":80},{"channel":"messenger","count":21,"open":15},
        {"channel":"facebook","count":70,"open":22},{"channel":"instagram","count":11,"open":9},{"channel":"web","count":3,"open":2}]}
    """

    /// crm.py `attribution()`.
    static let attribution = """
    {"sources":[
        {"source":"organic","post":null,"leads":77,"orders":30,"revenue":402000.0,"paid_revenue":377500.0,"post_title":null},
        {"source":"facebook","post":"104882331_1203","leads":42,"orders":11,"revenue":186000.0,"paid_revenue":152000.0,"post_title":"Easter vestments sale"},
        {"source":"instagram","post":"17999123456789012","leads":18,"orders":4,"revenue":51000.0,"paid_revenue":51000.0,"post_title":null}],
      "unattributed":{"orders":9,"revenue":64000.0,"paid_revenue":60000.0},
      "totals":{"leads":137,"orders":54,"revenue":703000.0}}
    """

    /// `GET /admin/catalog` with catalog_source=hub: hub_client `_map_product()` for every product.
    static let catalog = """
    [
      {"hub_product_id":501,"uuid":"9b1c7f10-0000-4000-8000-000000000501","sku":"CS-BLK","slug":"clergy-shirt","name":"Clergy Shirt",
       "category":"Clergy Apparel","price":3500.0,"price_kes":3500.0,"price_usd":27.0,"prices":{"KES":3500.0,"USD":27.0},"unit":"",
       "description":"Tab-collar clergy shirt, poly-cotton, long sleeve.","aliases":["clerical shirt","collar shirt","tab shirt","priest shirt"],
       "in_stock":true,"available_qty":1200,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"variable","is_producible":false,
       "measurements":[],"price_min_kes":3500.0,"price_max_kes":4200.0,"price_min_usd":27.0,"price_max_usd":32.5,
       "variants":[
         {"variant_id":1,"sku":"CS-BLK-15","name":"Black","attributes":{"Colour":"Black","Size":"15 inch"},"price_kes":3500.0,"price_usd":27.0,
          "prices":{"KES":3500.0,"USD":27.0},"is_default":true,"in_stock":true,"label":"Clergy Shirt — Black / 15 inch"},
         {"variant_id":2,"sku":"CS-BLK-16","name":"Black","attributes":{"Colour":"Black","Size":"16 inch"},"price_kes":3500.0,"price_usd":27.0,
          "prices":{"KES":3500.0,"USD":27.0},"is_default":false,"in_stock":true,"label":"Clergy Shirt — Black / 16 inch"},
         {"variant_id":3,"sku":"CS-BLU-16","name":"Blue Clergy Shirt","attributes":{"Colour":"Blue","Size":"16 inch"},"price_kes":4200.0,"price_usd":32.5,
          "prices":{"KES":4200.0,"USD":32.5},"is_default":false,"in_stock":true,"label":"Clergy Shirt — Blue / 16 inch"}]},
      {"hub_product_id":502,"uuid":"9b1c7f10-0000-4000-8000-000000000502","sku":"CAS-PUR","slug":"anglican-cassock",
       "name":"Anglican Double-Breasted Cassock with Cincture and Matching Buttons","category":"Clergy Vestments",
       "price":12500.0,"price_kes":12500.0,"price_usd":96.0,"prices":{"KES":12500.0,"USD":96.0},"unit":"",
       "description":"Anglican double-breasted cassock, wool blend, made to measure in any liturgical colour with a matching cincture.",
       "aliases":[],"in_stock":true,"available_qty":6,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":true,"measurements":[{"name":"Chest","unit":"cm","required":true}],"variants":[]},
      {"hub_product_id":503,"uuid":null,"sku":"OIL-50","slug":"anointing-oil-50ml","name":"Anointing Oil 50ml","category":"Anointing Oil",
       "price":650.0,"price_kes":650.0,"price_usd":null,"prices":{"KES":650.0},"unit":"","description":"Frankincense-scented olive oil.",
       "aliases":["holy oil"],"in_stock":false,"available_qty":0,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]},
      {"hub_product_id":504,"uuid":null,"sku":"WAF-500","slug":"communion-wafers-500","name":"Communion Wafers (500)","category":"Communion Wafers",
       "price":1800.0,"price_kes":1800.0,"price_usd":13.85,"prices":{"KES":1800.0,"USD":13.85},"unit":"","description":"White unleavened wafers, 35mm.",
       "aliases":["hosts"],"in_stock":true,"available_qty":null,
       "images":[{"url":"https://hub.test/img/broken.jpg","thumb":"https://hub.test/img/broken_thumb.webp","alt":"","primary":true,"sort":0}],
       "image_url":"https://hub.test/img/broken.jpg","thumbnail_url":"https://hub.test/img/broken_thumb.webp","product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]},
      {"hub_product_id":505,"uuid":null,"sku":"CUP-PF","slug":"prefilled-cups","name":"Prefilled Communion Cups","category":"Prefilled Cups",
       "price":45.0,"price_kes":45.0,"price_usd":null,"prices":{"KES":45.0},"unit":"","description":"",
       "aliases":[],"in_stock":true,"available_qty":35000,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]},
      {"hub_product_id":506,"uuid":null,"sku":"TRAY-1","slug":"communion-tray","name":"Communion Tray","category":"",
       "price":36000.0,"price_kes":36000.0,"price_usd":600.0,"prices":{"KES":36000.0,"USD":600.0},"unit":"","description":"Brass tray set.",
       "aliases":[],"in_stock":true,"available_qty":null,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]}
    ]
    """

    /// `GET /admin/catalog` when the hub is unreachable and no last-good copy exists: the local table, in-stock rows only.
    static let localCatalog = """
    [
      {"sku":"CS-BLK","name":"Clergy Shirt","category":"Clergy Apparel","price":3500.0,"unit":"piece",
       "description":"Tab-collar clergy shirt.","aliases":["clerical shirt"],"in_stock":true},
      {"sku":"TRAY-1","name":"Communion Tray","category":"","price":36000.0,"unit":"",
       "description":"","aliases":[],"in_stock":true}
    ]
    """

    /// admin.py `catalog_price_audit()` → services/price_audit `audit()`.
    static let audit = """
    {"currency_gaps":[
        {"name":"Communion Tray","category":"","kes":36000.0,"usd":600.0,"usd_expected":276.92,"factor":2.17},
        {"name":"Anglican Double-Breasted Cassock with Cincture and Matching Buttons","category":"Clergy Vestments","kes":12500.0,"usd":90.0,"usd_expected":96.15,"factor":0.94},
        {"name":"Communion Cup","category":"Communion Cups","kes":10.0,"usd":10.0,"usd_expected":0.08,"factor":129.87}],
      "per_piece":[{"name":"Prefilled Communion Cups","category":"Prefilled Cups","kes":45.0},{"name":"Communion Hosts","category":null,"kes":null}],
      "checked":6,"rate":130.0}
    """

    static let emptyAudit = #"{"currency_gaps":[],"per_piece":[],"checked":0,"rate":130.0}"#

    private static func humanPage(_ rows: [String]) -> String { "{\"items\":[\(rows.joined(separator: ","))],\"next_cursor\":null}" }

    /// Fr. Peter's second, AI-held (Messenger) thread shares r1's person.
    private static var siblingOfR1: String {
        conv("r1b", "Fr. Peter Kamau", nil, "messenger", "ai", ago(30), person: "p0000001-0000-4000-8000-000000000001",
             externalId: .some("7098765432109876"), country: .some(nil))
    }

    static func install(_ f: FakeNeema) {
        let convs = conversations
        f.on("GET", "/admin/conversations") { r, _ in
            if r.param("limit") == nil { return (200, "[\(convs.joined(separator: ","))]") }
            if r.param("tab") == "human" { return (200, humanPage(convs.filter { $0.contains("\"intercept_mode\":\"human\"") } + [siblingOfR1])) }
            return (200, "{\"items\":[\(convs.joined(separator: ","))],\"next_cursor\":null}")
        }
        f.on("GET", "/admin/orders", body: "[\(orders.joined(separator: ","))]")
        f.on("GET", "/admin/catalog", body: catalog)
        f.on("GET", "/admin/catalog/audit", body: audit)
        f.on("GET", "/admin/stats", body: stats)
        f.on("GET", "/admin/attribution", body: attribution)
    }

    /// The stress case for layout: a busy shop — the same handler shapes as `install`, with a long Swahili / emoji product.
    static func installBig(_ f: FakeNeema) {
        install(f)
        var big = catalog.trimmingCharacters(in: .whitespacesAndNewlines)
        big.removeLast()
        big += """
        ,{"hub_product_id":599,"uuid":null,"sku":"KAS-DHB-XL-HANDMADE-2026","slug":"kasula","name":"Kasula ya Kiaskofu — Dhahabu na Nyeupe, Imeshonwa kwa Mkono na Mafundi wa Nyeri ✝️🙏",
           "category":"Clergy Vestments","price":169000.0,"price_kes":169000.0,"price_usd":1300.0,"prices":{"KES":169000.0,"USD":1300.0},"unit":"",
           "description":"Vazi la sherehe kuu, lenye nakshi za dhahabu na bitana ya hariri.","aliases":["chasuble","kasula","vazi la askofu"],
           "in_stock":true,"available_qty":3,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"variable","is_producible":true,
           "measurements":[],"price_min_kes":169000.0,"price_max_kes":245000.0,"price_min_usd":1300.0,"price_max_usd":1884.6,"variants":[]}
        ]
        """
        f.on("GET", "/admin/catalog", body: big)
    }

    /// A backend with nothing in it (a fresh install) — the same handlers over empty tables.
    static func installEmpty(_ f: FakeNeema) {
        f.on("GET", "/admin/conversations") { r, _ in (200, r.param("limit") == nil ? "[]" : #"{"items":[],"next_cursor":null}"#) }
        f.on("GET", "/admin/orders", body: "[]")
        f.on("GET", "/admin/catalog", body: "[]")
        f.on("GET", "/admin/catalog/audit", body: emptyAudit)
        f.on("GET", "/admin/attribution", body: #"{"sources":[],"unattributed":{"orders":0,"revenue":0.0,"paid_revenue":0.0},"totals":{"leads":0,"orders":0,"revenue":0}}"#)
        f.on("GET", "/admin/stats", body: """
        {"open_conversations":0,"human_conversations":0,"ai_conversations":0,"active_agents":0,"total_agents":1,
          "total_revenue":0.0,"total_orders":0,"pending_orders":0,"delivered_orders":0,"confirmed_orders":0,"cancelled_orders":0,
          "in_stock_items":0,"total_items":0,"channel_breakdown":[]}
        """)
    }
}
