package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Round 8 — the shop at peak: a 5,000-conversation inbox served in cursor
 * pages exactly as admin.py list_conversations pages it (newest first,
 * `limit`, an opaque `next_cursor`), and a 2,000-message thread served in
 * `before` pages as admin.py get_thread does (oldest first within a page),
 * with photos, albums, voice notes, translations and system events mixed in.
 */
object InboxStressFixtures {
    private val PY_ISO: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSSxxx")
    private fun iso(t: Instant): String = PY_ISO.format(t.atOffset(ZoneOffset.UTC))

    private val CHANNELS = listOf("whatsapp", "whatsapp", "whatsapp", "messenger", "instagram", "facebook")

    /**
     * One inbox row. Every 10th is held by a human (every 20th by me), every
     * 7th is unread, and the first [pairs] × 2 rows are the same people on two
     * channels (so the list groups them into one row each).
     */
    fun row(i: Int, minutesAgo: Long, pairs: Int = 100, mode: String? = null): String {
        val ch = if (i < pairs * 2) (if (i % 2 == 0) "whatsapp" else "messenger") else CHANNELS[i % CHANNELS.size]
        val phone = (254700000000L + i).toString()
        val wa = ch == "whatsapp"
        val m = mode ?: if (i % 10 == 0) "human" else "ai"
        val mine = m == "human" && (mode != null || i % 20 == 0)
        return InboxFixtures.Contract.row(
            id = "s$i", name = "Customer $i", waId = if (wa) phone else null, externalId = if (wa) phone else "psid$i",
            channel = ch, mode = m, preview = "Message number $i about the purple cassock", minutes = minutesAgo,
            unread = if (i % 7 == 0) 2 else 0, person = if (i < pairs * 2) "pp${i / 2}" else null,
            agentId = if (m == "human") (if (mine) Fixtures.ME_ID else "agent-other") else null,
            agentName = if (m == "human") (if (mine) "Moses Mwicigi" else "Grace Wanjiru") else null,
            stage = if (i % 13 == 0) "qualified" else null, orders = i % 5,
        )
    }

    /**
     * A paged inbox of [total] rows on [f]: GET /admin/conversations answers
     * [pageSize] rows per call, newest first, with a cursor to the next page.
     * [top] lets a test move rows to the top of page one (a new message).
     */
    class Inbox(f: FakeNeema, val total: Int = 5_000, val pageSize: Int = 50, pairs: Int = 100, mode: String? = null) {
        /** Server order: s0 (newest) … s{total-1} (oldest). */
        val ids: MutableList<String> = (0 until total).map { "s$it" }.toMutableList()
        private val rows = HashMap<String, String>().apply { for (i in 0 until total) put("s$i", row(i, (i + 1).toLong(), pairs, mode)) }
        val cursors = CopyOnWriteArrayList<String?>()
        val queries = CopyOnWriteArrayList<String?>()

        init {
            f.on("GET", "/admin/conversations") { r, _ ->
                val cursor = r.url.queryParameter("cursor")
                cursors += cursor
                queries += r.url.queryParameter("q")
                val limit = r.url.queryParameter("limit")?.toIntOrNull() ?: pageSize
                val from = cursor?.removePrefix("o")?.toIntOrNull() ?: 0
                val to = minOf(ids.size, from + limit)
                val next = if (to < ids.size) "\"o$to\"" else "null"
                200 to """{"items":[${ids.subList(from, to).joinToString(",") { rows.getValue(it) }}],"next_cursor":$next}"""
            }
            f.on("GET", "/admin/conversations/s\\d+") { r, _ -> 200 to rows.getValue(r.url.pathSegments.last()) }
        }

        /** [id] just got a message: it moves to the top of page one. */
        fun bump(id: String, i: Int) {
            ids.remove(id); ids.add(0, id)
            rows[id] = row(i, 0)
        }
    }

