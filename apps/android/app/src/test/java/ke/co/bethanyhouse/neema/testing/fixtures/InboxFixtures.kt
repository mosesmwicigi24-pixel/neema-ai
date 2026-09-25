package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.Fixtures.ago
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * Inbox + thread data beyond the base [Fixtures]: a web-chat visitor, a thread
 * with every bubble and media type, and window states. Shapes follow
 * apps/api/app/routers/admin.py (GET /admin/conversations/{id}/messages).
 */
object InboxFixtures {
    /** A web-chat visitor: `web_<sha1[:20]>` on the default channel (web_chat.py). */
    val webVisitor get() = Fixtures.conv(
        "c7", null, "web_3fa9c1e20b7d4c5a9e11", "whatsapp", "ai", "Do you ship to Kampala?", 20, unread = 1, iso = "UG",
    )

    val conversations get() = Fixtures.conversations + webVisitor
    val page get() = """{"items":[${conversations.joinToString(",")}],"next_cursor":"cursor-2"}"""

    /** Every bubble the thread can draw, oldest first. */
    val richThread get() = """[
      {"id":"r1","type":"message","direction":"inbound","sender":"user","text":"Habari! *Bold*, _italic_, ~gone~ and `code` — see www.bethanyhouse.co.ke","created_at":"${ago(300)}","translation":"Hello! Bold, italic, gone and code","translated_from":"sw"},
      {"id":"r2","type":"message","direction":"outbound","sender":"ai","text":"Karibu! Our clergy shirts start at KES 3,500.","created_at":"${ago(299)}","translation":"Welcome! Our clergy shirts start at KES 3,500.","translated_from":"sw"},
      {"id":"e1","type":"system_event","direction":"outbound","sender":"ai","text":"Escalated","created_at":"${ago(290)}","event_kind":"escalated","event_reason":"Customer asked for a custom embroidery quote"},
      {"id":"e2","type":"system_event","direction":"outbound","sender":"ai","text":"Picked up by Moses","created_at":"${ago(289)}","event_kind":"intercept","agent_name":"Moses Mwicigi"},
      {"id":"e3","type":"system_event","direction":"outbound","sender":"ai","text":"Flagged","created_at":"${ago(288)}","event_kind":"flag"},
      {"id":"e4","type":"system_event","direction":"outbound","sender":"ai","text":"Paused by Moses Mwicigi — replies held","created_at":"${ago(287)}","event_kind":"pause"},
      {"id":"i1","type":"message","direction":"inbound","sender":"user","text":"","created_at":"${ago(280)}","media_type":"image","media_url":"https://neema.test/media/a1.jpg"},
      {"id":"i2","type":"message","direction":"inbound","sender":"user","text":"","created_at":"${ago(280)}","media_type":"image","media_url":"https://neema.test/media/a2.jpg"},
      {"id":"i3","type":"message","direction":"inbound","sender":"user","text":"The purple one","created_at":"${ago(279)}","media_type":"image","media_url":"https://neema.test/media/a3.jpg"},
      {"id":"t1","type":"message","direction":"inbound","sender":"user","text":"And this collar?","created_at":"${ago(270)}"},
      {"id":"i4","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","text":"","created_at":"${ago(265)}","media_type":"image","media_url":"https://neema.test/media/collar.jpg","media_caption":"A black clergy shirt with a white tab collar."},
      {"id":"v1","type":"message","direction":"inbound","sender":"user","text":"Here is the fit","created_at":"${ago(260)}","media_type":"video","media_url":"https://neema.test/media/fit.mp4"},
      {"id":"a1","type":"message","direction":"inbound","sender":"user","text":"Nataka shati mbili nyeusi","created_at":"${ago(250)}","media_type":"audio","media_url":"https://neema.test/media/v.ogg"},
      {"id":"a2","type":"message","direction":"outbound","sender":"ai","text":"Sawa — two black shirts.","created_at":"${ago(249)}","media_type":"audio","media_url":"https://neema.test/media/r.ogg","media_caption":"🛒 2 × Clergy Shirt — Black, 16 inch · KES 7,000"},
      {"id":"d1","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","text":"","created_at":"${ago(240)}","media_type":"document","media_url":"https://neema.test/media/Invoice-BH-1042.pdf","filename":"Invoice-BH-1042.pdf"},
      {"id":"x1","type":"message","direction":"inbound","sender":"user","text":"[image]","created_at":"${ago(230)}","media_type":"image"},
      {"id":"x2","type":"message","direction":"inbound","sender":"user","text":"","created_at":"${ago(225)}"},
      {"id":"k1","type":"message","direction":"inbound","sender":"user","text":"[comment] How much is this stole?","created_at":"${ago(200)}","comment_context":{"post_id":"p_77","title":"New Advent stoles — hand-embroidered in Nairobi","permalink":"https://facebook.com/p/77","thumb":"https://neema.test/media/post.jpg","media_type":"video","has_video":true}},
      {"id":"k2","type":"message","direction":"outbound","sender":"ai","text":"Hi! It is KES 4,800 — sent you a DM 🙏","created_at":"${ago(199)}","comment_context":{"post_id":"p_77","reply_to":"k1"}},
      {"id":"k3","type":"message","direction":"inbound","sender":"user","text":"[comment] Do you have it in green?","created_at":"${ago(198)}","comment_context":{"post_id":"p_77","title":"New Advent stoles — hand-embroidered in Nairobi","permalink":"https://facebook.com/p/77","thumb":"https://neema.test/media/post.jpg"}},
      {"id":"n1","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","isNote":true,"text":"Repeat buyer — offer free delivery to Nyeri","created_at":"${ago(12)}"},
      {"id":"m5","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","text":"Yes, that's our standard tab collar. Two black 16\" shirts come to KES 7,000.","created_at":"${ago(10)}"},
      {"id":"m6","type":"message","direction":"inbound","sender":"user","text":"Can you deliver to Nyeri by Friday?","created_at":"${ago(2)}","reply_to":{"id":"m5","text":"Yes, that's our standard tab collar.","sender":"human_agent"}},
      {"id":"m7","type":"message","direction":"inbound","sender":"user","text":"This one 👇","created_at":"${ago(1)}","reply_to":{"id":"i4","text":"[image]","sender":"human_agent","media_type":"image","media_url":"https://neema.test/media/collar.jpg"}}
    ]"""

