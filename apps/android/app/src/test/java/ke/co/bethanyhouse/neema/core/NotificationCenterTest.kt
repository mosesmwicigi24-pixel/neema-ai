package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.util.AppClock

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.notify.AppNotification
import ke.co.bethanyhouse.neema.core.notify.NotificationCenter
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** The bell (components/ui/Notifications.tsx + useAgentNotifications). */
class NotificationCenterTest {
    // Only for a Context; nothing is rendered.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val factory = FakeSocketFactory()
    private val prefs = MemoryPrefs()

    private fun center(): Pair<NotificationCenter, LiveSocket> {
        val socket = LiveSocket(factory, "https://neema.test", scope)
        val nc = NotificationCenter(paparazzi.context, scope, socket, AppPrefs(paparazzi.context, MemoryPrefs()), prefs)
        nc.start(MutableStateFlow(true))
        socket.connect("a1"); factory.last.open()
        return nc to socket
    }

    private fun push(json: String) = factory.last.frame(json)

    @Test
    fun framesBecomeUnreadEntriesNewestFirst() {
        val (nc) = center()
        val seen = mutableListOf<AppNotification>()
        scope.launch { nc.incoming.collect { seen += it } }
        push("""{"event":"notification","type":"new_conversation","title":"New chat from Mary","body":"Hi","wa_id":"254722000111"}""")
        push("""{"event":"notification","type":"intercept","title":"🙋 Grace picked up","body":"b","conversationId":"c1"}""")

        val items = nc.items.value
        assertEquals(listOf("🙋 Grace picked up", "New chat from Mary"), items.map { it.title })
        assertEquals(2, nc.unread)
        assertEquals(2, seen.size)
        assertTrue(items.all { !it.read && it.at > 0 && it.id.isNotBlank() })
        assertEquals(2, items.map { it.id }.toSet().size)
    }

    @Test
    fun theTargetConversationIsReadFromEveryFieldTheBackendUses() {
        val (nc) = center()
        push("""{"event":"notification","type":"intercept","title":"a","body":"","conversationId":"conv-1","wa_id":"w"}""")
        push("""{"event":"notification","type":"draft_ready","title":"b","body":"","conv_id":"conv-2","wa_id":"w"}""")
        push("""{"event":"notification","type":"new_conversation","title":"c","body":"","wa_id":"254700000000"}""")
        push("""{"event":"notification","type":"standup","title":"d","body":""}""")
        assertEquals(listOf(null, "254700000000", "conv-2", "conv-1"), nc.items.value.map { it.convKey })
    }

    @Test
    fun missingFieldsGetSafeDefaults() {
        val (nc) = center()
        push("""{"event":"notification"}""")
        val n = nc.items.value.single()
        assertEquals("system", n.type)
        assertEquals("Neema", n.title)
        assertEquals("", n.body)
        assertNull(n.convKey)
    }

    @Test
    fun aFrameTimestampIsKeptOtherwiseArrivalTime() {
        val (nc) = center()
        val before = AppClock.now()
        push("""{"event":"notification","type":"system","title":"late","body":"","ts":"2026-01-02T03:04:05Z"}""")
        push("""{"event":"notification","type":"system","title":"now","body":"","ts":"garbage"}""")
        val (now, late) = nc.items.value
        assertEquals(java.time.Instant.parse("2026-01-02T03:04:05Z").toEpochMilli(), late.at)
        assertTrue(now.at >= before)
    }

    @Test
    fun onlyNotificationFramesCount() {
        val (nc) = center()
        push("""{"type":"new_message","conversationId":"c1"}""")
        push("""{"type":"intercept_changed","conversationId":"c1","mode":"human"}""")
        push("""{"type":"incoming_call","call_id":"x"}""")
        assertTrue(nc.items.value.isEmpty())
    }

    @Test
    fun keepsTheLatestSixty() {
        val (nc) = center()
        repeat(65) { push("""{"event":"notification","type":"system","title":"n$it","body":""}""") }
        assertEquals(60, nc.items.value.size)
        assertEquals("n64", nc.items.value.first().title)
        assertEquals("n5", nc.items.value.last().title)
    }

    @Test
    fun readDismissAndClear() {
        val (nc) = center()
        repeat(3) { push("""{"event":"notification","type":"system","title":"n$it","body":""}""") }
        val (a, b, c) = nc.items.value
        nc.markRead(b.id)
        assertEquals(listOf(false, true, false), nc.items.value.map { it.read })
        nc.dismiss(a.id)
        assertEquals(listOf(b.id, c.id), nc.items.value.map { it.id })
        nc.markAllRead()
        assertEquals(0, nc.unread)
        nc.clear()
        assertTrue(nc.items.value.isEmpty())
    }

    @Test
    fun theListSurvivesARestart() {
        val (nc) = center()
        push("""{"event":"notification","type":"order_update","title":"Order paid","body":"BH-1042"}""")
        nc.markAllRead()
        val (again) = center()
        assertEquals(listOf("Order paid"), again.items.value.map { it.title })
        assertTrue(again.items.value.single().read)
    }

    @Test
    fun everyBackendTypeHasALook() {
        val kinds = mapOf(
            "intercept" to "intercept", "human_transfer" to "intercept", "media_escalation" to "intercept",
            "take_back" to "intercept", "availability_check" to "intercept",
            "new_message" to "new_message", "new_conversation" to "new_message", "draft_ready" to "new_message",
            "order" to "order", "order_update" to "order", "hub_event" to "order",
            "transfer" to "transfer",
            "system" to "system", "daily_summary" to "system", "planned_action" to "system", "standup" to "system",
            "selfcheck" to "system", "something_new" to "system",
        )
        kinds.forEach { (type, kind) -> assertEquals(type, kind, NotificationCenter.kindOf(type)) }
        assertFalse(kinds.values.any { it !in setOf("intercept", "new_message", "order", "transfer", "system") })
    }
}