    /** One thread message; every 20th starts a run of photos (an album), every 50th is a voice note. */
    private fun message(i: Int, at: Instant): String {
        val inbound = i % 3 != 2
        val dir = if (inbound) "inbound" else "outbound"
        val sender = if (inbound) "user" else if (i % 2 == 0) "ai" else "human_agent"
        val t = iso(at)
        return when {
            i % 20 in 0..2 && inbound -> """{"id":"m$i","type":"message","direction":"inbound","sender":"user","text":"[image]","media_type":"image","media_url":"https://cdn.test/p$i.jpg","media_caption":"A purple clergy stole","created_at":"$t"}"""
            i % 50 == 7 -> """{"id":"m$i","type":"message","direction":"$dir","sender":"$sender","text":"voice note $i","media_type":"audio","media_url":"https://cdn.test/v$i.ogg","created_at":"$t"}"""
            else -> """{"id":"m$i","type":"message","direction":"$dir","sender":"$sender","text":"Message $i — *bold* _italic_ see www.bethanyhouse.co.ke/p/$i","translation":${if (i % 11 == 0) "\"Hello $i\"" else "null"},"translated_from":${if (i % 11 == 0) "\"sw\"" else "null"},"created_at":"$t"}"""
        }
    }

    /** The intercept timeline item admin.py get_thread mixes in (10 s after message [i]). */
    private fun event(i: Int, at: Instant): String =
        """{"id":"evt-$i","type":"system_event","direction":"outbound","sender":"ai","text":"Escalated","event_kind":"${if (i % 2 == 0) "escalated" else "flag"}","created_at":"${iso(at.plusSeconds(10))}"}"""

    /**
     * A [total]-message thread for [convId], with a system event after every
     * 97th message: page one is the newest [page] MESSAGES plus the events
     * among them (get_thread's `limit` counts messages, not events);
     * `before=<created_at>` answers the [page] messages older than it.
     */
    class Thread(f: FakeNeema, convId: String, val total: Int = 2_000, val page: Int = 50) {
        private val base: Instant = AppClock.instant().minusSeconds(60)
        private fun at(i: Int): Instant = base.minusSeconds((total - i).toLong() * 30)
        val stamps: List<String> = (0 until total).map { iso(at(it)) }
        private val itemsOf: List<List<String>> =
            (0 until total).map { i -> listOfNotNull(message(i, at(i)), if (i % 97 == 0) event(i, at(i)) else null) }
        /** Every item (messages and events), oldest first. */
        val json: List<String> = itemsOf.flatten()
        val events: Int = (0 until total).count { it % 97 == 0 }
        val befores = CopyOnWriteArrayList<String?>()

        init {
            f.on("GET", "/admin/conversations/$convId/messages") { r, _ ->
                val before = r.url.queryParameter("before")
                befores += before
                val end = if (before == null) total else stamps.indexOf(before).let { if (it < 0) 0 else it }
                val start = maxOf(0, end - page)
                200 to itemsOf.subList(start, end).flatten().joinToString(",", "[", "]")
            }
        }
    }

    /** Frame JSON for the live socket. */
    fun newMessage(convId: String, id: String?, text: String, sender: String = "user") =
        """{"type":"new_message","conversationId":"$convId",${id?.let { "\"id\":\"$it\"," } ?: ""}"sender":"$sender","text":"$text"}"""

    fun interceptChanged(convId: String, mode: String) =
        """{"type":"intercept_changed","conversationId":"$convId","mode":"$mode","assignedAgentId":${if (mode == "human") "\"agent-other\"" else "null"},"assignedAgentName":${if (mode == "human") "\"Grace Wanjiru\"" else "null"}}"""

    fun typing(convId: String) = """{"type":"typing","conversationId":"$convId","sender":"user"}"""

    /** A long WhatsApp message: [paragraphs] paragraphs full of formatting and links. */
    fun longMessage(paragraphs: Int = 200): String = (0 until paragraphs).joinToString("\n\n") { i ->
        "*Item $i* — _handmade_ ~was KES 4,000~ now `KES 3,500`. Details: https://bethanyhouse.co.ke/p/$i, or www.bethanyhouse.co.ke. " +
            "```size chart $i``` **legacy bold** and plain words to fill the line out a little more."
    }
}
