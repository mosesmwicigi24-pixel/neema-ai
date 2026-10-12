import Foundation
@testable import NeemaCore

/// The CRM panel's backend, built from what the handlers in apps/api actually
/// return (Android `CustomerFixtures`):
///  - c1 Fr. Peter Kamau (WhatsApp): hub-linked, 24 lifetime orders — a VIP gone quiet.
///  - c2 Rev. Mary Achieng (Messenger): a sparse lead — no phone, no orders.
///  - c7 a website chat visitor keyed `web_<sha1>`.
enum CustomerFixtures {
    static let PETER = "254712345678"
    static let MARY = "254722000111"
    static let ENQUIRY_ID = "5b7e2c9a-1f3d-4e8b-9a61-2d0c4f7e8a13"
    /// c7's key: its hex hash holds 11 digits — enough to pass for a phone.
    static let WEB = "web_3fa9c1e20b7d4c5a9e11"

    static func conversation(_ id: String) -> Conversation {
        try! NeemaJSON.decode(Conversation.self, from: Fixtures.inbox.first { $0.contains("\"id\":\"\(id)\"") }!)
    }

    /// A tz-aware datetime's Python `.isoformat()`: "…+00:00", never "Z".
    static func py(_ minutesAgo: Int64) -> String { Fixtures.pyIso(minutesAgo) }
    static func ago(_ minutes: Int64) -> String { Fixtures.ago(minutes) }
    private static let DAY: Int64 = 60 * 24

