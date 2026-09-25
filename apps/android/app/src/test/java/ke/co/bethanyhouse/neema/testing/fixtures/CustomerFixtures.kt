package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.Fixtures.ago

/**
 * The CRM panel's backend (routers/crm.py `_build_profile`, merge_suggestions,
 * /production/conversation/{id}), shaped exactly as the server sends it.
 *  - c1 Fr. Peter Kamau (WhatsApp): a rich, hub-linked VIP with every section filled.
 *  - c2 Rev. Mary Achieng (Messenger): a sparse lead — no phone, no orders, no tier.
 */
object CustomerFixtures {
    const val PETER = "254712345678"
    const val MARY = "254722000111"

    fun conversation(id: String): Conversation =
        NeemaJson.decodeFromString(Conversation.serializer(), InboxFixtures.conversations.first { it.contains("\"id\":\"$id\"") })

    val peter get() = """{
      "id":"u1","wa_id":"$PETER","name":"Fr. Peter Kamau","name_confirmed":true,"email":"peter.kamau@stmarks.or.ke",
      "phone":"+$PETER","location":"Nyeri","age":47,"tags":["vip","clergy","bulk"],
      "lead_stage":"proposal","lead_stage_source":"auto","suggested_lead_stage":"proposal","lead_source":"facebook",
      "ad_ref":{"headline":"Easter vestments — 10% off","ad_id":"1203","source_type":"ad"},
      "role":"Parish Priest","organization":"St. Mark's Anglican Church",
      "orders":[
        {"id":"h1","order_number":"BH-1042","status":"confirmed","payment_status":"paid","total":8000,"subtotal":8000,"currency_code":"KES",
         "created_at":"${ago(45)}","items":[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"total":7000},{"name":"Roman Collar Tab","qty":4,"total":1000}],"source":"hub"},
        {"id":"h2","order_number":"BH-0987","status":"delivered","payment_status":"paid","total":14500,"currency_code":"KES",
         "created_at":"${ago(60 * 24 * 40)}","items":[{"name":"Cassock — Black, L","qty":1,"total":12500},{"name":"Roman Collar Tab","qty":8,"total":2000}],"source":"hub"},
        {"id":"h3","order_number":"BH-0912","status":"delivered","payment_status":"paid","total":4800,"currency_code":"KES",
         "created_at":"${ago(60 * 24 * 95)}","items":[{"name":"Stole — Green","qty":1,"total":4800}],"source":"hub"},
        {"id":"h4","order_number":"POS-5521","status":"cancelled","payment_status":"refunded","total":3500,"currency_code":"KES",
         "created_at":"${ago(60 * 24 * 130)}","items":[{"name":"Clergy Shirt — Blue, 16 inch","qty":1,"total":3500}],"source":"hub"}
      ],
      "orders_source":"hub","hub_linked":true,"hub_customer_id":311,"hub_customer_name":"Peter Kamau (St. Mark's)",
      "lead_score":72,"phone_verified":true,"cart_items":2,
      "lead_score_breakdown":[{"label":"Orders placed","pts":30,"max":30},{"label":"Lifetime spend","pts":20,"max":25},
        {"label":"Reachable phone","pts":10,"max":10},{"label":"Recent activity","pts":12,"max":20},{"label":"Items in cart","pts":0,"max":15}],
      "parish":{"id":"par1","name":"St. Mark's Parish","location":"Nyeri"},
      "channels":[
        {"channel":"whatsapp","identifier":"$PETER","first_seen":"${ago(60 * 24 * 140)}","last_seen":"${ago(2)}","conversation_count":3},
        {"channel":"facebook","identifier":null,"first_seen":"${ago(60 * 24 * 20)}","last_seen":"${ago(240)}","conversation_count":1}
      ],
      "merged_ids":["254799000111"],
      "person_id":"p1",
      "linked_identities":[
        {"channel":"whatsapp","external_id":"$PETER","display_name":"Fr. Peter","source":"webhook","confidence":"verified"},
        {"channel":"facebook","external_id":"25898765432101234","display_name":"Peter Kamau","source":"comment","confidence":"probable"}
      ],
      "total_orders":4,"total_spent":30800,"avg_order_value":7700,"tier":"vip","tier_label":"VIP",
      "buying_rhythm":{"days_since_last":40,"avg_interval_days":30,"cadence_label":"monthly","overdue":true},
      "last_order_at":"${ago(45)}","last_seen_at":"${ago(2)}","first_seen_at":"${ago(60 * 24 * 140)}",
      "notes":"Prefers delivery to the parish office.\nAsk about the Easter order in March.",
      "created_at":"${ago(60 * 24 * 140)}","country_iso":"KE","country":"Kenya","flag_url":"https://flagcdn.com/w40/ke.png"
    }"""

