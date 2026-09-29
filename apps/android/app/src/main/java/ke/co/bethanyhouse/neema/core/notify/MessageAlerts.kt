package ke.co.bethanyhouse.neema.core.notify

import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.VibrationAttributes
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.core.app.NotificationCompat
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/** A customer's message that just landed in a thread, as the phone announces it. */
data class InboundPing(
    val conversationId: String,
    val waId: String?,
    /** "WhatsApp", "Messenger", "Instagram", "Facebook", "SMS"… */
    val app: String,
    /** The words, or "📷 Photo" / "🎤 Voice message" for media. */
    val preview: String,
)

/**
 * The customer's own message in a conversation frame (`new_message`, or the
 * older `message` shape): `sender: "user"` or `direction: "inbound"`. The
 * agent-level `event: "notification"` frames, our own replies, the AI's and
 * a colleague's are not — they never beep.
 */
internal fun inboundPingOf(e: JsonObject): InboundPing? {
    if (e.str("event") == "notification") return null
    val type = e.str("type")
    if (type != "new_message" && type != "message") return null
    val inbound = e.str("sender") == "user" || e.str("direction") == "inbound"
    if (!inbound) return null
    val conv = e.str("conversationId")?.takeIf { it.isNotBlank() } ?: return null
    val text = e.str("text")?.trim().orEmpty()
    val preview = text.ifEmpty {
        when (e.str("mediaType")) {
            "image", "sticker" -> "📷 Photo"
            "audio", "voice" -> "🎤 Voice message"
            "video" -> "🎥 Video"
            "document", "file" -> "📄 Document"
            "location" -> "📍 Location"
            else -> "New message"
        }
    }
    return InboundPing(conv, e.str("waId")?.takeIf { it.isNotBlank() }, appName(e.str("channel")), preview)
}

internal fun appName(channel: String?): String = when (channel?.lowercase()) {
    null, "", "whatsapp", "wa" -> "WhatsApp"
    "messenger" -> "Messenger"
    "instagram", "ig" -> "Instagram"
    "facebook", "fb" -> "Facebook"
    "sms" -> "SMS"
    "web", "web_chat", "webchat" -> "Website chat"
    "tiktok" -> "TikTok"
    else -> channel.replaceFirstChar { it.uppercase() }
}

/**
 * Customer names the app has seen (every inbox page, every thread opened), so
 * a message notification says who wrote — a conversation frame carries only
 * ids. Kept for the life of the process; the last [MAX] are enough.
 */
object ContactNames {
    private const val MAX = 2_000
    private val names = object : LinkedHashMap<String, String>(256, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>?) = size > MAX
    }

    fun learn(conversations: List<Conversation>) = synchronized(names) {
        conversations.forEach { c ->
            val n = c.name?.trim()?.takeIf { it.isNotEmpty() } ?: return@forEach
            names[c.id] = n
            c.waId?.let { names[it] = n }
            c.externalId?.let { names[it] = n }
        }
    }

    fun learn(c: Conversation) = learn(listOf(c))

    fun nameFor(conversationId: String?, handle: String?): String? = synchronized(names) {
        conversationId?.let(names::get) ?: handle?.let(names::get)
    }

    internal fun clear() = synchronized(names) { names.clear() }
}

/**
 * One beep for a burst: a photo album, or a new chat's alert and its first
 * message arriving together, sound once — not a machine-gun of pings.
 */
class AlertGate(private val quietMs: Long = 2_000) {
    private var last = Long.MIN_VALUE / 2
    @Synchronized fun claim(now: Long): Boolean {
        if (now - last < quietMs) return false
        last = now
        return true
    }
}

/** Plays a message alert: the phone's notification sound and/or a short buzz. */
fun interface AlertPlayer {
    fun play(sound: Boolean, vibrate: Boolean)
}

/**
 * What the phone does for one alert, given the ringer switch and Do Not
 * Disturb: silent mode is silent (no buzz either), vibrate mode only buzzes,
 * and Do Not Disturb is respected for messages (calls follow the system).
 */