    fun windowOpen() = """{"mode":"open","channel":"whatsapp","last_inbound_at":"${ago(2)}","expires_at":"${Instant.now().plus(1438, ChronoUnit.MINUTES)}"}"""
    fun windowHumanAgent() = """{"mode":"human_agent","channel":"messenger","last_inbound_at":"${ago(60 * 30)}","expires_at":"${ago(60 * 6)}","human_agent_until":"${Instant.now().plus(60 * 24 * 5 + 190, ChronoUnit.MINUTES)}"}"""
    fun windowClosed() = """{"mode":"closed","channel":"whatsapp","last_inbound_at":"${ago(60 * 24 * 3)}","reason":"WhatsApp's 24h window closed 2d ago — only an approved template can reach them now."}"""

    /** `n` plain messages ending `minutesAgo` minutes back — for paging. */
    fun plainPage(prefix: String, n: Int, startMinutesAgo: Long): String = (0 until n).joinToString(",", "[", "]") { i ->
        """{"id":"$prefix$i","type":"message","direction":"${if (i % 2 == 0) "inbound" else "outbound"}","sender":"${if (i % 2 == 0) "user" else "ai"}","text":"$prefix message $i","created_at":"${ago(startMinutesAgo - i)}"}"""
    }

    fun install(f: FakeNeema) {
        f.on("GET", "/admin/conversations", body = page)
        f.on("GET", "/admin/conversations/[^/]+") { r, _ ->
            val id = r.url.pathSegments.last()
            200 to (conversations.firstOrNull { it.contains("\"id\":\"$id\"") } ?: conversations.first())
        }
        f.on("GET", "/admin/conversations/summary", body = Fixtures.summary)
        f.on("GET", "/admin/conversations/[^/]+/messages", body = Fixtures.messages)
        f.on("GET", "/admin/conversations/[^/]+/window", body = windowOpen())
        f.on("GET", "/admin/conversations/[^/]+/latest-draft", body = """{"draft":null}""")
        // What the server really answers for the controls (services/conversation.py).
        f.on("POST", "/admin/conversations/[^/]+/intercept", body = """{"ok":true,"mode":"human","assigned_to":"${Fixtures.ME_ID}"}""")
        f.on("POST", "/admin/conversations/[^/]+/release", body = """{"ok":true,"mode":"ai"}""")
        f.on("POST", "/admin/conversations/[^/]+/pause", body = """{"id":"c1","intercept_mode":"paused"}""")
        f.on("POST", "/admin/conversations/[^/]+/transfer", body = """{"ok":true,"transferred_to":"${Fixtures.AGENT2_ID}"}""")
        f.on("POST", "/admin/conversations/[^/]+/note") { _, b ->
            200 to """{"id":"srv-note","type":"message","direction":"outbound","sender":"human_agent","text":"note","isNote":true,"created_at":"${Instant.now()}"}"""
        }
        f.on("POST", "/admin/conversations/[^/]+/generate-draft", body = """{"draft":"Hello Father 🙏 Yes — we deliver to Nyeri by Friday. Shall I send the M-Pesa details?"}""")
        f.on("POST", "/admin/conversations/[^/]+/translate-reply", body = """{"text":"Ndiyo, tutafikisha Ijumaa.","lang":"sw"}""")
        f.on("DELETE", "/admin/conversations/[^/]+/messages", body = """{"ok":true}""")
    }
}
