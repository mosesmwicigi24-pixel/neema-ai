package ke.co.bethanyhouse.neema.testing

import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * A realistic data set for the fake backend, shaped exactly like the API's
 * responses (see apps/api/app/routers). Times are relative to now so
 * "5m ago" style labels stay stable. Feature areas add their own routes via
 * [install] or directly on a [FakeNeema].
 */
object Fixtures {
    const val ME_ID = "a1000000-0000-0000-0000-000000000001"
    const val AGENT2_ID = "a1000000-0000-0000-0000-000000000002"
    const val AGENT3_ID = "a1000000-0000-0000-0000-000000000003"

    fun ago(minutes: Long): String = Instant.now().minus(minutes, ChronoUnit.MINUTES).toString()

    val me get() = """{"id":"$ME_ID","name":"Moses Mwicigi","email":"moses@bethanyhouse.co.ke","role":"admin",
        "is_available":true,"is_superuser":true,"active_convs":4,"avatar_url":null,"created_at":"${ago(60 * 24 * 200)}",
        "last_seen_at":"${ago(1)}","custom_role_id":null,"custom_permissions":null,"role_name":null,"role_color":null,"role_permissions":null}"""

    val agents get() = """[
      $me,
      {"id":"$AGENT2_ID","name":"Grace Wanjiru","email":"grace@bethanyhouse.co.ke","role":"agent","is_available":true,
       "is_superuser":false,"active_convs":7,"avatar_url":null,"created_at":"${ago(60 * 24 * 120)}","last_seen_at":"${ago(3)}",
       "custom_role_id":"sales","custom_permissions":null,"role_name":"Sales","role_color":"#3b82f6",
       "role_permissions":["view_conversations","reply_conversations","intercept_release","transfer_conversations","add_notes","view_orders","manage_orders","view_catalog","view_crm","edit_crm","view_leads"]},
      {"id":"$AGENT3_ID","name":"Brian Otieno","email":"brian@bethanyhouse.co.ke","role":"readonly","is_available":false,
       "is_superuser":false,"active_convs":0,"avatar_url":null,"created_at":"${ago(60 * 24 * 30)}","last_seen_at":"${ago(60 * 26)}",
       "custom_role_id":null,"custom_permissions":null,"role_name":null,"role_color":null,"role_permissions":null}
    ]"""

    val orders get() = """[
      {"id":"o1","wa_id":"254712345678","items":[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"unit":3500,"total":7000,"sku":"CS-BLK-16"},
        {"name":"Roman Collar Tab","qty":4,"unit":250,"total":1000,"sku":"RC-TAB"}],"subtotal":8000,"currency":"KES","status":"confirmed",
        "payment_status":"paid","fulfillment_status":"unfulfilled","channel":"whatsapp","created_at":"${ago(45)}","updated_at":"${ago(30)}",
        "contact_name":"Fr. Peter Kamau","hub_order_id":1042,"hub_order_number":"BH-1042","hub_push_status":"pushed","hub_status":"processing",
        "hub_payment_status":"paid","hub_public_token":"tok1042"},
      {"id":"o2","wa_id":"254722000111","items":[{"name":"Cassock — Purple, L","qty":1,"unit":12500,"total":12500}],"subtotal":12500,
        "currency":"KES","status":"open","payment_status":"pending","channel":"messenger","created_at":"${ago(180)}","contact_name":"Rev. Mary Achieng",
        "hub_push_status":"failed","hub_last_error":"Variant out of stock in hub"},
      {"id":"o3","wa_id":"255754333222","items":[{"name":"Stole — Green","qty":1,"unit":4800,"total":4800}],"subtotal":4800,"currency":"KES",
        "status":"delivered","payment_status":"paid","channel":"whatsapp","created_at":"${ago(60 * 30)}","contact_name":"Deacon John Mushi",
        "hub_order_number":"BH-1031","hub_status":"completed"},
      {"id":"o4","wa_id":"254700999888","items":[{"name":"Alb — White, M","qty":3,"unit":6000,"total":18000}],"subtotal":18000,"currency":"KES",
        "status":"cancelled","payment_status":"refunded","channel":"instagram","created_at":"${ago(60 * 72)}","contact_name":"Sr. Lucy Njeri"}
    ]"""

