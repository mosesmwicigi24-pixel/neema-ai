package ke.co.bethanyhouse.neema.conversations

import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import ke.co.bethanyhouse.neema.core.api.InboxQuery
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaMono
import ke.co.bethanyhouse.neema.feature.conversations.*
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

/** Pure logic ported from the web: WaText, thread merge/dedupe, thread rows, keys. */
class InboxLogicTest {

    // ── WaText (lib/waText.tsx) ──

    private fun AnnotatedString.styled(): List<Pair<String, String>> = spanStyles.map { r ->
        val s = r.item
        val kind = when {
            s.fontWeight == FontWeight.Bold -> "b"
            s.fontStyle == FontStyle.Italic -> "i"
            s.textDecoration == TextDecoration.LineThrough -> "s"
            s.fontFamily == NeemaMono -> "code"
            else -> "?"
        }
        kind to text.substring(r.start, r.end)
    }

    @Test fun waText_basicMarks() {
        val a = formatWa("*bold* _it_ ~gone~ `mono`")
        assertEquals("bold it gone mono", a.text)
        assertEquals(listOf("b" to "bold", "i" to "it", "s" to "gone", "code" to "mono"), a.styled())
    }

    @Test fun waText_legacyDoubleStarWinsOverSingle() {
        val a = formatWa("**x** and *y*")
        assertEquals("x and y", a.text)
        assertEquals(listOf("b" to "x", "b" to "y"), a.styled())
    }

    @Test fun waText_tripleStarKeepsOuterStars() {
        // Same as the web's split: "***b***" → "*" + <b>b</b> + "*".
        val a = formatWa("***b***")
        assertEquals("*b*", a.text)
        assertEquals(listOf("b" to "b"), a.styled())
    }

    @Test fun waText_marksNeverCrossNewlines() {
        val a = formatWa("*a\nb* and _c\nd_")
        assertEquals("*a\nb* and _c\nd_", a.text)
        assertTrue(a.styled().isEmpty())
    }

    @Test fun waText_unmatchedAndEmptyDelimitersStayLiteral() {
        assertEquals("2 * 3 = 6", formatWa("2 * 3 = 6").text)
        assertEquals("** __ ~~", formatWa("** __ ~~").text)
        // No word boundaries on the web either: snake_case_name italicises "case".
        formatWa("snake_case_name").let { assertEquals("snakecasename", it.text); assertEquals(listOf("i" to "case"), it.styled()) }
        assertEquals("", formatWa(null).text)
        assertEquals("", formatWa("").text)
    }

    @Test fun waText_midWordMarksLikeTheWeb() {
        // The web's regex has no word boundaries: a*b*c bolds "b".
        val a = formatWa("a*b*c")
        assertEquals("abc", a.text)
        assertEquals(listOf("b" to "b"), a.styled())
    }

    @Test fun waText_tripleBacktickIsMonospace() {
        val a = formatWa("```x = 1```")
        assertEquals("x = 1", a.text)
        assertEquals(listOf("code" to "x = 1"), a.styled())
    }

    @Test fun waText_linksAreTappableAndDropTrailingPunctuation() {
        val a = formatWa("See https://bethanyhouse.co.ke/shop, or www.neema.ke.")
        val links = a.getLinkAnnotations(0, a.length).map { (it.item as LinkAnnotation.Url).url to a.text.substring(it.start, it.end) }
        assertEquals(
            listOf("https://bethanyhouse.co.ke/shop" to "https://bethanyhouse.co.ke/shop", "https://www.neema.ke" to "www.neema.ke"),
            links,
        )
    }

    @Test fun waText_linkInsideBoldStillWorks() {
        val a = formatWa("*https://x.co*")
        assertEquals("https://x.co", a.text)
        assertEquals(1, a.getLinkAnnotations(0, a.length).size)
    }

    // ── Thread merge (mergeThread / mergeServer) ──

    private fun m(id: String, sec: Long, text: String = id, dir: String = "inbound", sender: String = "user", media: String? = null, type: String = "message", kind: String? = null) =
        ThreadMsg(id = id, type = type, direction = dir, sender = sender, text = text, createdAt = Instant.ofEpochSecond(1_800_000_000 + sec).toString(), mediaUrl = media, eventKind = kind)