internal fun ringerPlan(sound: Boolean, vibrate: Boolean, ringerMode: Int, dnd: Boolean): Pair<Boolean, Boolean> = when {
    dnd || ringerMode == AudioManager.RINGER_MODE_SILENT -> false to false
    ringerMode == AudioManager.RINGER_MODE_VIBRATE -> false to vibrate
    else -> sound to vibrate
}

/** The real [AlertPlayer]: the phone's default notification sound, and a double buzz. */
class DeviceAlertPlayer(private val context: Context) : AlertPlayer {
    private var ringtone: Ringtone? = null

    override fun play(sound: Boolean, vibrate: Boolean) {
        val am = context.getSystemService(AudioManager::class.java)
        val nm = context.getSystemService(NotificationManager::class.java)
        val dnd = runCatching { nm?.currentInterruptionFilter?.let { it > NotificationManager.INTERRUPTION_FILTER_ALL } }.getOrNull() ?: false
        val (s, v) = ringerPlan(sound, vibrate, am?.ringerMode ?: AudioManager.RINGER_MODE_NORMAL, dnd)
        if (s) runCatching {
            ringtone?.stop()
            val uri = RingtoneManager.getActualDefaultRingtoneUri(context, RingtoneManager.TYPE_NOTIFICATION)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
            ringtone = RingtoneManager.getRingtone(context, uri)?.apply {
                audioAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
                play()
            }
        }
        if (v) runCatching { vibrate(context, MESSAGE_BUZZ, ring = false) }
    }

    companion object {
        /** Two short pulses: a message, not a call. */
        val MESSAGE_BUZZ = longArrayOf(0, 160, 110, 160)
    }
}

internal fun vibratorOf(context: Context): Vibrator? =
    if (Build.VERSION.SDK_INT >= 31) context.getSystemService(VibratorManager::class.java)?.defaultVibrator
    else @Suppress("DEPRECATION") context.getSystemService(Vibrator::class.java)

/**
 * Vibrate with a usage (notification, or ringtone for a call) so Android lets
 * it through while the app runs in the background and applies the phone's
 * own vibration settings to it. [repeat]: index to loop from, -1 = once.
 */
