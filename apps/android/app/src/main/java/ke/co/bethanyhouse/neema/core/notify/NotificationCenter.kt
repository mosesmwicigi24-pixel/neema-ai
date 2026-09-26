package ke.co.bethanyhouse.neema.core.notify

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.content.Context
import android.content.SharedPreferences
import androidx.core.app.NotificationCompat
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject

/** One entry in the bell (components/ui/Notifications.tsx), persisted — last 60. */
@Serializable
data class AppNotification(
    val id: String,
    /** One of the 13 types the backend sends (see LiveSocket), or the web's legacy names. */
    val type: String,
    val title: String,
    val body: String,
    val convKey: String? = null,
    val at: Long,
    val read: Boolean = false,
)

/**
 * Listens for `{"event":"notification", …}` frames (useAgentNotifications),
 * keeps the bell's list, and raises a system notification when the app isn't
 * in front — the web's `new Notification(...)` when permission is granted.
 */
class NotificationCenter(
    private val context: Context,
    private val scope: CoroutineScope,
    private val socket: LiveSocket,
    private val appPrefs: ke.co.bethanyhouse.neema.core.util.AppPrefs,
    override: SharedPreferences? = null,
    /** Where system notifications go; tests record them. */
    private val sink: AlertSink = Notifier.sink(context),
) {
    private val prefs = override ?: context.getSharedPreferences("neema_notifications", Context.MODE_PRIVATE)
    private val listSer = ListSerializer(AppNotification.serializer())
    private val seq = java.util.concurrent.atomic.AtomicLong()

    private val _items = MutableStateFlow(load())
    val items: StateFlow<List<AppNotification>> = _items.asStateFlow()

    private val _incoming = MutableSharedFlow<AppNotification>(extraBufferCapacity = 16)
    /** Every notification as it lands (the dashboard toasts it and refetches). */
    val incoming: SharedFlow<AppNotification> = _incoming.asSharedFlow()

    val unread: Int get() = _items.value.count { !it.read }

    /** System notifications currently in the tray, oldest first: system id → bell entry. */
    private val tray = LinkedHashMap<Int, AppNotification>()

    /** The last few frames, to drop an exact repeat (a double publish, a replaced socket draining). */
    private val recent = ArrayDeque<Pair<String, Long>>()

    private fun load(): List<AppNotification> =
        runCatching { NeemaJson.decodeFromString(listSer, prefs.getString("items", "[]")!!) }.getOrDefault(emptyList())

    private fun save(list: List<AppNotification>) {
        _items.value = list
        prefs.edit().putString("items", NeemaJson.encodeToString(listSer, list)).apply()
    }

    fun start(foreground: StateFlow<Boolean>) {
        scope.launch {
            socket.events.collect { e ->
                if (e.str("event") != "notification") return@collect
                val n = fromFrame(e)
                if (isRepeat(n)) return@collect
                save((listOf(n) + _items.value).take(60))
                _incoming.tryEmit(n)
                // In front, the toast and the bell are the alert: no second,
                // duplicate one in the tray.
                if (!foreground.value) alertFor(n, appPrefs.raw)?.let(::raise)
            }
        }
    }

    private fun isRepeat(n: AppNotification): Boolean {
        val key = listOf(n.type, n.title, n.body, n.convKey.orEmpty()).joinToString("|")
        val now = AppClock.now()
        synchronized(recent) {
            while (recent.isNotEmpty() && now - recent.first().second > REPEAT_WINDOW_MS) recent.removeFirst()
            if (recent.any { it.first == key }) return true
            recent.addLast(key to now)
            if (recent.size > 32) recent.removeFirst()
        }
        return false
    }

    private fun raise(a: SystemAlert) {
        // Denied on Android 13+ (or switched off): the bell and the toast still
        // have it, and nothing here ever asks again.
        if (!sink.canPost()) return
        val n = _items.value.firstOrNull { it.id == a.notificationId } ?: return
        synchronized(tray) {
            sink.active()?.let { live -> tray.keys.retainAll(live) }
            tray.remove(a.id)
            tray[a.id] = n
        }
        sink.post(a)
        refreshSummary()
    }

    private fun refreshSummary() {
        val shown = synchronized(tray) { tray.values.toList() }
        when {
            shown.size >= 2 -> sink.summary(shown.size, shown.asReversed().map { summaryLine(it) })
            shown.isEmpty() -> sink.cancelSummary()
        }
    }

    /** The bell read/removed [ids]: take their system notifications out of the tray too. */
    private fun withdraw(ids: Set<String>) {
        val gone = synchronized(tray) {
            tray.filterValues { it.id in ids }.keys.toList().onEach { tray.remove(it) }
        }
        if (gone.isEmpty()) return
        gone.forEach(sink::cancel)
        refreshSummary()
    }

    private fun fromFrame(e: JsonObject): AppNotification = AppNotification(
        // Unique even for a burst in one millisecond (the list keys on it).
        id = "${AppClock.now()}-${seq.incrementAndGet()}-${(0..9999).random()}",
        type = e.str("type") ?: "system",
        title = e.str("title") ?: "Neema",
        body = e.str("body") ?: "",
        convKey = e.str("conversationId") ?: e.str("conv_id") ?: e.str("convId") ?: e.str("wa_id") ?: e.str("waId"),
        // The frame's own `ts` (AgentNotification.ts) when it carries one, else arrival time.
        at = ke.co.bethanyhouse.neema.core.util.Fmt.millis(e.str("ts"))?.takeIf { it > 0 } ?: AppClock.now(),
    )

    fun markAllRead() {
        save(_items.value.map { it.copy(read = true) })
        withdraw(_items.value.map { it.id }.toSet())
    }
    fun markRead(id: String) {
        save(_items.value.map { if (it.id == id) it.copy(read = true) else it })
        withdraw(setOf(id))
    }
    /** The x on one row. */
    fun dismiss(id: String) {
        save(_items.value.filterNot { it.id == id })
        withdraw(setOf(id))
    }
    /** Clear all (also on sign-out): the tray empties with the bell. */
    fun clear() {
        val ids = _items.value.map { it.id }.toSet()
        save(emptyList())
        withdraw(ids)
        synchronized(tray) { tray.clear() }
        sink.cancelSummary()
    }

    companion object {
        private const val REPEAT_WINDOW_MS = 3_000L

        private fun summaryLine(n: AppNotification) = if (n.body.isBlank()) n.title else "${n.title} — ${n.body}"

        /**
         * The phone notification for [n], or null when the agent's switches
         * (Profile → Notifications, keys "notif_<name>", defaults as there)
         * silence it. The switches only gate the phone notification; the bell
         * and toast still record everything. (On the web they are decorative.)
         *
         * Every type the backend sends (see LiveSocket), by urgency:
         * - Alerts channel, high — someone must act: `new_conversation`,
         *   `human_transfer`, `media_escalation`, `intercept`, `transfer`,
         *   `take_back`, `availability_check`, `draft_ready`, `planned_action`,
         *   `hub_event`, `order_update`.
         * - Customer messages, default — `new_message` (an SMS).
         * - Team updates, low — `system` (released to AI), `standup`,
         *   `daily_summary`, `selfcheck`, anything new.
         *
         * Tap: the conversation when the frame names one; order updates (and a
         * hub event with no matching thread) open Orders; the rest open the app.
         * One notification per conversation: a thread's newer alert replaces
         * its older one instead of stacking a second row.
         */
        fun alertFor(n: AppNotification, prefs: SharedPreferences): SystemAlert? {
            val on = when (n.type) {
                "new_conversation", "new_message" -> prefs.getBoolean("notif_new_conv", true)
                "human_transfer", "transfer", "media_escalation" -> prefs.getBoolean("notif_human_transfer", true)
                "order_update" -> prefs.getBoolean("notif_order_updates", false)
                "daily_summary", "standup" -> prefs.getBoolean("notif_daily_summary", true)
                else -> true
            }
            if (!on) return null
            val (channel, priority) = when (n.type) {
                "new_conversation", "human_transfer", "media_escalation", "intercept", "transfer", "take_back",
                "availability_check", "draft_ready", "planned_action", "hub_event", "order_update", "order",
                -> Notifier.CH_ALERTS to NotificationCompat.PRIORITY_HIGH
                "new_message" -> Notifier.CH_MESSAGES to NotificationCompat.PRIORITY_DEFAULT
                else -> Notifier.CH_UPDATES to NotificationCompat.PRIORITY_LOW
            }
            return SystemAlert(
                id = systemId(n),
                channel = channel,
                title = n.title,
                body = n.body,
                priority = priority,
                convKey = n.convKey,
                view = viewFor(n),
                notificationId = n.id,
            )
        }

        /** Where tapping [n] (in the bell or the tray) goes when it names no conversation. */
        fun viewFor(n: AppNotification): String? = when {
            n.convKey != null -> null
            n.type == "order_update" || n.type == "order" || n.type == "hub_event" -> "orders"
            else -> null
        }

        /** Stable per conversation, else per entry; clear of the live (1001), summary (1002) and call ids. */
        fun systemId(n: AppNotification): Int {
            val h = (n.convKey?.let { "conv:$it" } ?: n.id).hashCode() and 0x7fffffff
            return 10_000 + h % 1_000_000_000
        }

        /**
         * The bell's five looks (Notifications.tsx META). The web keys them on
         * intercept / new_message / order / transfer / system only; every type
         * the backend actually sends is folded into the nearest one here.
         */
        fun kindOf(type: String): String = when (type) {
            "intercept", "human_transfer", "media_escalation", "take_back", "availability_check" -> "intercept"
            "new_message", "new_conversation", "draft_ready" -> "new_message"
            "order", "order_update", "hub_event" -> "order"
            "transfer" -> "transfer"
            else -> "system"
        }
    }
}
