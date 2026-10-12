import Foundation
@testable import NeemaCore

/// A realistic data set for the fake backend — the Swift twin of Android's
/// `Fixtures`. The core endpoints are built from what their handlers in
/// apps/api/app actually return, including the serialisation FastAPI applies
/// (`jsonable_encoder`: UUID → string, Decimal → float, an aware datetime →
/// Python `isoformat()` with microseconds and `+00:00`). Times are relative
/// to the pinned clock so "5m ago" style labels stay stable.
enum Fixtures {
    static let ME_ID = "a1000000-0000-0000-0000-000000000001"
    static let AGENT2_ID = "a1000000-0000-0000-0000-000000000002"
    static let AGENT3_ID = "a1000000-0000-0000-0000-000000000003"

    private static let isoZ: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func ago(_ minutes: Int64) -> String {
        isoZ.string(from: AppClock.date().addingTimeInterval(-Double(minutes) * 60))
    }

    /// A `timestamptz` column as FastAPI sends it: Python's `datetime.isoformat()`
    /// of an aware UTC value — "2026-09-25T09:41:07.123456+00:00".
    static func pyIso(_ minutesAgo: Int64) -> String {
        let d = AppClock.date().addingTimeInterval(-Double(minutesAgo) * 60)
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let c = cal.dateComponents([.year, .month, .day, .hour, .minute, .second, .nanosecond], from: d)
        return String(format: "%04d-%02d-%02dT%02d:%02d:%02d.%06d+00:00", c.year!, c.month!, c.day!, c.hour!, c.minute!, c.second!, (c.nanosecond ?? 0) / 1000)
    }

    private static func q(_ s: String?) -> String { s.map { "\"\($0)\"" } ?? "null" }

    /// GET /admin/me — the ORM `Agent` row itself, with `password_hash` (ignored) and no custom-role columns.
    static var meOrm: String {
        """
        {"id":"\(ME_ID)","name":"Moses Mwicigi","email":"moses@bethanyhouse.co.ke",
        "password_hash":"$2b$12$Qm9ndXNIYXNoRm9yVGVzdHNPbmx5Li4uLi4uLi4uLi4uLi4u","role":"admin",
        "is_available":true,"is_superuser":true,"active_convs":4,"avatar_url":null,"created_at":"\(pyIso(60 * 24 * 200))",
        "last_seen_at":"\(pyIso(1))"}
        """
    }

    /// One row of GET /admin/agents: raw SQL over `agents LEFT JOIN custom_roles`, every column present.
    static func agentRow(_ id: String, _ name: String, _ email: String, _ role: String, _ available: Bool, _ superuser: Bool, _ active: Int,
                         _ createdMin: Int64, _ seenMin: Int64?, customRole: String? = nil, roleName: String? = nil, roleColor: String? = nil,
                         rolePermissions: String = "null", customPermissions: String = "null") -> String {
        """
        {"id":"\(id)","name":"\(name)","email":"\(email)","role":"\(role)","is_available":\(available),"is_superuser":\(superuser),
        "avatar_url":null,"created_at":"\(pyIso(createdMin))","last_seen_at":\(seenMin.map { "\"\(pyIso($0))\"" } ?? "null"),
        "active_convs":\(active),"custom_role_id":\(q(customRole)),"custom_permissions":\(customPermissions),
        "role_name":\(q(roleName)),"role_color":\(q(roleColor)),"role_permissions":\(rolePermissions)}
        """
    }

