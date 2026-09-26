package ke.co.bethanyhouse.neema.core

import androidx.core.app.NotificationCompat
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.notify.AlertSink
import ke.co.bethanyhouse.neema.core.notify.AppNotification
import ke.co.bethanyhouse.neema.core.notify.NotificationCenter
import ke.co.bethanyhouse.neema.core.notify.Notifier
import ke.co.bethanyhouse.neema.core.notify.SystemAlert
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.MemoryPrefs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * The phone notifications raised for the 13 notification frames the backend
 * sends: channel, priority, text, tap target, the agent's switches, the
 * denied-permission path, and how a burst stacks in the tray.
 */
class NotificationAlertsTest {
    // Only for a Context; nothing is rendered.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    /** Records what would reach Android's notification manager. */
    private class Tray(var allowed: Boolean = true) : AlertSink {
        val posted = mutableListOf<SystemAlert>()
        val cancelled = mutableListOf<Int>()
        var summary: Pair<Int, List<String>>? = null
        var summaryCancels = 0
        /** Ids the agent swiped away. */
        val swiped = mutableSetOf<Int>()
        override fun canPost() = allowed
        override fun post(alert: SystemAlert) { posted += alert }
        override fun cancel(id: Int) { cancelled += id }
        override fun active(): Set<Int> = posted.map { it.id }.toSet() - cancelled.toSet() - swiped
        override fun summary(count: Int, lines: List<String>) { summary = count to lines }
        override fun cancelSummary() { summary = null; summaryCancels++ }
    }

    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val factory = FakeSocketFactory()
    private val appPrefs = MemoryPrefs()
    private val foreground = MutableStateFlow(false)
    private val tray = Tray()

    private fun center(): NotificationCenter {
        val socket = LiveSocket(factory, "https://neema.test", scope)
        val nc = NotificationCenter(paparazzi.context, scope, socket, AppPrefs(paparazzi.context, appPrefs), MemoryPrefs(), tray)
        nc.start(foreground)
        socket.connect("a1"); factory.last.open()
        return nc
    }

    private fun push(type: String, title: String = "t-$type", body: String = "b", extra: String = "") =
        factory.last.frame("""{"event":"notification","type":"$type","title":"$title","body":"$body"$extra}""")

    // ── Every type the backend sends, exactly as each sender shapes it ──────

