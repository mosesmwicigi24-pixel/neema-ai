package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.crash.CrashReport
import ke.co.bethanyhouse.neema.core.crash.CrashReporter
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.TokenProvider
import ke.co.bethanyhouse.neema.feature.calls.CALL_LOG_PAGE
import ke.co.bethanyhouse.neema.feature.calls.LogItem
import ke.co.bethanyhouse.neema.feature.calls.insertByTime
import ke.co.bethanyhouse.neema.feature.calls.logItems
import ke.co.bethanyhouse.neema.feature.leads.buildStages
import ke.co.bethanyhouse.neema.feature.reports.uniqueKeys
import ke.co.bethanyhouse.neema.testing.FakeNeema
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The crash fixes of 2026-09-27 ("Neema closed because this app has a bug"):
 * every lazy list key stays unique whatever the server sends, and a crash
 * leaves a report that reaches the server.
 */
class CrashHardeningTest {
    private fun call(id: String, iso: String?) = Call(callId = id, waId = "2547000000${id.takeLast(2).padStart(2, '0')}", direction = "inbound", status = "completed", startedAt = iso)

    // ── The Calls log: a live update for an OLD call ─────────────────────────

    @Test fun anUpdateForACallOlderThanAFullLogIsLeftForTheNextRead() {
        val rows = (0 until CALL_LOG_PAGE).map { i -> call("c$i", "2026-09-27T${"%02d".format(23 - i % 24)}:00:00Z".let { if (i < 24) it else "2026-09-26T${"%02d".format(23 - (i - 24) % 24)}:00:00Z" }) }
        val old = call("old", "2026-09-12T10:00:00Z")
        assertNull("not at the head of the log", insertByTime(rows, old))
    }

    @Test fun anUpdateGoesInAtItsPlaceByTime() {
        val rows = listOf(call("a", "2026-09-27T12:00:00Z"), call("b", "2026-09-26T12:00:00Z"), call("c", "2026-09-25T12:00:00Z"))
        val mid = insertByTime(rows, call("m", "2026-09-26T18:00:00+03:00"))!!
        assertEquals(listOf("a", "m", "b", "c"), mid.map { it.callId })
        val newest = insertByTime(rows, call("n", "2026-09-28T01:00:00Z"))!!
        assertEquals("n", newest.first().callId)
        // A short log holds every call: an older one is simply last.
        assertEquals("o", insertByTime(rows, call("o", "2026-01-01T00:00:00Z"))!!.last().callId)
    }

    @Test fun dayHeadingsNeverRepeatAKeyEvenOutOfOrder() {
        // What used to crash: a row from an earlier day at the head of the log.
        val rows = listOf(
            call("x", "2026-09-12T10:00:00Z"), call("a", "2026-09-27T12:00:00Z"),
            call("b", "2026-09-12T09:00:00Z"), call("c", null), call("d", "not a date"),
        )
        val keys = logItems(rows).map { when (it) { is LogItem.Day -> it.key; is LogItem.Row -> it.key } }
        assertEquals(keys.size, keys.toSet().size)
        assertTrue(logItems(rows).count { it is LogItem.Day } >= 3)
    }

    // ── Other lazy keys the audit found ──────────────────────────────────────

    @Test fun uniqueKeysSurviveIdsThatLookLikeTheirOwnSuffix() {
        val keys = uniqueKeys(listOf("a#2", "a", "a", "a", "a#2"))
        assertEquals(keys.size, keys.toSet().size)
    }

    @Test fun leadStagesNeverRepeat() {
        val ids = buildStages(listOf("Quoted", "Quoted", " ", "won", "Site visit")).map { it.id }
        assertEquals(ids.size, ids.toSet().size)
    }

    // ── Crash reports reach the server ───────────────────────────────────────

    private class Tok : TokenProvider {
        override suspend fun validAccessToken() = "tok"
        override suspend fun forceRefresh(): String? = null
        override fun onRejected(token: String?) {}
    }

    private fun report(id: String) = CrashReport(id = id, at = "2026-09-27T18:35:00Z", kind = "crash", summary = "boom", trace = "boom\n\tat x")

    @Test fun savedReportsAreSentOnceSignedInAndRemovedWhenDelivered() = runBlocking {
        val fake = FakeNeema()
        fake.on("POST", "/admin/client-crashes", body = """{"ok":true}""")
        val http = NeemaHttp("https://neema.test", Tok(), fake, Dispatchers.Unconfined)
        val waiting = mutableListOf(File("r1") to report("r1"), File("r2") to report("r2"))
        val signedIn = MutableStateFlow(false)
        val reporter = CrashReporter(CoroutineScope(Dispatchers.Unconfined), http, signedIn,
            pending = { waiting.toList() }, delivered = { f -> waiting.removeAll { it.first == f } })
        assertEquals("signed out: nothing is sent", 0, reporter.flush())
        signedIn.value = true
        assertEquals(2, reporter.flush())
        assertTrue(waiting.isEmpty())
        val sent = fake.calls.filter { it.path.endsWith("/admin/client-crashes") }
        assertEquals(2, sent.size)
        assertTrue(sent[0].body!!.contains("\"id\":\"r1\"") && sent[0].body!!.contains("\"kind\":\"crash\""))
    }

    @Test fun aReportThatCannotBeSentStaysForTheNextTry() = runBlocking {
        val fake = FakeNeema()
        fake.on("POST", "/admin/client-crashes", code = 503, body = "down")
        val http = NeemaHttp("https://neema.test", Tok(), fake, Dispatchers.Unconfined)
        val waiting = mutableListOf(File("r1") to report("r1"))
        val reporter = CrashReporter(CoroutineScope(Dispatchers.Unconfined), http, MutableStateFlow(true),
            pending = { waiting.toList() }, delivered = { f -> waiting.removeAll { it.first == f } })
        assertEquals(0, reporter.flush())
        assertEquals(1, waiting.size)
    }
}
