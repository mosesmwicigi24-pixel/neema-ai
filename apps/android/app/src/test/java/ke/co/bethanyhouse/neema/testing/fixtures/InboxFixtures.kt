package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.Fixtures.ago
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
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

    // services/conversation.py messaging_window — every key it returns, its own reason strings.
    fun windowOpen() = """{"mode":"open","channel":"whatsapp","last_inbound_at":"${iso(2)}","expires_at":"${isoIn(1438)}","human_agent_until":null,"reason":""}"""
    fun windowHumanAgent() = """{"mode":"human_agent","channel":"messenger","last_inbound_at":"${iso(60 * 30)}","expires_at":"${iso(60 * 6)}","human_agent_until":"${isoIn(60 * 24 * 5 + 190)}","reason":"24h window closed — sending as a human agent (Meta allows 7 days)"}"""
    fun windowClosed() = """{"mode":"closed","channel":"whatsapp","last_inbound_at":"${iso(60 * 24 * 3)}","expires_at":"${iso(60 * 24 * 2)}","human_agent_until":null,"reason":"Outside the messaging window — an approved template is the only way in"}"""

    /** Python's `datetime.isoformat()` of an aware UTC timestamp: microseconds and "+00:00", never "Z". */
    fun iso(minutesAgo: Long): String = PY_ISO.format(AppClock.instant().atOffset(ZoneOffset.UTC).minusMinutes(minutesAgo))
    fun isoIn(minutes: Long): String = iso(-minutes)
    private val PY_ISO: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSSxxx")

    /**
     * Server-exact wire shapes, built from what each handler in
     * apps/api/app/routers/admin.py (and the services it calls) returns — for
     * the contract tests. Meta rows here are real: `wa_id` is null and the
     * PSID is the `external_id`.
     */
    object Contract {
        // admin.py _conversation_rows — the exact key set, in its order.
        fun row(
            id: String, name: String?, waId: String?, externalId: String, channel: String, mode: String, preview: String, minutes: Long,
            unread: Int = 0, person: String? = null, agentId: String? = null, agentName: String? = null, tags: String = "[]",
            stage: String? = null, orders: Int = 0, country: String? = "KE",
        ) = """{"id":"$id","wa_id":${waId?.let { "\"$it\"" } ?: "null"},"person_id":${person?.let { "\"$it\"" } ?: "null"},
          "external_id":"$externalId","intercept_mode":"$mode","assigned_agent_id":${agentId?.let { "\"$it\"" } ?: "null"},
          "assigned_agent_name":${agentName?.let { "\"$it\"" } ?: "null"},"intercept_since":${if (mode == "human") "\"${iso(minutes + 5)}\"" else "null"},
          "last_message_at":"${iso(minutes)}","last_message":"$preview","last_message_preview":"$preview","status":"open",
          "created_at":"${iso(minutes + 900)}","updated_at":"${iso(minutes)}","name":${name?.let { "\"$it\"" } ?: "null"},"avatar_url":null,
          "country_iso":${country?.let { "\"$it\"" } ?: "null"},"flag_url":${country?.let { "\"https://flagcdn.com/${it.lowercase()}.svg\"" } ?: "null"},
          "channel":"$channel","unread":$unread,"orders_count":$orders,"lead_stage":${stage?.let { "\"$it\"" } ?: "null"},"tags":$tags}"""

        val peterWa get() = row("k1", "Fr. Peter Kamau", "254712345678", "254712345678", "whatsapp", "human", "Can you deliver to Nyeri by Friday?", 2,
            unread = 2, person = "p1", agentId = Fixtures.ME_ID, agentName = "Moses Mwicigi", tags = """["vip","clergy"]""", stage = "proposal", orders = 3)
        /** A Messenger thread: no wa_id, the PSID is the key; flag from nothing (no phone). */
        val maryMsgr get() = row("k2", "Rev. Mary Achieng", null, "7123456789012345", "messenger", "ai", "Asante! How much is the purple cassock?", 9,
            unread = 1, person = "p2", country = null)
        /** Tags straight off a hand-edited JSONB state: a bare string, not a list. */
        val oddTags get() = row("k3", "Deacon James", "254733444555", "254733444555", "whatsapp", "ai", "Sawa", 40, tags = "\"vip\"")
        /** Tags with a null and a number inside, as JSONB allows. */
        val mixedTags get() = row("k4", null, "255754333222", "255754333222", "whatsapp", "paused", "📷 Photo", 60, tags = """["bulk",null,7,""]""", country = "TZ")
        /** A web-chat visitor (web_chat.py): `web_<sha1[:20]>` on the default channel. */
        val visitor get() = row("k5", null, "web_3fa9c1e20b7d4c5a9e11", "web_3fa9c1e20b7d4c5a9e11", "whatsapp", "ai", "Do you ship to Kampala?", 80, country = null)
        /** Peter's Facebook comment thread — the same person as k1. */
        val peterFb get() = row("k6", "Fr. Peter Kamau", null, "25898765432101234", "facebook", "ai", "Beautiful stoles! 🙏", 240, person = "p1", country = null)

        // admin.py list_conversations (with limit): {items, next_cursor}; the cursor is base64url, unpadded.
        fun page(vararg rows: String, cursor: String? = null) =
            """{"items":[${rows.joinToString(",")}],"next_cursor":${cursor?.let { "\"$it\"" } ?: "null"}}"""
        const val CURSOR = "WyIyMDI2LTA5LTI1VDA5OjU4OjAwLjEyMzQ1NiswMDowMCIsInAxIl0"

        // admin.py conversations_summary.
        const val summary = """{"unread":2,"human":1,"yours":1,"unread_messages":{"all":3,"whatsapp":2,"messenger":1},"tags":["bulk","clergy","vip"]}"""

        // admin.py resolve_conversation: {"conversation_id": <uuid>|null}.
        const val resolved = """{"conversation_id":"k2"}"""
        const val unresolved = """{"conversation_id":null}"""

        // admin.py get_thread page one: _shape_messages_into items + the intercept timeline
        // as system_event items (id "evt-<uuid>", no media keys), sorted by created_at.
        fun thread() = """[
          {"id":"m1","type":"message","direction":"inbound","sender":"user","text":"Bonjour, vous livrez à Kigali ?","translation":"Hello, do you deliver to Kigali?","translated_from":"French","isNote":false,"agent_name":null,"created_at":"${iso(30)}","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":null,"reply_to":null},
          {"id":"evt-9f1","type":"system_event","direction":"outbound","sender":"ai","text":"Escalated — needs human","created_at":"${iso(29)}","event_kind":"escalated","event_reason":"Asked for a delivery quote","agent_name":null},
          {"id":"m2","type":"message","direction":"inbound","sender":"user","text":null,"translation":null,"translated_from":null,"isNote":false,"agent_name":null,"created_at":"${iso(20)}","media_type":"image","media_id":"wamid.MEDIA1","media_url":"https://api.bethanyhouse.co.ke/api/admin/media/a1.jpg","media_caption":"A purple clergy stole","mime_type":"image/jpeg","filename":null,"comment_context":null,"reply_to":null},
          {"id":"m3","type":"message","direction":"outbound","sender":"human_agent","text":"Oui, 5 jours.","translation":"Yes, 5 days.","translated_from":"French","isNote":false,"agent_name":"Moses Mwicigi","created_at":"${iso(10)}","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":null,"reply_to":{"id":"m1","text":"Bonjour, vous livrez à Kigali ?","sender":"user","media_type":null,"media_url":null}},
          {"id":"m4","type":"message","direction":"outbound","sender":"human_agent","text":"Repeat buyer","translation":null,"translated_from":null,"isNote":true,"agent_name":"Moses Mwicigi","created_at":"${iso(8)}","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":null,"reply_to":null},
          {"id":"m5","type":"message","direction":"inbound","sender":"user","text":"[comment] Price?","translation":null,"translated_from":null,"isNote":false,"agent_name":null,"created_at":"${iso(5)}","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":{"post_id":"p_77","title":"Advent stoles","permalink":"https://facebook.com/p/77","thumb":null},"reply_to":null}
        ]"""

        // admin.py conversations/{id}/activity: {"events": [...]} newest first; detail may be "" or null.
        fun activity() = """{"events":[
          {"id":"icpt-1","kind":"intercept","label":"Picked up by Moses Mwicigi","detail":"Moses Mwicigi","at":"${iso(20)}"},
          {"id":"act-2","kind":"checkin_sent","label":"Check-in sent","detail":"","at":"${iso(60)}"},
          {"id":"ord-3","kind":"order","label":"Order open · unpaid","detail":"2 items — KES 7000","at":null},
          {"id":"tool-4","kind":"tool","label":"Looked up the catalogue","detail":null,"at":"${iso(90)}"}
        ]}"""

        // services/conversation.py — the controls' real answers.
        val intercept get() = """{"ok":true,"mode":"human","assigned_to":"${Fixtures.ME_ID}"}"""
        val interceptAlready get() = """{"id":"k1","intercept_mode":"human","assigned_agent_id":"${Fixtures.ME_ID}","already":true}"""
        const val interceptConflict = """{"detail":"Already handled by Grace Wanjiru. They must release or transfer it first."}"""
        const val release = """{"ok":true,"mode":"ai"}"""
        const val releaseAlready = """{"id":"k1","intercept_mode":"ai","assigned_agent_id":null,"already":true}"""
        val pause get() = """{"id":"k1","intercept_mode":"paused","assigned_agent_id":"${Fixtures.ME_ID}"}"""
        const val pauseConflict = """{"detail":"Handled by Grace Wanjiru — they must pause or release it."}"""
        val transfer get() = """{"ok":true,"transferred_to":"${Fixtures.AGENT2_ID}"}"""

        // send_agent_reply: the saved row — or 200 {ok:false, error} when delivery failed.
        fun replySent(text: String) = """{"id":"srv-r1","direction":"outbound","sender":"human_agent","text":"$text","reply_to":null,"created_at":"${iso(0)}"}"""
        const val replyFailed = """{"ok":false,"error":"Couldn't send the reply: (#10) This message is sent outside of allowed window."}"""
        const val replyLocked = """{"detail":"Conversation is handled by Grace Wanjiru."}"""
        const val replySms = """{"detail":"SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."}"""

        // translate.translate_reply: always {text, lang}; lang null when nothing was translated.
        const val translated = """{"text":"Oui, nous livrons vendredi.","lang":"French"}"""
        const val untranslated = """{"text":"Yes, Friday.","lang":null}"""

        // add_note → the note row; approve_draft → the sent row (not {ok}).
        fun note(text: String) = """{"id":"srv-n1","type":"message","direction":"outbound","sender":"human_agent","text":"$text","isNote":true,"created_at":"${iso(0)}"}"""
        fun approved(text: String) = """{"id":"srv-a1","direction":"outbound","sender":"ai","text":"$text","created_at":"${iso(0)}"}"""
        const val noDraft = """{"detail":"No draft text found to approve"}"""
        const val latestDraftNone = """{"draft":null}"""
        const val latestDraft = """{"draft":"Bonjour 🙏 Oui, nous livrons à Kigali en 5 jours."}"""
        const val generated = """{"draft":"Yes Father — Nyeri by Friday. Shall I send the M-Pesa details?"}"""
        const val generateNoMessages = """{"detail":"No messages to draft from"}"""

        // ask_neema / answer_through_neema.
        const val answer = """{"answer":"Collar 16 inch, chest 42 — from BH-1042."}"""
        const val sent = """{"ok":true,"sent":"Yes Reverend — KES 12,500, ready in 5 days 🙏"}"""
        const val outsideWindow = """{"detail":"outside the messaging window — send it as a template, or reply yourself when they next write"}"""

        // upload_media → send_agent_media's row: text is the CAPTION (null when none).
        fun uploaded(type: String, url: String, caption: String?) =
            """{"id":"srv-u1","direction":"outbound","sender":"human_agent","media_type":"$type","media_url":"$url","text":${caption?.let { "\"$it\"" } ?: "null"},"created_at":"${iso(0)}"}"""
        const val tooLarge = """{"detail":"Image too large — max 5 MB."}"""
        const val unsupported = """{"detail":"Unsupported media type: video/webm"}"""
        const val unconvertible = """{"detail":"Couldn't convert this video for WhatsApp — try a shorter clip or export it as MP4 (H.264)."}"""
        /** nginx's own 413 page — the request never reached FastAPI. */
        const val proxyTooLarge = "<html><head><title>413 Request Entity Too Large</title></head><body><center><h1>413 Request Entity Too Large</h1></center><hr><center>nginx</center></body></html>"

        // recover_message_media / post_video.
        const val recovered = """{"ok":true,"media_url":"https://api.bethanyhouse.co.ke/api/admin/media/rehosted.jpg","media_type":"image"}"""
        const val recoverGone = """{"detail":"Meta no longer has this attachment — it can't be recovered."}"""
        const val postVideo = """{"video_url":"https://video.xx.fbcdn.net/v/t42/reel.mp4?oe=1"}"""

        // clear_chat_history.
        const val cleared = """{"ok":true,"cleared":true,"conversation_id":"k1"}"""
        const val clearForbidden = """{"detail":"Only admins can clear chat history"}"""

        // whatsapp_invite.
        const val invited = """{"ok":true,"wa_id":"250788123456"}"""
        const val inviteBadPhone = """{"detail":"A valid phone number is required to invite to WhatsApp."}"""

        // FastAPI's own 422 for a malformed request: a pydantic error LIST, not a string.
        const val pydantic422 = """{"detail":[{"type":"missing","loc":["body","file"],"msg":"Field required","input":null}]}"""
    }

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
        f.on("POST", "/admin/conversations/[^/]+/intercept", body = Contract.intercept)
        f.on("POST", "/admin/conversations/[^/]+/release", body = Contract.release)
        f.on("POST", "/admin/conversations/[^/]+/pause", body = Contract.pause)
        f.on("POST", "/admin/conversations/[^/]+/transfer", body = Contract.transfer)
        // admin.py add_note → the note row.
        f.on("POST", "/admin/conversations/[^/]+/note") { _, _ -> 200 to Contract.note("note") }
        // send_agent_reply / approve_draft → the saved row.
        f.on("POST", "/admin/conversations/[^/]+/reply") { _, _ -> 200 to Contract.replySent("sent") }
        f.on("POST", "/admin/conversations/[^/]+/approve-draft") { _, _ -> 200 to Contract.approved("sent") }
        // admin.py generate_draft / translate.translate_reply.
        f.on("POST", "/admin/conversations/[^/]+/generate-draft", body = """{"draft":"Hello Father 🙏 Yes — we deliver to Nyeri by Friday. Shall I send the M-Pesa details?"}""")
        f.on("POST", "/admin/conversations/[^/]+/translate-reply", body = """{"text":"Ndiyo, tutafikisha Ijumaa.","lang":"Swahili"}""")
        // admin.py get_conversation_activity.
        f.on("GET", "/admin/conversations/[^/]+/activity", body = Contract.activity())
        // admin.py clear_chat_history.
        f.on("DELETE", "/admin/conversations/[^/]+/messages", body = Contract.cleared)
    }
}