    val catalog get() = """[
      {"hub_product_id":501,"sku":"CS-BLK","name":"Clergy Shirt","aliases":["clerical shirt","collar shirt"],"price":3500,
       "category":"Shirts","description":"Tab-collar clergy shirt, poly-cotton, long sleeve.","in_stock":true,"available_qty":42,
       "price_kes":3500,"price_usd":27,"price_min_kes":3500,"price_max_kes":4200,"product_type":"variable",
       "variants":[{"variant_id":1,"sku":"CS-BLK-15","label":"Clergy Shirt — Black, 15 inch","attributes":{"Colour":"Black","Size":"15 inch"},"price_kes":3500,"price_usd":27},
                   {"variant_id":2,"sku":"CS-BLK-16","label":"Clergy Shirt — Black, 16 inch","attributes":{"Colour":"Black","Size":"16 inch"},"price_kes":3500,"price_usd":27},
                   {"variant_id":3,"sku":"CS-BLU-16","label":"Clergy Shirt — Blue, 16 inch","attributes":{"Colour":"Blue","Size":"16 inch"},"price_kes":4200,"price_usd":32}]},
      {"hub_product_id":502,"sku":"CAS-PUR","name":"Cassock","aliases":[],"price":12500,"category":"Vestments","description":"Anglican double-breasted cassock.",
       "in_stock":true,"available_qty":6,"price_kes":12500,"price_usd":96,"variants":[]},
      {"hub_product_id":503,"sku":"STL-GRN","name":"Stole","aliases":["stola"],"price":4800,"category":"Vestments","description":"Embroidered green stole.",
       "in_stock":false,"available_qty":0,"price_kes":4800,"price_usd":37,"variants":[]},
      {"id":"c-local-1","sku":"RC-TAB","name":"Roman Collar Tab","aliases":["collar tab"],"price":250,"unit":"piece","category":"Accessories",
       "description":"Replacement white collar tab.","in_stock":true}
    ]"""

    val stats = """{"open_conversations":128,"human_conversations":9,"ai_conversations":119,"active_agents":2,"total_agents":3,
      "total_revenue":1284500,"total_orders":284,"pending_orders":21,"delivered_orders":203,"confirmed_orders":48,"cancelled_orders":12,
      "in_stock_items":187,"total_items":214,
      "channel_breakdown":[{"channel":"whatsapp","count":96,"open":80},{"channel":"messenger","count":21,"open":30},{"channel":"instagram","count":11,"open":18}]}"""

    fun conv(id: String, name: String?, waId: String, channel: String, mode: String, preview: String, minutes: Long,
             unread: Int = 0, stage: String? = null, orders: Int = 0, person: String? = null, agent: String? = null,
             tags: String = "[]", iso: String = "KE") = """{"id":"$id","wa_id":"$waId","external_id":"$waId","person_id":${person?.let { "\"$it\"" }},
        "intercept_mode":"$mode","lead_stage":${stage?.let { "\"$it\"" }},"assigned_agent_id":${agent?.let { "\"$it\"" }},
        "assigned_agent_name":${if (agent == ME_ID) "\"Moses Mwicigi\"" else if (agent != null) "\"Grace Wanjiru\"" else "null"},
        "intercept_since":null,"last_message_at":"${ago(minutes)}","last_message_preview":"$preview","status":"open",
        "created_at":"${ago(minutes + 600)}","updated_at":"${ago(minutes)}","name":${name?.let { "\"$it\"" }},"avatar_url":null,
        "orders_count":$orders,"channel":"$channel","unread":$unread,"country":null,"country_iso":"$iso","tags":$tags}"""

    val conversations get() = listOf(
        conv("c1", "Fr. Peter Kamau", "254712345678", "whatsapp", "human", "Can you deliver to Nyeri by Friday?", 2, unread = 2, stage = "proposal", orders = 3, person = "p1", agent = ME_ID, tags = """["vip","clergy"]"""),
        conv("c2", "Rev. Mary Achieng", "254722000111", "messenger", "ai", "Asante! How much is the purple cassock?", 9, unread = 1, stage = "qualified"),
        conv("c3", null, "255754333222", "whatsapp", "paused", "📷 Photo", 34, stage = "new", iso = "TZ"),
        conv("c4", "Sr. Lucy Njeri", "17840000000000001", "instagram", "ai", "Do you have albs in size M?", 75, stage = "contacted"),
        conv("c5", "Fr. Peter Kamau", "25898765432101234", "facebook", "ai", "Commented: Beautiful stoles! 🙏", 240, person = "p1"),
        conv("c6", "Deacon James Mwangi", "254733444555", "whatsapp", "human", "I'll send the measurements tonight", 60 * 5, stage = "negotiation", agent = AGENT2_ID),
    )

