package ke.co.bethanyhouse.neema.core.ws

import android.util.Log
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * The dashboard's live feed: a plain FastAPI WebSocket at `/ws/{agent_id}`
 * that relays every `ws:channel:*` Redis broadcast (new messages, intercept
 * changes, notifications, incoming calls…). Port of `lib/websocket.tsx`:
 * reconnect 2s after any close, JSON `{"type":"ping"}` every 25s.
 *
 * Consumers collect [events] and filter on `type` / `event` themselves, the
 * same way the web's `ws.on("event", …)` handlers do.
 */
class LiveSocket(
    private val client: OkHttpClient,
    private val baseUrl: String,
    private val scope: CoroutineScope,
) {
    private val _events = MutableSharedFlow<JsonObject>(extraBufferCapacity = 256)
    val events: SharedFlow<JsonObject> = _events.asSharedFlow()

    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected.asStateFlow()

    private var ws: WebSocket? = null
    private var agentId: String? = null
    private var pingJob: Job? = null
    private var reconnectJob: Job? = null
    @Volatile private var closed = true

    private fun url(agentId: String): String {
        val wsBase = baseUrl.trimEnd('/')
            .replaceFirst(Regex("^https://"), "wss://")
            .replaceFirst(Regex("^http://"), "ws://")
            .replace(Regex("/api/?$"), "")
        return "$wsBase/ws/$agentId"
    }

    /** Idempotent: connecting as the same agent again is a no-op. */
    @Synchronized
    fun connect(agentId: String) {
        if (!closed && this.agentId == agentId) return
        disconnect()
        this.agentId = agentId
        closed = false
        open()
    }

    @Synchronized
    fun disconnect() {
        closed = true
        pingJob?.cancel(); reconnectJob?.cancel()
        ws?.close(1000, null); ws = null
        _connected.value = false
    }

    /** Reconnect immediately (e.g. the app came back to the foreground). */
    fun nudge() {
        val id = agentId ?: return
        if (!closed && !_connected.value) { reconnectJob?.cancel(); ws?.cancel(); ws = null; open() }
        else if (closed) connect(id)
    }

    private fun open() {
        val id = agentId ?: return
        val req = Request.Builder().url(url(id)).build()
        ws = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _connected.value = true
                pingJob?.cancel()
                pingJob = scope.launch {
                    while (isActive) {
                        delay(25_000)
                        webSocket.send("""{"type":"ping"}""")
                    }
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val obj = runCatching { NeemaJson.parseToJsonElement(text) as? JsonObject }.getOrNull() ?: return
                if (obj["type"]?.jsonPrimitive?.contentOrNull == "pong") return
                _events.tryEmit(obj)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = dropped(webSocket)
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w("LiveSocket", "socket failure: ${t.message}")
                dropped(webSocket)
            }
        })
    }

    private fun dropped(socket: WebSocket) {
        if (socket !== ws) return
        _connected.value = false
        pingJob?.cancel()
        if (closed) return
        reconnectJob?.cancel()
        reconnectJob = scope.launch { delay(2_000); if (!closed) open() }
    }
}

/** Convenience readers for the loosely-typed socket frames. */
fun JsonObject.str(key: String): String? = this[key]?.let { runCatching { it.jsonPrimitive.contentOrNull }.getOrNull() }
