package ke.co.bethanyhouse.neema.core

import android.media.AudioManager
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.notify.AlertGate
import ke.co.bethanyhouse.neema.core.notify.AlertSink
import ke.co.bethanyhouse.neema.core.notify.ContactNames
import ke.co.bethanyhouse.neema.core.notify.MessageAlerts
import ke.co.bethanyhouse.neema.core.notify.NotificationCenter
import ke.co.bethanyhouse.neema.core.notify.Notifier
import ke.co.bethanyhouse.neema.core.notify.SystemAlert
import ke.co.bethanyhouse.neema.core.notify.inboundPingOf
import ke.co.bethanyhouse.neema.core.notify.muteStatus
import ke.co.bethanyhouse.neema.core.notify.ringerPlan
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.AlertSettings
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.MemoryPrefs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.serialization.json.JsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.time.ZoneId

/**
 * Every customer message beeps and buzzes: open or closed, what mute and the
 * Profile switches silence, what a burst sounds like, what reaches the tray
 * and what never beeps (our own replies, the AI's, team updates).
 */
class MessageAlertsTest {
    // Only for a Context; nothing is rendered.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private class Tray : AlertSink {
        val posted = mutableListOf<SystemAlert>()
        val cancelled = mutableListOf<Int>()
        override fun canPost() = true
        override fun post(alert: SystemAlert) { posted += alert }
        override fun cancel(id: Int) { cancelled += id }
        override fun active(): Set<Int> = posted.map { it.id }.toSet() - cancelled.toSet()
        override fun summary(count: Int, lines: List<String>) {}
        override fun cancelSummary() {}
    }

    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val factory = FakeSocketFactory()
    private val raw = MemoryPrefs()
    private val foreground = MutableStateFlow(false)
    private val tray = Tray()
    private val plays = mutableListOf<Pair<Boolean, Boolean>>()
    private var clock = 1_000_000L
    private lateinit var prefs: AppPrefs

    private fun start(): MessageAlerts {
        prefs = AppPrefs(paparazzi.context, raw)
        val socket = LiveSocket(factory, "https://neema.test", scope)
        val nc = NotificationCenter(paparazzi.context, scope, socket, prefs, MemoryPrefs(), tray)
        nc.start(foreground)
        val ma = MessageAlerts(scope, socket, nc, prefs, tray, { s, v -> plays += s to v }, AlertGate(), { clock })
        ma.start(foreground)
        socket.connect("a1"); factory.last.open()
        return ma
    }

    @After fun forget() = ContactNames.clear()

    private fun customer(text: String = "Do you have albs in size M?", conv: String = "c1", extra: String = "") =
        factory.last.frame("""{"type":"new_message","conversationId":"$conv","sender":"user","text":"$text"$extra}""")

    private fun frame(json: String) = NeemaJson.parseToJsonElement(json) as JsonObject

    // 1. The app closed: a WhatsApp message beeps, buzzes and shows who wrote.
    @Test fun inTheBackgroundAMessageBeepsBuzzesAndShowsInTheTray() {
        ContactNames.learn(listOf(Conversation(id = "c1", waId = "254700111222", name = "Fr. Peter Kamau")))
        start()
        customer(extra = ""","waId":"254700111222"""")
        assertEquals(listOf(true to true), plays)
        val row = tray.posted.single()
        assertEquals(Notifier.CH_MESSAGES, row.channel)
        assertEquals("Fr. Peter Kamau", row.title)
        assertEquals("Do you have albs in size M?", row.body)
        assertEquals("tap opens the chat", "c1", row.convKey)
    }

    // 2. The app open: it beeps and buzzes; the inbox shows it, so no tray row.
    @Test fun inTheForegroundItBeepsWithoutATrayRow() {
        foreground.value = true
        start()
        customer()
        assertEquals(listOf(true to true), plays)
        assertTrue(tray.posted.isEmpty())
    }

    // 3. Our replies, the AI's, a colleague's — never a beep.
    @Test fun onlyTheCustomersOwnMessagesBeep() {
        start()
        factory.last.frame("""{"type":"new_message","conversationId":"c1","sender":"ai","text":"Yes, we do"}""")
        factory.last.frame("""{"type":"new_message","conversationId":"c1","sender":"human_agent","text":"Sending now"}""")
        factory.last.frame("""{"type":"message","conversationId":"c1","direction":"outbound","text":"Order confirmed"}""")
        factory.last.frame("""{"type":"intercept_changed","conversationId":"c1","mode":"human"}""")
        assertTrue(plays.isEmpty()); assertTrue(tray.posted.isEmpty())
        // The older inbound shape (web chat, TikTok) does.
        clock += 5_000
        factory.last.frame("""{"type":"message","conversationId":"c2","direction":"inbound","text":"hi","channel":"web_chat"}""")
        assertEquals(1, plays.size)
        assertEquals("Website chat customer · Website chat", tray.posted.single().title)
    }

    // 4. Muted for an hour: messages still arrive in the tray, silently; after the hour they beep again.
    @Test fun muteSilencesUntilItEnds() {
        start()
        prefs.muteFor(3_600_000L, now = clock)
        customer()
        assertTrue("muted: no sound, no buzz", plays.isEmpty())
        assertEquals("still in the tray", 1, tray.posted.size)
        clock += 3_600_001L
        customer("Are you there?")
        assertEquals(listOf(true to true), plays)
        // Until turned back on: stays silent however long it has been; unmute restores.
        prefs.muteFor(null, now = clock)
        clock += 30L * 24 * 3_600_000L
        customer("Hello?")
        assertEquals(1, plays.size)
        prefs.unmute()
        clock += 5_000
        customer("Hello??")
        assertEquals(2, plays.size)
    }

    // 5. Sound off, vibration on (a meeting): a buzz only; both off: nothing.
    @Test fun theSwitchesChooseSoundAndBuzz() {
        start()
        prefs.setAlerts(prefs.alerts.value.copy(messageSound = false))
        customer()
        assertEquals(false to true, plays.last())
        clock += 5_000
        prefs.setAlerts(prefs.alerts.value.copy(messageVibrate = false))
        customer("again")
        assertEquals(1, plays.size)
    }

    // 6. A burst (a customer sends five photos): one beep, one tray row.
    @Test fun aBurstBeepsOnce() {
        start()
        repeat(5) { i -> clock += 200; customer("", extra = ""","mediaType":"image","mediaUrl":"u$i"""") }
        assertEquals(1, plays.size)
        assertEquals("📷 Photo", tray.posted.last().body)
        assertEquals("one row per customer", 1, tray.posted.map { it.id }.toSet().size)
        // Two seconds on, the next message beeps again.
        clock += 2_500
        customer("Which is cheaper?")
        assertEquals(2, plays.size)
    }

    // 7. A brand-new chat: the "New chat" alert and the first message sound once and share one tray row.
    @Test fun aNewChatAndItsFirstMessageBeepOnceInOneRow() {
        start()
        factory.last.frame("""{"event":"notification","type":"new_conversation","title":"New chat from Mary","body":"Hi","wa_id":"254722000111"}""")
        customer("Hi", conv = "c-new", extra = ""","waId":"254722000111"""")
        assertEquals(1, plays.size)
        assertEquals(1, tray.posted.map { it.id }.toSet().size)
    }

    // 8. "New conversations" switched off in Profile: no row, no beep.
    @Test fun theNewConversationsSwitchSilencesMessages() {
        raw.edit().putBoolean("notif_new_conv", false).apply()
        start()
        customer()
        assertTrue(plays.isEmpty()); assertTrue(tray.posted.isEmpty())
    }

    // 9. Alerts that need someone beep; team updates (standup, released to AI) don't.
    @Test fun alertsBeepTeamUpdatesDoNot() {
        foreground.value = true
        start()
        factory.last.frame("""{"event":"notification","type":"standup","title":"Morning standup","body":"3 follow-ups"}""")
        factory.last.frame("""{"event":"notification","type":"system","title":"Released to Neema","body":"x"}""")
        assertTrue(plays.isEmpty())
        factory.last.frame("""{"event":"notification","type":"human_transfer","title":"Transferred to you","body":"Mary","conversationId":"c7"}""")
        assertEquals(1, plays.size)
    }

    // 10. Opening the app clears the message rows it posted.
    @Test fun openingTheAppClearsMessageRows() {
        start()
        customer(conv = "c1"); clock += 3_000; customer(conv = "c2")
        foreground.value = true
        assertEquals(tray.posted.map { it.id }.toSet(), tray.cancelled.toSet())
    }

    // 11. Messenger, no name known yet: says which app, never a raw id.
    @Test fun messengerWithoutANameSaysWhichApp() {
        start()
        customer("price?", conv = "m1", extra = ""","channel":"messenger"""")
        assertEquals("Messenger customer · Messenger", tray.posted.single().title)
    }

    // 12. What counts as the customer's own message.
    @Test fun inboundFramesAreRecognised() {
        assertEquals("🎤 Voice message", inboundPingOf(frame("""{"type":"new_message","conversationId":"c","sender":"user","mediaType":"audio"}"""))!!.preview)
        assertEquals("SMS", inboundPingOf(frame("""{"type":"new_message","conversationId":"c","sender":"user","text":"hi","channel":"sms"}"""))!!.app)
        assertNull("the SMS bridge's agent ping is not a message", inboundPingOf(frame("""{"event":"notification","type":"new_message","conversationId":"c"}""")))
        assertNull("no thread, nothing to open", inboundPingOf(frame("""{"type":"new_message","sender":"user","text":"hi"}""")))
    }

    // 13. The phone's own switch wins: silent is silent, vibrate only buzzes, Do Not Disturb is quiet.
    @Test fun thePhonesRingerSwitchWins() {
        assertEquals(true to true, ringerPlan(true, true, AudioManager.RINGER_MODE_NORMAL, dnd = false))
        assertEquals(false to true, ringerPlan(true, true, AudioManager.RINGER_MODE_VIBRATE, dnd = false))
        assertEquals(false to false, ringerPlan(true, true, AudioManager.RINGER_MODE_SILENT, dnd = false))
        assertEquals(false to false, ringerPlan(true, true, AudioManager.RINGER_MODE_NORMAL, dnd = true))
        assertEquals(false to false, ringerPlan(false, false, AudioManager.RINGER_MODE_NORMAL, dnd = false))
    }

    // 14. How mute reads in Profile and the bell.
    @Test fun muteReadsInPlainWords() {
        val zone = ZoneId.of("Africa/Nairobi")
        val now = java.time.ZonedDateTime.of(2026, 9, 28, 14, 40, 0, 0, zone).toInstant().toEpochMilli()
        assertNull(muteStatus(0, now, zone))
        assertEquals("Muted until 3:40 PM", muteStatus(now + 3_600_000L, now, zone))
        assertEquals("Muted until tomorrow, 10:40 PM", muteStatus(now + 32 * 3_600_000L, now, zone))
        assertEquals("Muted until you turn it back on", muteStatus(AlertSettings.FOREVER, now, zone))
        assertNull("an ended mute", muteStatus(now - 1, now, zone))
    }

    // 15. The choices survive the app restarting.
    @Test fun settingsPersist() {
        start()
        prefs.setAlerts(AlertSettings(messageSound = false, messageVibrate = true, callRing = false, callVibrate = true, mutedUntil = 42))
        val again = AppPrefs(paparazzi.context, raw).alerts.value
        assertEquals(AlertSettings(messageSound = false, messageVibrate = true, callRing = false, callVibrate = true, mutedUntil = 42), again)
        assertEquals("defaults: everything on, not muted", AlertSettings(), AppPrefs(paparazzi.context, MemoryPrefs()).alerts.value)
    }
}