    val conversationPage get() = """{"items":[${conversations.joinToString(",")}],"next_cursor":"cursor-2"}"""
    val summary = """{"unread":2,"human":2,"yours":1,"unread_messages":{"all":3,"whatsapp":2,"messenger":1},"tags":["vip","clergy","bulk"]}"""

    val messages get() = """[
      {"id":"m1","type":"message","direction":"inbound","sender":"user","text":"Habari! Do you make clergy shirts?","created_at":"${ago(60 * 26)}"},
      {"id":"m2","type":"message","direction":"outbound","sender":"ai","text":"Habari Father! Yes 🙏 Our *Clergy Shirt* is KES 3,500 in black, and KES 4,200 in blue. What collar size do you wear?","created_at":"${ago(60 * 26 - 1)}"},
      {"id":"m3","type":"message","direction":"inbound","sender":"user","text":"16 inch, two black ones please","created_at":"${ago(50)}"},
      {"id":"e1","type":"system_event","direction":"outbound","sender":"ai","text":"Picked up by Moses Mwicigi","created_at":"${ago(20)}","event_kind":"intercept"},
      {"id":"m4","type":"message","direction":"inbound","sender":"user","text":"","created_at":"${ago(15)}","media_type":"image","media_url":"https://neema.test/media/collar.jpg","media_caption":"Like this collar"},
      {"id":"m5","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","text":"Yes, that's our standard tab collar. Two black 16\" shirts come to KES 7,000.","created_at":"${ago(10)}"},
      {"id":"n1","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","isNote":true,"text":"Repeat buyer — offer free delivery","created_at":"${ago(8)}"},
      {"id":"m6","type":"message","direction":"inbound","sender":"user","text":"Can you deliver to Nyeri by Friday?","created_at":"${ago(2)}","reply_to":{"id":"m5","text":"Yes, that's our standard tab collar.","sender":"human_agent"}}
    ]"""

    val calls get() = """[
      {"id":"k1","call_id":"wacid.1","wa_id":"254712345678","name":"Fr. Peter Kamau","direction":"inbound","status":"answered","duration":184,
       "agent_name":"Moses Mwicigi","started_at":"${ago(40)}","summary":"Wants two black clergy shirts delivered to Nyeri by Friday.","transcript_status":"done","has_recording":true},
      {"id":"k2","call_id":"wacid.2","wa_id":"254722000111","name":"Rev. Mary Achieng","direction":"inbound","status":"missed","duration":null,
       "agent_name":null,"started_at":"${ago(130)}","transcript_status":"none","has_recording":false},
      {"id":"k3","call_id":"wacid.3","wa_id":"254733444555","name":"Deacon James Mwangi","direction":"outbound","status":"answered","duration":61,
       "agent_name":"Grace Wanjiru","started_at":"${ago(60 * 20)}","transcript_status":"pending","has_recording":true}
    ]"""

    val deals get() = """{"deals":[
      {"id":"d1","conversation_id":"c1","customer":"Fr. Peter Kamau","wa_id":"254712345678","channel":"whatsapp","title":"2× Clergy Shirt (Black 16\")",
       "items":[{"name":"Clergy Shirt","qty":2,"price":3500}],"stage":"proposal","blocking":"Needs delivery date confirmed",
       "next_action":{"kind":"follow_up","owner":"ai","due_at":"${Instant.now().plus(3, ChronoUnit.HOURS)}","note":"Confirm Nyeri delivery"},"guidance":"Offer free delivery","status":"open","updated_at":"${ago(12)}"},
      {"id":"d2","conversation_id":"c2","customer":"Rev. Mary Achieng","wa_id":"254722000111","channel":"messenger","title":"Purple cassock",
       "items":[],"stage":"qualified","blocking":null,"next_action":null,"guidance":null,"status":"open","updated_at":"${ago(90)}"},
      {"id":"d3","conversation_id":"c6","customer":"Deacon James Mwangi","wa_id":"254733444555","channel":"whatsapp","title":"Made-to-measure alb",
       "items":[],"stage":"new","blocking":"Waiting for measurements","next_action":{"kind":"follow_up","owner":"human","due_at":"${ago(-60 * 20)}"},"guidance":null,"status":"open","updated_at":"${ago(300)}"}
    ]}"""

    val actions get() = """{"actions":[
      {"id":"x1","deal_id":"d1","conversation_id":"c1","due_at":null,"kind":"follow_up","reason":"Father asked about Friday delivery 2h ago and hasn't had an answer",
       "draft":"Hello Father Peter 🙏 Just confirming — we can deliver both shirts to Nyeri by Friday. Shall I send the M-Pesa details?","status":"pending","created_by":"neema"}
    ]}"""