    static var meRow: String { agentRow(ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", "admin", true, true, 4, 60 * 24 * 200, 1) }

    static var agents: String {
        """
        [\(meRow),
        \(agentRow(AGENT2_ID, "Grace Wanjiru", "grace@bethanyhouse.co.ke", "agent", true, false, 7, 60 * 24 * 120, 3,
                   customRole: "sales", roleName: "Sales", roleColor: "#3b82f6",
                   rolePermissions: #"["view_conversations","reply_conversations","intercept_release","transfer_conversations","add_notes","view_orders","manage_orders","view_catalog","view_crm","edit_crm","view_leads"]"#)),
        \(agentRow(AGENT3_ID, "Brian Otieno", "brian@bethanyhouse.co.ke", "readonly", false, false, 0, 60 * 24 * 30, 60 * 26))]
        """
    }

    /// One `order_events` row as GET /admin/orders sends it (every column present; no contact_name).
    static func orderRow(_ id: String, _ waId: String, _ items: String, _ subtotal: String, _ status: String, _ channel: String, _ minutes: Int64,
                         payment: String = "unpaid", fulfillment: String = "pending", eventType: String? = "confirmed",
                         person: String? = nil, replyText: String? = nil, hub: [String: String] = [:]) -> String {
        var base: [(String, String)] = [
            ("hub_order_id", "null"), ("hub_order_number", "null"), ("hub_push_status", "null"), ("hub_payment_url", "null"),
            ("hub_currency", "null"), ("hub_total", "null"), ("hub_last_error", "null"), ("hub_pushed_at", "null"),
            ("hub_public_url", "null"), ("hub_public_token", "null"), ("short_ref", "null"), ("hub_status", "null"),
            ("hub_payment_status", "null"), ("hub_fulfillment_status", "null"), ("hub_status_at", "null"),
        ]
        for (k, v) in hub { if let i = base.firstIndex(where: { $0.0 == k }) { base[i].1 = v } else { base.append((k, v)) } }
        return """
        {"id":"\(id)","wa_id":"\(waId)","person_id":\(q(person)),"session_id":null,
        "event_type":\(q(eventType)),"items":\(items),"subtotal":\(subtotal),"currency":"KES","status":"\(status)",
        "payment_status":"\(payment)","fulfillment_status":"\(fulfillment)","reply_text":\(q(replyText)),
        "channel":"\(channel)","state":{},"created_at":"\(pyIso(minutes))","updated_at":"\(pyIso(max(0, minutes - 15)))",
        \(base.map { "\"\($0.0)\":\($0.1)" }.joined(separator: ","))}
        """
    }

    /// A cart line as Neema's own orders store it — `unit_price`, no `unit`/`total`.
    static func cartLine(_ productId: Int, _ name: String, _ sku: String, _ qty: Int, _ unitPrice: Double, _ usd: Double?) -> String {
        """
        {"hub_product_id":\(productId),"name":"\(name)","sku":"\(sku)","qty":\(qty),"unit_price":\(unitPrice),"price_usd":\(usd.map { "\($0)" } ?? "null"),
        "prices":{"KES":\(unitPrice)\(usd.map { ",\"USD\":\($0)" } ?? "")},"in_stock":true,"made_to_order":false}
        """
    }

    static var orders: String {
        """
        [\(orderRow("o1", "254712345678",
                    "[\(cartLine(501, "Clergy Shirt — Black, 16 inch", "CS-BLK-16", 2, 3500.0, 27.0)),\(cartLine(504, "Roman Collar Tab", "RC-TAB", 4, 250.0, 2.0))]",
                    "8000.0", "confirmed", "whatsapp", 45, payment: "paid", fulfillment: "unfulfilled", person: "9b2f6c1a-0000-4000-8000-000000000001",
                    hub: ["hub_order_id": "1042", "hub_order_number": "\"BH-1042\"", "hub_push_status": "\"pushed\"", "hub_currency": "\"KES\"", "hub_total": "8000.0",
                          "hub_pushed_at": "\"\(pyIso(44))\"", "hub_public_url": "\"https://hub.bethanyhouse.co.ke/order/tok1042\"", "hub_public_token": "\"tok1042\"",
                          "short_ref": "\"k7Q2mX\"", "hub_status": "\"processing\"", "hub_payment_status": "\"paid\"", "hub_status_at": "\"\(pyIso(30))\""])),
        \(orderRow("o2", "254722000111", "[\(cartLine(502, "Cassock — Purple, L", "CAS-PUR-L", 1, 12500.0, 96.0))]",
                    "12500.0", "open", "messenger", 180, eventType: "cart",
                    hub: ["hub_push_status": "\"failed\"", "hub_last_error": "\"Variant out of stock in hub\""])),
        \(orderRow("o3", "255754333222", #"[{"name":"Stole — Green","qty":1,"unit":4800,"total":4800}]"#,
                    "4800.0", "delivered", "whatsapp", 60 * 30, payment: "paid", fulfillment: "fulfilled", eventType: "order",
                    hub: ["hub_order_number": "\"BH-1031\"", "hub_status": "\"completed\""])),
        \(orderRow("o4", "254700999888", "[\(cartLine(505, "Alb — White, M", "ALB-WHT-M", 3, 6000.0, 46.0))]",
                    "18000.0", "cancelled", "instagram", 60 * 72, payment: "refunded"))]
        """
    }

    /// One hub product as GET /admin/catalog sends it: no local `id`, `unit` always "".
    static func hubProduct(_ id: Int, _ sku: String, _ name: String, _ category: String, _ kes: Double, _ usd: Double?, _ inStock: Bool, _ qty: Int?,
                           _ description: String, aliases: String = "[]", type: String = "simple", variants: String = "[]", range: String = "") -> String {
        """
        {"hub_product_id":\(id),"uuid":"8c1d\(id)00-0000-4000-8000-000000000000","sku":"\(sku)","slug":"\(name.lowercased().replacingOccurrences(of: " ", with: "-"))",
        "name":"\(name)","category":"\(category)","price":\(kes),"price_kes":\(kes),"price_usd":\(usd.map { "\($0)" } ?? "null"),
        "prices":{"KES":\(kes)\(usd.map { ",\"USD\":\($0)" } ?? "")},"unit":"","description":"\(description)","aliases":\(aliases),
        "in_stock":\(inStock),"available_qty":\(qty.map { "\($0)" } ?? "null"),
        "images":[{"url":"https://hub.test/p/\(sku).jpg","thumb":"https://hub.test/p/\(sku)-t.jpg","alt":"","primary":true,"sort":0}],
        "image_url":"https://hub.test/p/\(sku).jpg","thumbnail_url":"https://hub.test/p/\(sku)-t.jpg",
        "product_type":"\(type)","is_producible":false,"measurements":[],"variants":\(variants)\(range)}
        """
    }

    static func hubVariant(_ id: Int, _ sku: String, _ variantName: String, _ attrs: String, _ kes: Double, _ usd: Double?, _ label: String, isDefault: Bool = false) -> String {
        """
        {"variant_id":\(id),"sku":"\(sku)","name":"\(variantName)","attributes":\(attrs),"price_kes":\(kes),"price_usd":\(usd.map { "\($0)" } ?? "null"),
        "prices":{"KES":\(kes)\(usd.map { ",\"USD\":\($0)" } ?? "")},"is_default":\(isDefault),"in_stock":true,"label":"\(label)"}
        """
    }

    static var catalog: String {
        let variants = [
            hubVariant(1, "CS-BLK-15", "15 INCH / BLACK", #"{"Colour":"Black","Size":"15 inch"}"#, 3500.0, 27.0, "Clergy Shirt — Black, 15 inch", isDefault: true),
            hubVariant(2, "CS-BLK-16", "16 INCH / BLACK", #"{"Colour":"Black","Size":"16 inch"}"#, 3500.0, 27.0, "Clergy Shirt — Black, 16 inch"),
            hubVariant(3, "CS-BLU-16", "16 INCH / BLUE", #"{"Colour":"Blue","Size":"16 inch"}"#, 4200.0, 32.0, "Clergy Shirt — Blue, 16 inch"),
        ].joined(separator: ",")
        return """
        [\(hubProduct(501, "CS-BLK", "Clergy Shirt", "Shirts", 3500.0, 27.0, true, 42, "Tab-collar clergy shirt, poly-cotton, long sleeve.",
                      aliases: #"["clerical shirt","collar shirt"]"#, type: "variable", variants: "[\(variants)]",
                      range: #","price_min_kes":3500.0,"price_max_kes":4200.0,"price_min_usd":27.0,"price_max_usd":32.0"#)),
        \(hubProduct(502, "CAS-PUR", "Cassock", "Vestments", 12500.0, 96.0, true, 6, "Anglican double-breasted cassock.")),
        \(hubProduct(503, "STL-GRN", "Stole", "Vestments", 4800.0, 37.0, false, 0, "Embroidered green stole.", aliases: #"["stola"]"#)),
        \(hubProduct(504, "RC-TAB", "Roman Collar Tab", "Accessories", 250.0, 2.0, true, nil, "Replacement white collar tab.", aliases: #"["collar tab"]"#))]
        """
    }

    /// GET /admin/catalog while the hub is unreachable: eight keys only, no ids, "" for missing text.
    static let localCatalog = """
    [{"sku":"RC-TAB","name":"Roman Collar Tab","category":"Accessories","price":250.0,"unit":"piece","description":"Replacement white collar tab.","aliases":["collar tab"],"in_stock":true},
     {"sku":"CANDLE-1","name":"Altar Candle","category":"","price":1200.0,"unit":"","description":"","aliases":[],"in_stock":true}]
    """

    static let stats = """
    {"open_conversations":128,"human_conversations":9,"ai_conversations":119,"active_agents":2,"total_agents":3,
     "total_revenue":1284500,"total_orders":284,"pending_orders":21,"delivered_orders":203,"confirmed_orders":48,"cancelled_orders":12,
     "in_stock_items":187,"total_items":214,
     "channel_breakdown":[{"channel":"whatsapp","count":96,"open":80},{"channel":"messenger","count":21,"open":30},{"channel":"instagram","count":11,"open":18}]}
    """

    static func conv(_ id: String, _ name: String?, _ waId: String, _ channel: String, _ mode: String, _ preview: String, _ minutes: Int64,
                     unread: Int = 0, stage: String? = nil, orders: Int = 0, person: String? = nil, agent: String? = nil,
                     tags: String = "[]", iso: String = "KE") -> String {
        let agentName = agent == ME_ID ? "\"Moses Mwicigi\"" : (agent != nil ? "\"Grace Wanjiru\"" : "null")
        return """
        {"id":"\(id)","wa_id":"\(waId)","external_id":"\(waId)","person_id":\(q(person)),
        "intercept_mode":"\(mode)","lead_stage":\(q(stage)),"assigned_agent_id":\(q(agent)),
        "assigned_agent_name":\(agentName),
        "intercept_since":null,"last_message_at":"\(ago(minutes))","last_message_preview":"\(preview)","status":"open",
        "created_at":"\(ago(minutes + 600))","updated_at":"\(ago(minutes))","name":\(q(name)),"avatar_url":null,
        "orders_count":\(orders),"channel":"\(channel)","unread":\(unread),"country":null,"country_iso":"\(iso)","tags":\(tags)}
        """
    }

    static var conversations: [String] {
        [
            conv("c1", "Fr. Peter Kamau", "254712345678", "whatsapp", "human", "Can you deliver to Nyeri by Friday?", 2, unread: 2, stage: "proposal", orders: 3, person: "p1", agent: ME_ID, tags: #"["vip","clergy"]"#),
            conv("c2", "Rev. Mary Achieng", "254722000111", "messenger", "ai", "Asante! How much is the purple cassock?", 9, unread: 1, stage: "qualified"),
            conv("c3", nil, "255754333222", "whatsapp", "paused", "📷 Photo", 34, stage: "new", iso: "TZ"),
            conv("c4", "Sr. Lucy Njeri", "17840000000000001", "instagram", "ai", "Do you have albs in size M?", 75, stage: "contacted"),
            conv("c5", "Fr. Peter Kamau", "25898765432101234", "facebook", "ai", "Commented: Beautiful stoles! 🙏", 240, person: "p1"),
            conv("c6", "Deacon James Mwangi", "254733444555", "whatsapp", "human", "I'll send the measurements tonight", 60 * 5, stage: "negotiation", agent: AGENT2_ID),
        ]
    }

    /// A web-chat visitor: keyed `web_<sha1[:20]>` in `wa_id`, on the DEFAULT channel "whatsapp", no name.
    static var webVisitor: String { conv("c7", nil, "web_3fa9c1e20b7d4c5a9e11", "whatsapp", "ai", "Do you ship to Kampala?", 20, unread: 1, iso: "UG") }

    static var inbox: [String] { conversations + [webVisitor] }

    static var conversationPage: String { "{\"items\":[\(inbox.joined(separator: ","))],\"next_cursor\":\"cursor-2\"}" }

    static let inboxSummary = #"{"unread":3,"human":2,"yours":1,"unread_messages":{"all":4,"whatsapp":3,"messenger":1},"tags":["bulk","clergy","vip"]}"#

    static var messages: String {
        """
        [{"id":"m1","type":"message","direction":"inbound","sender":"user","text":"Habari! Do you make clergy shirts?","created_at":"\(ago(60 * 26))"},
         {"id":"m2","type":"message","direction":"outbound","sender":"ai","text":"Habari Father! Yes 🙏 Our *Clergy Shirt* is KES 3,500 in black, and KES 4,200 in blue. What collar size do you wear?","created_at":"\(ago(60 * 26 - 1))"},
         {"id":"m3","type":"message","direction":"inbound","sender":"user","text":"16 inch, two black ones please","created_at":"\(ago(50))"},
         {"id":"e1","type":"system_event","direction":"outbound","sender":"ai","text":"Picked up by Moses Mwicigi","created_at":"\(ago(20))","event_kind":"intercept"},
         {"id":"m4","type":"message","direction":"inbound","sender":"user","text":"","created_at":"\(ago(15))","media_type":"image","media_url":"https://neema.test/media/collar.jpg","media_caption":"Like this collar"},
         {"id":"m5","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","text":"Yes, that's our standard tab collar. Two black 16\\" shirts come to KES 7,000.","created_at":"\(ago(10))"},
         {"id":"n1","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","isNote":true,"text":"Repeat buyer — offer free delivery","created_at":"\(ago(8))"},
         {"id":"m6","type":"message","direction":"inbound","sender":"user","text":"Can you deliver to Nyeri by Friday?","created_at":"\(ago(2))","reply_to":{"id":"m5","text":"Yes, that's our standard tab collar.","sender":"human_agent"}}]
        """
    }

    static var calls: String {
        """
        [{"id":"k1","call_id":"wacid.1","wa_id":"254712345678","name":"Fr. Peter Kamau","direction":"inbound","status":"completed","duration":184,
          "agent_name":"Moses Mwicigi","started_at":"\(ago(40))","summary":"Wants two black clergy shirts delivered to Nyeri by Friday.","transcript_status":"done","has_recording":true},
         {"id":"k2","call_id":"wacid.2","wa_id":"254722000111","name":"Rev. Mary Achieng","direction":"inbound","status":"missed","duration":null,
          "agent_name":null,"started_at":"\(ago(130))","transcript_status":"none","has_recording":false},
         {"id":"k3","call_id":"wacid.3","wa_id":"254733444555","name":"Deacon James Mwangi","direction":"outbound","status":"completed","duration":61,
          "agent_name":"Grace Wanjiru","started_at":"\(ago(60 * 20))","transcript_status":"pending","has_recording":true}]
        """
    }

    static var deals: String {
        """
        {"deals":[
          {"id":"d1","conversation_id":"c1","customer":"Fr. Peter Kamau","wa_id":"254712345678","channel":"whatsapp","title":"2× Clergy Shirt (Black 16\\")",
           "items":[{"name":"Clergy Shirt","qty":2,"price":3500}],"stage":"proposal","blocking":"Needs delivery date confirmed",
           "next_action":{"kind":"follow_up","owner":"ai","due_at":"\(ago(-180))","note":"Confirm Nyeri delivery"},"guidance":"Offer free delivery","status":"open","updated_at":"\(ago(12))"},
          {"id":"d2","conversation_id":"c2","customer":"Rev. Mary Achieng","wa_id":"254722000111","channel":"messenger","title":"Purple cassock",
           "items":[],"stage":"qualified","blocking":null,"next_action":null,"guidance":null,"status":"open","updated_at":"\(ago(90))"},
          {"id":"d3","conversation_id":"c6","customer":"Deacon James Mwangi","wa_id":"254733444555","channel":"whatsapp","title":"Made-to-measure alb",
           "items":[],"stage":"new","blocking":"Waiting for measurements","next_action":{"kind":"follow_up","owner":"human","due_at":"\(ago(-60 * 20))"},"guidance":null,"status":"open","updated_at":"\(ago(300))"}
        ]}
        """
    }

    static var actions: String {
        """
        {"actions":[
          {"id":"x1","deal_id":"d1","conversation_id":"c1","due_at":null,"kind":"follow_up","reason":"Father asked about Friday delivery 2h ago and hasn't had an answer",
           "draft":"Hello Father Peter 🙏 Just confirming — we can deliver both shirts to Nyeri by Friday. Shall I send the M-Pesa details?","status":"pending","created_by":"neema"}
        ]}
        """
    }

    static let attribution = """
    {"sources":[{"source":"facebook_ad","post":"1203","post_title":"Easter vestments sale","leads":42,"orders":11,"revenue":186000,"paid_revenue":152000},
      {"source":"instagram","post":null,"leads":18,"orders":4,"revenue":51000,"paid_revenue":51000},
      {"source":"organic","post":null,"leads":77,"orders":30,"revenue":402000,"paid_revenue":377500}],
      "unattributed":{"orders":9,"revenue":64000,"paid_revenue":60000},"totals":{"leads":137,"orders":54,"revenue":703000}}
    """

    static let roles = """
    [{"id":"admin","name":"Admin","description":"Full system access","color":"#f59e0b","permissions":["view_conversations","manage_agents","manage_roles","manage_settings"],"protected":true},
     {"id":"sales","name":"Sales","description":"Handles conversations and orders","color":"#3b82f6","permissions":["view_conversations","reply_conversations","view_orders","manage_orders"],"protected":false}]
    """

    static func tokenResponse(agentId: String = ME_ID, role: String = "admin", superuser: Bool = true,
                              access: String? = nil, refresh: String = "refresh-2") -> String {
        let a = access ?? fakeJwt(agentId)
        return #"{"access_token":"\#(a)","refresh_token":"\#(refresh)","token_type":"bearer","agent_id":"\#(agentId)","role":"\#(role)","is_superuser":\#(superuser)}"#
    }

    static func install(_ f: FakeNeema) {
        f.on("GET", "/admin/conversations/[^/]+") { r, _ in
            let id = r.url.lastPathComponent
            return (200, inbox.first { $0.contains("\"id\":\"\(id)\"") } ?? conversations[0])
        }
        f.on("GET", "/admin/me", body: meOrm)
        f.on("GET", "/admin/agents", body: agents)
        f.on("GET", "/admin/orders", body: orders)
        f.on("GET", "/admin/catalog", body: catalog)
        f.on("GET", "/admin/catalog/audit", body: #"{"currency_gaps":[{"name":"Cassock","category":"Vestments","kes":12500,"usd":110,"usd_expected":96.2,"factor":1.14}],"per_piece":[],"checked":214,"rate":130}"#)
        f.on("GET", "/admin/stats", body: stats)
        f.on("GET", "/admin/attribution", body: attribution)
        f.on("GET", "/admin/conversations") { r, _ in
            (200, (r.url.query ?? "").contains("limit=") ? conversationPage : "[\(inbox.joined(separator: ","))]")
        }
        f.on("GET", "/admin/conversations/summary", body: inboxSummary)
        f.on("GET", "/admin/conversations/[^/]+/messages", body: messages)
        f.on("GET", "/admin/conversations/[^/]+/window", body: #"{"mode":"open","channel":"whatsapp","last_inbound_at":"\#(ago(2))","expires_at":"\#(ago(-1438))"}"#)
        f.on("GET", "/admin/conversations/[^/]+/latest-draft", body: #"{"draft":null}"#)
        f.on("GET", "/admin/conversations/[^/]+/activity", body: #"{"events":[{"id":"ev1","kind":"order","label":"Order BH-1042 paid","detail":"KES 8,000 via M-Pesa","at":"\#(ago(30))"},{"id":"ev2","kind":"intercept","label":"Picked up by Moses","at":"\#(ago(20))"}]}"#)
        f.on("GET", "/admin/calls", body: calls)
        f.on("GET", "/admin/deals", body: deals)
        f.on("GET", "/admin/actions", body: actions)
        f.on("GET", "/admin/roles", body: roles)
        f.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages":["measuring"]}"#)
        f.on("GET", "/admin/settings/directives", body: #"{"directives":"Always offer free delivery within Nairobi on orders above KES 10,000.","max_chars":2000}"#)
        f.on("GET", "/admin/settings/translation", body: #"{"enabled":true,"default":false,"spend_30d_usd":3.42,"calls_30d":812}"#)
        f.on("GET", "/admin/settings/offer", body: #"{"campaign":{"name":"Easter Sale","percent":10,"scope":"category","categories":["Vestments"],"skus":[],"starts_on":null,"ends_on":"2099-04-30"},"running":true,"says":"Easter Sale: 10% off all Vestments until 30 April.","max_percent":30}"#)
        for m in ["POST", "PATCH", "PUT", "DELETE"] { f.on(m, "/.*") { _, _ in (200, #"{"ok":true}"#) } }
        f.on("POST", "/(agent-auth|auth)/(login|refresh)") { _, _ in (200, tokenResponse()) }
        f.on("PATCH", "/admin/me") { _, _ in (200, meOrm) }
    }

    static func withFixtures() -> FakeNeema {
        let f = FakeNeema()
        install(f)
        return f
    }
}