    @Test fun mergeThread_unionsByIdNewestStateWinsSortedByTime() {
        val existing = listOf(m("a", 1), m("b", 2, "old"))
        val incoming = listOf(m("b", 2, "new"), m("c", 0))
        val out = mergeThread(existing, incoming)
        assertEquals(listOf("c", "a", "b"), out.map { it.id })
        assertEquals("new", out.last().text)
    }

    @Test fun mergeThread_olderPageSlotsInWithoutDuplicates() {
        val page1 = (10..14).map { m("n$it", it.toLong()) }
        val older = (5..10).map { m("n$it", it.toLong()) }
        val out = mergeThread(page1, older)
        assertEquals((5..14).map { "n$it" }, out.map { it.id })
    }

    @Test fun mergeServer_optimisticReplacedByServerRow() {
        val opt = m("optimistic-1", 100, "Hello", dir = "outbound", sender = "human_agent")
        val server = listOf(m("a", 1), m("srv-9", 101, "Hello", dir = "outbound", sender = "human_agent"))
        val out = mergeServer(listOf(m("a", 1), opt), server)
        assertEquals(listOf("a", "srv-9"), out.map { it.id })
    }

    @Test fun mergeServer_keepsOptimisticUntilServerHasIt() {
        val opt = m("optimistic-1", 100, "Hello", dir = "outbound", sender = "human_agent")
        val out = mergeServer(listOf(opt), listOf(m("a", 1)))
        assertEquals(listOf("a", "optimistic-1"), out.map { it.id })
    }

    @Test fun mergeServer_livePillDroppedWhenTheDbEventArrives() {
        val live = m("live-evt-1", 50, type = "system_event", kind = "intercept")
        val out = mergeServer(listOf(live), listOf(m("evt-x", 50, type = "system_event", kind = "intercept")))
        assertEquals(listOf("evt-x"), out.map { it.id })
    }

    // ── Live pills (buildSystemEventFromWs) ──

    @Test fun systemEventFromWs_labels() {
        fun ev(kind: String, agent: String? = null, note: String? = null) = systemEventFromWs(buildJsonObject {
            put("type", "intercept_changed"); put("eventKind", kind)
            if (agent != null) put("eventAgentName", agent)
            if (note != null) put("eventNote", note)
        })!!.text
        assertEquals("Escalated — needs human", ev("escalated"))
        assertEquals("Flagged: Needs Attention", ev("flag"))
        assertEquals("Picked up by Grace", ev("intercept", "Grace"))
        assertEquals("Picked up by agent", ev("intercept"))
        assertEquals("Released to AI by Grace", ev("release", "Grace"))
        assertEquals("Released to AI", ev("release"))
        assertEquals("Transferred — to sales", ev("transfer", note = "to sales"))
        assertEquals("Transferred", ev("transfer"))
        assertEquals("Paused by Grace — replies held", ev("pause", "Grace"))
        assertEquals("Paused — replies held", ev("pause"))
        assertEquals("AI draft approved", ev("approve_draft"))
        assertNull(systemEventFromWs(buildJsonObject { put("type", "intercept_changed") }))
        val e = systemEventFromWs(buildJsonObject { put("eventKind", "escalated"); put("eventReason", JsonPrimitive("media")) })!!
        assertTrue(e.id.startsWith("live-evt-")); assertEquals("system_event", e.type); assertEquals("media", e.eventReason)
    }

    /** waText.tsx: `<code className="font-mono text-[0.95em]">` — DM Mono (the web's --font-mono), a touch smaller. */
    @Test fun waText_codeIsDmMonoAtWebSize() {
        val a = formatWa("size `XL-42`")
        val code = a.spanStyles.single().item
        assertEquals(NeemaMono, code.fontFamily)
        assertEquals(androidx.compose.ui.unit.TextUnit(0.95f, androidx.compose.ui.unit.TextUnitType.Em), code.fontSize)
    }

    /**
     * Live pills key the thread's lazy list: two frames of different kinds in one
     * millisecond (always, under a test's fixed clock) used to share an id, and a
     * repeated key throws inside LazyColumn.
     */
    @Test fun liveEvents_haveUniqueIdsEvenInOneMillisecond() {
        val ids = listOf("escalated", "intercept", "escalated").map { k ->
            systemEventFromWs(buildJsonObject { put("type", "intercept_changed"); put("eventKind", k) })!!.id
        }
        assertEquals(3, ids.toSet().size)
        assertTrue(ids.all { it.startsWith("live-evt-") })
    }

