package ke.co.bethanyhouse.neema.core.notify

import android.content.Context
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
    /** new_conversation | human_transfer | media_escalation | intercept | order_update | transfer | system | daily_summary … */
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
    override: android.content.SharedPreferences? = null,
) {
    private val prefs = override ?: context.getSharedPreferences("neema_notifications", Context.MODE_PRIVATE)
    private val listSer = ListSerializer(AppNotification.serializer())

    private val _items = MutableStateFlow(load())
    val items: StateFlow<List<AppNotification>> = _items.asStateFlow()

    private val _incoming = MutableSharedFlow<AppNotification>(extraBufferCapacity = 16)
    /** Every notification as it lands (the dashboard toasts it and refetches). */
    val incoming: SharedFlow<AppNotification> = _incoming.asSharedFlow()

    val unread: Int get() = _items.value.count { !it.read }

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
                save((listOf(n) + _items.value).take(60))
                _incoming.tryEmit(n)
                if (!foreground.value && wantsSystemAlert(n.type)) {
                    Notifier.post(
                        context, (n.id.hashCode() and 0x7fffffff), Notifier.CH_ALERTS, n.title, n.body,
                        convKey = n.convKey, view = if (n.type == "order_update") "orders" else null,
                    )
                }
            }
        }
    }

    /**
     * The Profile screen's notification switches (keys "notif_<name>" in the
     * app prefs, defaults as there). They silence the phone notification only;
     * the bell still records everything, as on the web.
     */
    private fun wantsSystemAlert(type: String): Boolean {
        val p = appPrefs.raw
        return when (type) {
            "new_conversation" -> p.getBoolean("notif_new_conv", true)
            "human_transfer", "transfer" -> p.getBoolean("notif_human_transfer", true)
            "order_update" -> p.getBoolean("notif_order_updates", false)
            "daily_summary" -> p.getBoolean("notif_daily_summary", true)
            else -> true
        }
    }

    private fun fromFrame(e: JsonObject): AppNotification = AppNotification(
        id = "${System.currentTimeMillis()}-${(0..9999).random()}",
        type = e.str("type") ?: "system",
        title = e.str("title") ?: "Neema",
        body = e.str("body") ?: "",
        convKey = e.str("conversationId") ?: e.str("conv_id") ?: e.str("convId") ?: e.str("wa_id"),
        at = System.currentTimeMillis(),
    )

    fun markAllRead() = save(_items.value.map { it.copy(read = true) })
    fun markRead(id: String) = save(_items.value.map { if (it.id == id) it.copy(read = true) else it })
    fun clear() = save(emptyList())
}