    private static func hubOrder(_ id: Int, _ number: String, _ status: String, _ pay: String, _ type: String, _ total: Double, _ createdAt: String,
                                 _ lines: [(String, Int, Double)]) -> String {
        let items = lines.map { n, q, up in #"{"name":"\#(n)","qty":\#(q),"quantity":\#(q),"unit_price":\#(up),"total":\#(up * Double(q))}"# }.joined(separator: ",")
        return #"{"id":"\#(id)","order_number":"\#(number)","status":"\#(status)","payment_status":"\#(pay)","order_type":"\#(type)","total":\#(total),"subtotal":\#(total),"currency_code":"KES","created_at":"\#(createdAt)","items":[\#(items)],"source":"hub"}"#
    }

    /// crm.py get_customer → _build_profile with a hub summary: 24 lifetime orders, a VIP, overdue.
    static var peter: String { """
    {
      "id":"0f6b8a52-3c1e-4d7a-9b2f-5e8c1a4d6b70","wa_id":"\(PETER)","name":"Fr. Peter Kamau","name_confirmed":true,
      "email":"peter.kamau@stmarks.or.ke","phone":"+\(PETER)","location":"Nyeri","age":47,"tags":["vip","clergy","bulk"],
      "lead_stage":"proposal","lead_stage_source":"auto","suggested_lead_stage":"qualified","lead_source":"facebook_ad",
      "ad_ref":{"source_type":"ad","source_id":"120210987654321","source_url":"https://fb.me/2kQx","headline":"Easter vestments — 10% off"},
      "role":"Parish Priest","organization":"St. Mark's Anglican Church",
      "lead_score":95,"phone_verified":true,"cart_items":0,
      "parish":{"id":"7d2f4a18-6b3c-4e91-8a5d-0c1b2e3f4a5b","name":"St. Mark's Parish","location":"Nyeri"},
      "measurements":{"chest":"104 cm","height":"178 cm"},
      "lead_score_breakdown":[
        {"label":"Active cart","pts":0,"max":25},{"label":"Orders","pts":25,"max":25},
        {"label":"Recent contact","pts":15,"max":15},{"label":"Spend level","pts":15,"max":15},
        {"label":"Phone verified","pts":10,"max":10},{"label":"Multi-channel","pts":10,"max":10},
        {"label":"Name known","pts":5,"max":5},{"label":"Location known","pts":5,"max":5},
        {"label":"Clergy leader","pts":10,"max":10}],
      "channels":[
        {"channel":"whatsapp","identifier":"\(PETER)","first_seen":"\(py(DAY * 400))","last_seen":"\(py(2))","conversation_count":3},
        {"channel":"facebook","identifier":null,"first_seen":"\(py(DAY * 20))","last_seen":"\(py(240))","conversation_count":1}
      ],
      "merged_ids":["254799000111"],
      "person_id":"3e9a1c7b-5d2f-4b8e-a6c0-9f1e2d3c4b5a",
      "linked_identities":[
        {"channel":"whatsapp","external_id":"\(PETER)","display_name":"Fr. Peter","source":"whatsapp_inbound","confidence":"deterministic"},
        {"channel":"facebook","external_id":"25898765432101234","display_name":"Peter Kamau","source":"comment","confidence":"probable"}
      ],
      "total_orders":24,"total_spent":486500.0,"avg_order_value":20270.83,
      "orders":[
        \(hubOrder(90412, "BH-1042", "confirmed", "paid", "online", 8000.0, ago(DAY * 70), [("Clergy Shirt — Black, 16 inch", 2, 3500.0), ("Roman Collar Tab", 4, 250.0)])),
        \(hubOrder(88731, "BH-0987", "delivered", "paid", "online", 14500.0, ago(DAY * 100), [("Cassock — Black, L", 1, 12500.0), ("Roman Collar Tab", 8, 250.0)])),
        \(hubOrder(86102, "POS-5521", "delivered", "paid", "pos", 4800.0, ago(DAY * 130), [("Stole — Green", 1, 4800.0)])),
        \(hubOrder(84420, "BH-0912", "cancelled", "refunded", "online", 3500.0, ago(DAY * 160), [("Clergy Shirt — Blue, 16 inch", 1, 3500.0)]))
      ],
      "orders_source":"hub","hub_linked":true,"hub_customer_id":311,"hub_customer_name":"Peter Kamau (St. Mark's)",
      "buying_rhythm":{"days_since_last":70,"avg_interval_days":30.0,"cadence_label":"about every 4 weeks","overdue":true},
      "tier":"vip","tier_label":"VIP",
      "last_order_at":"\(py(DAY * 70))","last_seen_at":"\(py(2))","first_seen_at":"\(py(DAY * 400))",
      "notes":"Prefers delivery to the parish office.\\n\\nAsk about the Easter order in March.",
      "created_at":"\(py(DAY * 400))","country_iso":"KE","country":"Kenya","flag_url":"https://flagcdn.com/w40/ke.png"
    }
    """ }

    /// crm.py get_customer with no hub match: integer zeros, orders [], a rhythm of nulls; a Messenger thread has no wa_id identifier.
    static var mary: String { """
    {
      "id":"a41c2e9d-8b7f-4c3a-9e5d-1f0a2b3c4d5e","wa_id":"\(MARY)","name":"Rev. Mary Achieng","name_confirmed":false,
      "email":null,"phone":null,"location":null,"age":null,"tags":[],
      "lead_stage":"qualified","lead_stage_source":"manual","suggested_lead_stage":"contacted","lead_source":null,"ad_ref":null,
      "role":null,"organization":null,"lead_score":20,"phone_verified":false,"cart_items":0,"parish":null,"measurements":{},
      "lead_score_breakdown":[
        {"label":"Active cart","pts":0,"max":25},{"label":"Orders","pts":0,"max":25},
        {"label":"Recent contact","pts":15,"max":15},{"label":"Spend level","pts":0,"max":15},
        {"label":"Phone verified","pts":0,"max":10},{"label":"Multi-channel","pts":0,"max":10},
        {"label":"Name known","pts":5,"max":5},{"label":"Location known","pts":0,"max":5},
        {"label":"Clergy leader","pts":0,"max":10}],
      "channels":[{"channel":"messenger","identifier":null,"first_seen":"\(py(60 * 3))","last_seen":"\(py(9))","conversation_count":1}],
      "merged_ids":[],"person_id":"c5d6e7f8-0a1b-4c2d-8e3f-4a5b6c7d8e9f","linked_identities":[
        {"channel":"messenger","external_id":"7755332211009988","display_name":"Mary Achieng","source":"messenger_inbound","confidence":"deterministic"}],
      "total_orders":0,"total_spent":0,"avg_order_value":0,"orders":[],"orders_source":"whatsapp",
      "hub_linked":false,"hub_customer_id":null,"hub_customer_name":null,
      "buying_rhythm":{"days_since_last":null,"avg_interval_days":null,"cadence_label":null,"overdue":false},
      "tier":"prospect","tier_label":"Prospect",
      "last_order_at":null,"last_seen_at":"\(py(9))","first_seen_at":"\(py(60 * 3))",
      "notes":null,"created_at":"\(py(60 * 3))","country_iso":null,"country":null,"flag_url":null
    }
    """ }

    private static func q(_ s: String?) -> String { s.map { "\"\($0)\"" } ?? "null" }

    /// A website chat visitor as crm.py builds them: the `web_` key as identifier, `phone` null unless the visitor typed one.
    static func webVisitor(phone: String? = nil, name: String? = nil) -> String { """
    {
      "id":"e8f9a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b","wa_id":"\(WEB)","name":\(q(name)),"name_confirmed":false,"email":null,
      "phone":\(q(phone)),"location":null,"age":null,
      "tags":[],"lead_stage":"new","lead_stage_source":null,"suggested_lead_stage":"contacted","lead_source":"website","ad_ref":null,
      "role":null,"organization":null,"lead_score":\(40 + (name != nil ? 5 : 0)),"phone_verified":false,"cart_items":1,
      "parish":null,"measurements":{},
      "lead_score_breakdown":[
        {"label":"Active cart","pts":25,"max":25},{"label":"Orders","pts":0,"max":25},
        {"label":"Recent contact","pts":15,"max":15},{"label":"Spend level","pts":0,"max":15},
        {"label":"Phone verified","pts":0,"max":10},{"label":"Multi-channel","pts":0,"max":10},
        {"label":"Name known","pts":\(name != nil ? 5 : 0),"max":5},{"label":"Location known","pts":0,"max":5},
        {"label":"Clergy leader","pts":0,"max":10}],
      "channels":[{"channel":"whatsapp","identifier":"\(WEB)","first_seen":"\(py(40))","last_seen":"\(py(20))","conversation_count":1}],
      "merged_ids":[],"person_id":null,
      "linked_identities":[],
      "total_orders":0,"total_spent":0,"avg_order_value":0,"orders":[],"orders_source":"whatsapp",
      "hub_linked":false,"hub_customer_id":null,"hub_customer_name":null,
      "buying_rhythm":{"days_since_last":null,"avg_interval_days":null,"cadence_label":null,"overdue":false},
      "tier":"prospect","tier_label":"Prospect",
      "last_order_at":null,"last_seen_at":"\(py(20))","first_seen_at":"\(py(40))",
      "notes":null,"created_at":"\(py(40))","country_iso":"UG","country":"Uganda","flag_url":"https://flagcdn.com/w40/ug.png"
    }
    """ }

    /// crm.py merge_suggestions: sorted strong-first, at most 5.
    static let suggestions = """
    {"suggestions":[
      {"merge_with":"254799000222","name":"Peter Kamau","phone":"254799000222","country":"Kenya","channel_hint":"whatsapp",
       "evidence":["Same email","Same name + country"],"strength":"strong"},
      {"merge_with":"17840000000000077","name":"Fr. Peter Kamau","phone":null,"country":null,"channel_hint":"social",
       "evidence":["Same name"],"strength":"possible"}
    ]}
    """

    /// crm.py get_conversation_enquiry → {enquiry: _enq_json(e) | null}.
    static func enquiry(_ status: String = "new", pushable: Bool = true, order: String? = nil) -> String { """
    {"enquiry":{
      "id":"\(ENQUIRY_ID)","created_at":"\(py(30))","product_name":"Made-to-measure Alb","product_slug":"alb","customer_name":"Fr. Peter Kamau",
      "phone":"\(PETER)","measurements":{"Chest":"104 cm","Height":"178 cm","Sleeve":"63"},"notes":"Needs it before Palm Sunday",
      "location":"Nyeri","status":"\(status)","hub_order_id":\(order != nil ? "90555" : "null"),
      "hub_order_number":\(q(order)),"pushable":\(pushable)}}
    """ }

    /// crm.py push_production, first push.
    static let pushed = #"{"ok":true,"hub_order_id":90555,"hub_order_number":"BH-2001","total_amount":"18500.00","currency_code":"KES"}"#
    /// crm.py push_production on an enquiry already pushed.
    static let alreadyPushed = #"{"ok":true,"already":true,"hub_order_id":90555,"hub_order_number":"BH-2001"}"#

    /// A proxy's HTML error page: never to be shown to anyone.
    static let HTML_502 = "<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>nginx</center></body></html>"

    static func install(_ f: FakeNeema) {
        f.on("GET", "/admin/customers/\(PETER)", body: peter)
        f.on("GET", "/admin/customers/\(MARY)", body: mary)
        f.on("GET", "/admin/customers/\(WEB)", body: webVisitor())
        // crm.py update_customer / merge_customers / unmerge_customer: plain acknowledgements.
        f.on("PATCH", "/admin/customers/[^/]+", body: #"{"ok":true}"#)
        f.on("POST", "/admin/customers/[^/]+/merge", body: #"{"ok":true,"merged":"254799000222","into":"\#(PETER)","merge_id":"9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"}"#)
        f.on("POST", "/admin/customers/[^/]+/unmerge", body: #"{"ok":true,"unmerged":"254799000111","from":"\#(PETER)"}"#)
        f.on("GET", "/admin/customers/[^/]+/merge_suggestions", body: suggestions)
        f.on("GET", "/admin/production/conversation/[^/]+", body: #"{"enquiry":null}"#)
        f.on("GET", "/admin/production/conversation/c1", body: enquiry())
        f.on("POST", "/admin/production/[^/]+/push", body: #"{"ok":true,"hub_order_id":88,"hub_order_number":null}"#)
        // crm.py decline_production: {ok} whether or not anything changed.
        f.on("POST", "/admin/production/[^/]+/decline", body: #"{"ok":true}"#)
        f.on("POST", "/admin/whatsapp-invite", body: #"{"ok":true,"wa_id":"\#(PETER)"}"#)
        f.on("POST", "/admin/conversations/[^/]+/ask", body: #"{"answer":"16 inch collar, size L cassock."}"#)
        f.on("POST", "/admin/conversations/[^/]+/answer", body: #"{"ok":true,"sent":"Yes Father, we make it 🙏"}"#)
    }

    static func withFixtures() -> FakeNeema {
        let f = Fixtures.withFixtures()
        install(f)
        return f
    }
}