    @Test fun threadRows_neverRepeatAKey() {
        // The same server row delivered twice (a replayed frame appended past the dedupe).
        val list = sortThread(listOf(m("u1", 1, "hi"), m("u1", 1, "hi"), m("u2", 2, "there")))
        val rows = buildThreadRows(list, unreadSnap = 1)
        assertEquals(rows.map { it.key }.distinct(), rows.map { it.key })
        assertEquals(listOf("u1", "new-divider", "u2"), rows.map { it.key })
    }

    // ── Thread rows (the thread JSX) ──

    @Test fun threadRows_handoffsHiddenFirstEscalationOnlyDividerAndAlbum() {
        val list = sortThread(listOf(
            m("u1", 1, "hi"),
            m("esc1", 2, type = "system_event", kind = "escalated"),
            m("esc2", 3, type = "system_event", kind = "escalated"),
            m("rel", 4, type = "system_event", kind = "release"),
            m("pick", 5, type = "system_event", kind = "intercept").copy(agentName = "Moses"),
            m("p1", 6, dir = "inbound").copy(mediaType = "image", mediaUrl = "u/1"),
            m("p2", 7, dir = "inbound").copy(mediaType = "image", mediaUrl = "u/2"),
            m("u2", 8, "last"),
        ))
        val rows = buildThreadRows(list, unreadSnap = 1)
        assertEquals(listOf("u1", "esc1", "p1", "new-divider", "u2"), rows.map { it.key })
        assertEquals(2, (rows[2] as TBubble).album!!.size)
    }

    @Test fun threadRows_mediaEscalationReason() {
        val list = sortThread(listOf(
            m("img", 1).copy(mediaType = "image", mediaUrl = "u"),
            m("sys", 1, type = "system_event", kind = "intercept"),
        ))
        // The system intercept sorts just after the inbound it followed.
        assertEquals(listOf("img", "sys"), list.map { it.id })
        val esc = buildThreadRows(list, 0).filterIsInstance<TEscalated>().single()
        assertEquals("Media received — AI cannot process", esc.reason)
    }

    @Test fun threadRows_postCardOncePerRunOurRepliesDontBreakIt() {
        fun c(id: String, sec: Long, post: String?, reply: String? = null) = m(id, sec, "[comment] q").copy(
            commentRaw = buildJsonObject { if (post != null) put("post_id", post); put("title", "T"); if (reply != null) put("reply_to", reply) },
        )
        val list = sortThread(listOf(c("k1", 1, "p1"), c("r1", 2, "p1", reply = "k1"), c("k2", 3, "p1"), c("k3", 4, "p2")))
        val heads = buildThreadRows(list, 0).filterIsInstance<TPostHead>().map { it.key }
        assertEquals(listOf("post-k1", "post-k3"), heads)
    }

    // ── Keys and display ──

    @Test fun filterKey_distinguishesEveryFilterAndTrimsSearch() {
        val base = filterKeyOf(InboxQuery())
        assertEquals(base, DEFAULT_KEY)
        assertEquals(base, filterKeyOf(InboxQuery(q = "   ")))
        val keys = listOf(InboxQuery(tab = "unread"), InboxQuery(channel = "whatsapp"), InboxQuery(mode = "ai"), InboxQuery(tag = "vip"), InboxQuery(q = "peter"))
            .map(::filterKeyOf)
        assertEquals(keys.size, (keys + base).toSet().size - 1)
    }

    @Test fun webVisitor_isNeverShownAsAPhone() {
        val web = Conversation(id = "c", waId = "web_3fa9c1e20b7d4c5a9e11", channel = "whatsapp")
        assertEquals("Website visitor", inboxName(web))
        assertEquals("Web chat", inboxHandle(web))
        assertNull(phoneDigits(web))
        assertEquals("Amina", inboxName(web.copy(name = "Amina")))
        val wa = Conversation(id = "d", waId = "254712345678")
        assertEquals("+254 712 345 678", inboxName(wa))
        assertEquals("254712345678", phoneDigits(wa))
        assertNull(phoneDigits(Conversation(id = "e", waId = "25898765432101234", channel = "facebook")))
    }

    @Test fun normalized_fallsBackLikeMapConversation() {
        val c = Conversation(id = "x", waId = "2547", createdAt = "2026-01-01T00:00:00Z").normalized()
        assertEquals("2547", c.externalId)
        assertEquals("2026-01-01T00:00:00Z", c.lastMessageAt)
    }
}