internal fun vibrate(context: Context, pattern: LongArray, ring: Boolean, repeat: Int = -1) {
    val v = vibratorOf(context) ?: return
    if (!v.hasVibrator()) return
    val effect = VibrationEffect.createWaveform(pattern, repeat)
    if (Build.VERSION.SDK_INT >= 33) {
        v.vibrate(effect, VibrationAttributes.createForUsage(if (ring) VibrationAttributes.USAGE_RINGTONE else VibrationAttributes.USAGE_NOTIFICATION))
    } else {
        @Suppress("DEPRECATION")
        v.vibrate(
            effect,
            AudioAttributes.Builder()
                .setUsage(if (ring) AudioAttributes.USAGE_NOTIFICATION_RINGTONE else AudioAttributes.USAGE_NOTIFICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build(),
        )
    }
}

/**
 * Every customer message makes a sound. Open or not, a message from a
 * customer beeps and buzzes (per Profile → Sounds & vibration, and not while
 * muted); with the app in the background it also shows in the tray, one row
 * per customer, tapping into their chat. Alerts that already raise their own
 * notification (a new chat, a transfer, an escalation) beep the same way.
 *
 * The tray channels are silent (Notifier): the sound and buzz come from here,
 * so mute and the switches work the same in front and behind.
 */
class MessageAlerts(
    private val scope: CoroutineScope,
    private val socket: LiveSocket,
    private val notifications: NotificationCenter,
    private val prefs: AppPrefs,
    private val sink: AlertSink,
    private val player: AlertPlayer,
    private val gate: AlertGate = AlertGate(),
    private val now: () -> Long = AppClock::now,
) {
    fun start(foreground: StateFlow<Boolean>) {
        scope.launch {
            socket.events.collect { e ->
                val p = runCatching { inboundPingOf(e) }.getOrNull() ?: return@collect
                onInbound(p, foreground.value)
            }
        }
        scope.launch { notifications.incoming.collect(::onNotification) }
        // Back in the app: the message rows have done their job (the inbox
        // shows the unread), as a messaging app clears its tray on open.
        scope.launch { foreground.collect { if (it) clearTray() } }
    }

    /** Message rows this posted and hasn't cleared. */
    private val posted = mutableSetOf<Int>()

    internal fun clearTray() {
        val ids = synchronized(posted) { posted.toList().also { posted.clear() } }
        ids.forEach(sink::cancel)
    }

    /** A customer wrote. The "New conversations" switch (Profile) turns message alerts off entirely. */
    internal fun onInbound(p: InboundPing, foreground: Boolean) {
        if (!prefs.raw.getBoolean("notif_new_conv", true)) return
        if (!foreground && sink.canPost()) {
            val a = messageAlert(p)
            synchronized(posted) { posted += a.id }
            sink.post(a)
        }
        beep()
    }

    /** A bell alert landed: the ones that raise a phone notification beep too (not team updates). */
    internal fun onNotification(n: AppNotification) {
        val a = NotificationCenter.alertFor(n, prefs.raw) ?: return
        if (a.channel == Notifier.CH_UPDATES) return
        beep()
    }

    private fun beep() {
        val t = now()
        val s = prefs.alerts.value
        val sound = s.messageSoundAt(t)
        val buzz = s.messageVibrateAt(t)
        if ((sound || buzz) && gate.claim(t)) runCatching { player.play(sound, buzz) }
    }

    companion object {
        /** The tray row for [p]: one per customer (keyed like a new chat's alert, so the two merge). */
        fun messageAlert(p: InboundPing): SystemAlert {
            val who = ContactNames.nameFor(p.conversationId, p.waId)
                ?: p.waId?.let { Fmt.formatPhone(it).ifEmpty { null } }
                ?: "${p.app} customer"
            val key = p.waId ?: p.conversationId
            return SystemAlert(
                id = NotificationCenter.systemId(AppNotification(id = key, type = "new_message", title = "", body = "", convKey = key, at = 0)),
                channel = Notifier.CH_MESSAGES,
                title = if (p.app == "WhatsApp") who else "$who · ${p.app}",
                body = p.preview,
                priority = NotificationCompat.PRIORITY_HIGH,
                convKey = p.conversationId,
            )
        }
    }
}

/** The mute choices, as offered in Profile and the bell: duration (null = until turned back on). */
val MUTE_CHOICES: List<Pair<String, Long?>> = listOf(
    "1 hour" to 3_600_000L,
    "8 hours" to 8 * 3_600_000L,
    "Until I turn it back on" to null,
)

/**
 * "Muted until 3:40 PM", "Muted until tomorrow, 1:10 AM", "Muted until you
 * turn it back on" — or null when not muted at [now].
 */
fun muteStatus(until: Long, now: Long, zone: java.time.ZoneId = java.time.ZoneId.systemDefault()): String? {
    if (until <= now) return null
    if (until == ke.co.bethanyhouse.neema.core.util.AlertSettings.FOREVER) return "Muted until you turn it back on"
    val at = java.time.Instant.ofEpochMilli(until).atZone(zone)
    val today = java.time.Instant.ofEpochMilli(now).atZone(zone).toLocalDate()
    val time = at.format(java.time.format.DateTimeFormatter.ofPattern("h:mm a", java.util.Locale.ENGLISH))
    return when (at.toLocalDate()) {
        today -> "Muted until $time"
        today.plusDays(1) -> "Muted until tomorrow, $time"
        else -> "Muted until ${at.format(java.time.format.DateTimeFormatter.ofPattern("EEE d MMM", java.util.Locale.ENGLISH))}, $time"
    }
}