    @Test
    fun all13BackendTypesGetTheRightChannelPriorityAndTapTarget() {
        center()
        // (type, the sender's pointer fields) → (channel, priority, conversation, view)
        data class Case(val type: String, val extra: String, val channel: String, val priority: Int, val conv: String?, val view: String?)
        val high = NotificationCompat.PRIORITY_HIGH
        val cases = listOf(
            Case("new_conversation", ""","wa_id":"254700000001"""", Notifier.CH_ALERTS, high, "254700000001", null),
            Case("new_message", ""","conversationId":"c-sms"""", Notifier.CH_MESSAGES, NotificationCompat.PRIORITY_DEFAULT, "c-sms", null),
            Case("human_transfer", ""","waId":"254700000002","conversationId":"c-media","mediaType":"image"""", Notifier.CH_ALERTS, high, "c-media", null),
            Case("media_escalation", ""","wa_id":"254700000003","conv_id":"c-doc"""", Notifier.CH_ALERTS, high, "c-doc", null),
            Case("intercept", ""","conversationId":"c-int"""", Notifier.CH_ALERTS, high, "c-int", null),
            Case("system", ""","conversationId":"c-rel"""", Notifier.CH_UPDATES, NotificationCompat.PRIORITY_LOW, "c-rel", null),
            Case("draft_ready", ""","conv_id":"c-draft","wa_id":"254700000004"""", Notifier.CH_ALERTS, high, "c-draft", null),
            Case("availability_check", ""","conv_id":"c-avail"""", Notifier.CH_ALERTS, high, "c-avail", null),
            Case("take_back", ""","conv_id":"c-take","wa_id":"254700000005"""", Notifier.CH_ALERTS, high, "c-take", null),
            Case("planned_action", ""","conv_id":"c-plan","wa_id":"254700000006"""", Notifier.CH_ALERTS, high, "c-plan", null),
            Case("standup", "", Notifier.CH_UPDATES, NotificationCompat.PRIORITY_LOW, null, null),
            Case("hub_event", "", Notifier.CH_ALERTS, high, null, "orders"),
            Case("selfcheck", "", Notifier.CH_UPDATES, NotificationCompat.PRIORITY_LOW, null, null),
        )
        assertEquals(13, cases.size)
        for (c in cases) push(c.type, title = "Title ${c.type}", body = "Body ${c.type}", extra = c.extra)
        assertEquals(13, tray.posted.size)
        for ((c, a) in cases.zip(tray.posted)) {
            assertEquals(c.type, c.channel, a.channel)
            assertEquals(c.type, c.priority, a.priority)
            assertEquals(c.type, c.conv, a.convKey)
            assertEquals(c.type, c.view, a.view)
            assertEquals("Title ${c.type}", a.title)
            assertEquals("Body ${c.type}", a.body)
            assertTrue("tapping marks the bell entry read", a.notificationId != null)
        }
    }

    @Test
    fun aHubEventWithAThreadOpensTheThread() {
        center()
        push("hub_event", extra = ""","conv_id":"c9","wa_id":"254711"""")
        assertEquals("c9", tray.posted.single().convKey)
        assertNull(tray.posted.single().view)
    }

    @Test
    fun theWebsLegacyTypesStillMap() {
        center()
        appPrefs.edit().putBoolean("notif_order_updates", true).apply()
        push("order_update"); push("transfer", extra = ""","conv_id":"c1""""); push("daily_summary")
        assertEquals(listOf(Notifier.CH_ALERTS, Notifier.CH_ALERTS, Notifier.CH_UPDATES), tray.posted.map { it.channel })
        assertEquals("orders", tray.posted[0].view)
    }

    // ── When a phone notification is raised at all ──────────────────────────

    @Test
    fun noSystemNotificationWhileTheAppIsInFront() {
        val nc = center()
        foreground.value = true
        push("intercept", extra = ""","conversationId":"c1"""")
        assertTrue(tray.posted.isEmpty())
        assertEquals("the bell still has it", 1, nc.items.value.size)
        foreground.value = false
        push("intercept", title = "later", extra = ""","conversationId":"c1"""")
        assertEquals(1, tray.posted.size)
    }

    @Test
    fun theProfileSwitchesSilenceThePhoneButNotTheBell() {
        val nc = center()
        appPrefs.edit()
            .putBoolean("notif_new_conv", false).putBoolean("notif_human_transfer", false)
            .putBoolean("notif_daily_summary", false).apply()
        push("new_conversation"); push("new_message"); push("human_transfer"); push("transfer")
        push("media_escalation"); push("standup"); push("daily_summary"); push("order_update")
        assertTrue("all switched off (order updates are off by default)", tray.posted.isEmpty())
        assertEquals(8, nc.items.value.size)
        push("intercept")
        assertEquals("escalations have no switch", 1, tray.posted.size)
    }

    @Test
    fun orderUpdatesAreOptIn() {
        center()
        push("order_update")
        assertTrue(tray.posted.isEmpty())
        appPrefs.edit().putBoolean("notif_order_updates", true).apply()
        push("order_update", title = "Order paid")
        assertEquals("Order paid", tray.posted.single().title)
    }

    @Test
    fun deniedNotificationPermissionDegradesToTheBellAndToast() {
        val nc = center()
        val seen = mutableListOf<AppNotification>()
        scope.launch { nc.incoming.collect { seen += it } }
        tray.allowed = false
        push("intercept", extra = ""","conversationId":"c1"""")
        assertTrue(tray.posted.isEmpty())
        assertNull(tray.summary)
        assertEquals(1, nc.items.value.size)
        assertEquals("the in-app toast still fires", 1, seen.size)
    }

    // ── Duplicates and bursts ───────────────────────────────────────────────

    @Test
    fun anExactRepeatWithinSecondsIsDropped() {
        val nc = center()
        repeat(3) { push("intercept", title = "🤖 AI Escalation", body = "wants a human", extra = ""","conversationId":"c1"""") }
        assertEquals(1, nc.items.value.size)
        assertEquals(1, tray.posted.size)
        push("intercept", title = "🤖 AI Escalation", body = "wants a human", extra = ""","conversationId":"c2"""")
        assertEquals("another thread is not a repeat", 2, nc.items.value.size)
    }

    @Test
    fun aThreadsNewerAlertReplacesItsOlderOne() {
        center()
        push("intercept", title = "🤖 AI Escalation", extra = ""","conversationId":"c1"""")
        push("intercept", title = "🙋 Grace picked up", extra = ""","conversationId":"c1"""")
        assertEquals(tray.posted[0].id, tray.posted[1].id)
        assertNull("one thread, one row: no summary", tray.summary)
    }

    @Test
    fun aBurstStacksUnderOneSummary() {
        center()
        push("new_conversation", title = "New chat from Mary", body = "Hi", extra = ""","wa_id":"2547001"""")
        assertNull(tray.summary)
        push("new_conversation", title = "New chat from John", body = "Price?", extra = ""","wa_id":"2547002"""")
        push("standup", title = "☀️ Neema's morning standup", body = "")
        val (count, lines) = tray.summary!!
        assertEquals(3, count)
        assertEquals(listOf("☀️ Neema's morning standup", "New chat from John — Price?", "New chat from Mary — Hi"), lines)
        assertEquals("distinct rows", 3, tray.posted.map { it.id }.toSet().size)
        assertTrue(tray.posted.all { it.id >= 10_000 && it.id != Notifier.SUMMARY_ID })
    }

    @Test
    fun swipedAwayRowsLeaveTheSummaryCount() {
        center()
        push("new_conversation", extra = ""","wa_id":"1"""")
        push("new_conversation", extra = ""","wa_id":"2"""")
        tray.swiped += tray.posted.map { it.id }
        push("new_conversation", extra = ""","wa_id":"3"""")
        push("new_conversation", extra = ""","wa_id":"4"""")
        assertEquals(2, tray.summary!!.first)
    }

    // ── The bell and the tray stay in step ──────────────────────────────────

    @Test
    fun readingInTheBellTakesItOutOfTheTray() {
        val nc = center()
        push("new_conversation", extra = ""","wa_id":"1"""")
        push("new_conversation", extra = ""","wa_id":"2"""")
        val (second, first) = nc.items.value
        nc.markRead(first.id)
        assertEquals(listOf(tray.posted[0].id), tray.cancelled)
        nc.dismiss(second.id)
        assertEquals(2, tray.cancelled.size)
        assertNull("nothing left: the summary goes too", tray.summary)
    }

    @Test
    fun markAllReadAndClearEmptyTheTray() {
        val nc = center()
        repeat(3) { push("new_conversation", extra = ""","wa_id":"$it"""") }
        nc.markAllRead()
        assertEquals(3, tray.cancelled.size)
        assertNull(tray.summary)
        push("intercept", extra = ""","conversationId":"x"""")
        nc.clear()
        assertEquals(4, tray.cancelled.size)
        assertTrue(tray.summaryCancels > 0)
    }

    @Test
    fun theTargetIsTheSameInTheBellAndTheTray() {
        val n = { type: String, conv: String? -> AppNotification("i", type, "t", "b", conv, 1L) }
        assertEquals("orders", NotificationCenter.viewFor(n("order_update", null)))
        assertEquals("orders", NotificationCenter.viewFor(n("hub_event", null)))
        assertNull(NotificationCenter.viewFor(n("hub_event", "c1")))
        assertNull(NotificationCenter.viewFor(n("standup", null)))
        assertNotEquals(
            NotificationCenter.systemId(n("intercept", "c1")),
            NotificationCenter.systemId(n("intercept", "c2")),
        )
        assertEquals(
            NotificationCenter.systemId(n("intercept", "c1")),
            NotificationCenter.systemId(AppNotification("other", "system", "x", "y", "c1", 2L)),
        )
        assertFalse(NotificationCenter.systemId(n("standup", null)) in setOf(1001, 1002, 2001))
    }
}