    val attribution = """{"sources":[{"source":"facebook_ad","post":"1203","post_title":"Easter vestments sale","leads":42,"orders":11,"revenue":186000,"paid_revenue":152000},
      {"source":"instagram","post":null,"leads":18,"orders":4,"revenue":51000,"paid_revenue":51000},
      {"source":"organic","post":null,"leads":77,"orders":30,"revenue":402000,"paid_revenue":377500}],
      "unattributed":{"orders":9,"revenue":64000,"paid_revenue":60000},"totals":{"leads":137,"orders":54,"revenue":703000}}"""

    val roles = """[{"id":"admin","name":"Admin","description":"Full system access","color":"#f59e0b","permissions":["view_conversations","manage_agents","manage_roles","manage_settings"],"protected":true},
      {"id":"sales","name":"Sales","description":"Handles conversations and orders","color":"#3b82f6","permissions":["view_conversations","reply_conversations","view_orders","manage_orders"],"protected":false}]"""

    fun install(f: FakeNeema) {
        // Generic routes first: later registrations take priority over them.
        f.on("GET", "/admin/conversations/[^/]+") { r, _ ->
            val id = r.url.pathSegments.last()
            200 to (conversations.firstOrNull { it.contains("\"id\":\"$id\"") } ?: conversations.first())
        }
        f.on("GET", "/admin/me", body = me)
        f.on("GET", "/admin/agents", body = agents)
        f.on("GET", "/admin/orders", body = orders)
        f.on("GET", "/admin/catalog", body = catalog)
        f.on("GET", "/admin/catalog/audit", body = """{"currency_gaps":[{"name":"Cassock","category":"Vestments","kes":12500,"usd":110,"usd_expected":96.2,"factor":1.14}],"per_piece":[],"checked":214,"rate":130}""")
        f.on("GET", "/admin/stats", body = stats)
        f.on("GET", "/admin/attribution", body = attribution)
        // Paged when the caller sends `limit` (the inbox); the bare legacy array otherwise (Reports).
        f.on("GET", "/admin/conversations") { r, _ ->
            200 to (if (r.url.queryParameter("limit") != null) conversationPage else "[${conversations.joinToString(",")}]")
        }
        f.on("GET", "/admin/conversations/summary", body = summary)
        f.on("GET", "/admin/conversations/[^/]+/messages", body = messages)
        f.on("GET", "/admin/conversations/[^/]+/window", body = """{"mode":"open","channel":"whatsapp","last_inbound_at":"${ago(2)}","expires_at":"${Instant.now().plus(1438, ChronoUnit.MINUTES)}"}""")
        f.on("GET", "/admin/conversations/[^/]+/latest-draft", body = """{"draft":null}""")
        f.on("GET", "/admin/conversations/[^/]+/activity", body = """{"events":[{"id":"ev1","kind":"order","label":"Order BH-1042 paid","detail":"KES 8,000 via M-Pesa","at":"${ago(30)}"},{"id":"ev2","kind":"intercept","label":"Picked up by Moses","at":"${ago(20)}"}]}""")
        f.on("GET", "/admin/calls", body = calls)
        f.on("GET", "/admin/deals", body = deals)
        f.on("GET", "/admin/actions", body = actions)
        f.on("GET", "/admin/roles", body = roles)
        f.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["measuring"]}""")
        f.on("GET", "/admin/settings/directives", body = """{"directives":"Always offer free delivery within Nairobi on orders above KES 10,000.","max_chars":2000}""")
        f.on("GET", "/admin/settings/translation", body = """{"enabled":true,"default":false,"spend_30d_usd":3.42,"calls_30d":812}""")
        f.on("GET", "/admin/settings/offer", body = """{"campaign":{"name":"Easter Sale","percent":10,"scope":"category","categories":["Vestments"],"skus":[],"starts_on":null,"ends_on":"2099-04-30"},"running":true,"says":"Easter Sale: 10% off all Vestments until 30 April.","max_percent":30}""")
        // Writes succeed by default; tests override to simulate failures.
        listOf("POST", "PATCH", "PUT", "DELETE").forEach { m -> f.on(m, "/.*") { _, _ -> 200 to """{"ok":true}""" } }
        // Order matters: routes registered later win, so re-register specific GETs above the catch-all writes.
    }
}