    /** A Messenger lead: nothing known but a name. */
    val mary get() = """{
      "id":"u2","wa_id":"$MARY","name":"Rev. Mary Achieng","name_confirmed":false,"email":null,"phone":null,"location":null,"age":null,
      "tags":[],"lead_stage":"qualified","lead_stage_source":"manual","lead_source":null,"ad_ref":null,"role":null,"organization":null,
      "orders":[],"orders_source":"whatsapp","hub_linked":false,"lead_score":18,"phone_verified":false,"cart_items":0,
      "lead_score_breakdown":[{"label":"Orders placed","pts":0,"max":30},{"label":"Recent activity","pts":18,"max":20}],
      "parish":null,
      "channels":[{"channel":"messenger","identifier":"$MARY","first_seen":"${ago(60 * 3)}","last_seen":"${ago(9)}","conversation_count":1}],
      "merged_ids":[],"person_id":null,"linked_identities":[],
      "total_orders":0,"total_spent":0,"avg_order_value":0,"tier":"prospect","tier_label":"Prospect",
      "buying_rhythm":null,"last_order_at":null,"last_seen_at":"${ago(9)}","first_seen_at":"${ago(60 * 3)}",
      "notes":null,"created_at":"${ago(60 * 3)}","country_iso":null,"country":null,"flag_url":null
    }"""

    /** c7's key (InboxFixtures.webVisitor): its hex hash holds 11 digits — enough to pass for a phone. */
    const val WEB = "web_3fa9c1e20b7d4c5a9e11"

    /**
     * A website chat visitor as crm.py builds them: the thread rides the default
     * "whatsapp" channel with the `web_` key as its identifier, and `phone` is
     * null (is_plausible_phone refuses the key) unless the visitor typed one.
     */
    fun webVisitor(phone: String? = null, name: String? = null) = """{
      "id":"u7","wa_id":"$WEB","name":${name?.let { "\"$it\"" }},"name_confirmed":false,"email":null,
      "phone":${phone?.let { "\"$it\"" }},"location":null,"age":null,
      "tags":[],"lead_stage":"new","lead_stage_source":null,"lead_source":"website","ad_ref":null,"role":null,"organization":null,
      "orders":[],"orders_source":"whatsapp","hub_linked":false,"lead_score":8,"phone_verified":false,"cart_items":1,
      "lead_score_breakdown":[{"label":"Items in cart","pts":8,"max":15}],"parish":null,
      "channels":[{"channel":"whatsapp","identifier":"$WEB","first_seen":"${ago(40)}","last_seen":"${ago(20)}","conversation_count":1}],
      "merged_ids":[],"person_id":null,
      "linked_identities":[{"channel":"whatsapp","external_id":"$WEB","display_name":null,"source":"legacy","confidence":"probable"}],
      "total_orders":0,"total_spent":0,"avg_order_value":0,"tier":"prospect","tier_label":"Prospect",
      "buying_rhythm":null,"last_order_at":null,"last_seen_at":"${ago(20)}","first_seen_at":"${ago(40)}",
      "notes":null,"created_at":"${ago(40)}","country_iso":"UG","country":"Uganda","flag_url":null
    }"""

    val suggestions = """{"suggestions":[
      {"merge_with":"254799000222","name":"Peter Kamau","phone":"+254799000222","country":"Kenya","channel_hint":"whatsapp",
       "evidence":["Same phone on a Messenger profile","Same name"],"strength":"strong"},
      {"merge_with":"17840000000000077","name":null,"phone":null,"country":null,"channel_hint":"instagram",
       "evidence":["Same name + country"],"strength":"possible"}
    ]}"""

    fun enquiry(status: String = "new", pushable: Boolean = true, order: String? = null) = """{"enquiry":{
      "id":"e1","created_at":"${ago(30)}","product_name":"Made-to-measure Alb","product_slug":"alb","customer_name":"Fr. Peter Kamau",
      "phone":"$PETER","measurements":{"Chest":"104 cm","Height":"178 cm","Sleeve":"63"},"notes":"Needs it before Palm Sunday",
      "location":"Nyeri","status":"$status","hub_order_id":null,"hub_order_number":${order?.let { "\"$it\"" }},"pushable":$pushable}}"""

    fun install(f: FakeNeema) {
        f.on("GET", "/admin/customers/$PETER", body = peter)
        f.on("GET", "/admin/customers/$MARY", body = mary)
        f.on("GET", "/admin/customers/$WEB", body = webVisitor())
        f.on("GET", "/admin/customers/[^/]+/merge_suggestions", body = suggestions)
        f.on("GET", "/admin/production/conversation/[^/]+", body = """{"enquiry":null}""")
        f.on("GET", "/admin/production/conversation/c1", body = enquiry())
    }
}
