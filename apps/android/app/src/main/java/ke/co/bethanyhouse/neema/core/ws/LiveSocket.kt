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
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * The dashboard's live feed: a plain FastAPI WebSocket at `/ws/{agent_id}`
 * (routers/websocket.py) that relays every `ws:channel:*` Redis broadcast to
 * every connected client. Port of `lib/websocket.tsx`: reconnect 2s after any
 * close, JSON `{"type":"ping"}` every 25s (the server answers
 * `{"type":"pong"}`, dropped here; anything that isn't JSON makes the server
 * close the socket, so only JSON is ever sent).
 *
 * The socket is not filtered per agent or per conversation: every frame
 * reaches every client, and consumers collect [events] and filter on `type` /
 * `event` / `conversationId` themselves, as the web's `ws.on("event", …)`
 * handlers do. Frames are not typed here on purpose — the backend adds keys
 * freely — but this is the complete set it publishes today (grep
 * `ws:channel` / `broadcast(` / `_broadcast(` under apps/api/app):
 *
 * ## Conversation frames — channel `ws:channel:{conversation_id}`
 * Keys are camelCase. `conversationId` is always the conversation UUID.
 *
 * - `new_message` — a message landed in a thread. `{type, conversationId,
 *   sender: "user"|"ai"|"human_agent", text, id?, waId?, channel?, direction?,
 *   mediaType?, mediaId?, mediaUrl?, mediaCaption?, mimeType?, filename?,
 *   replyTo?, translation?, translatedFrom?}`. Only the AI's own text reply
 *   (n8n_bridge.outbound_gate) carries the DB `id`; every other sender omits
 *   it, and most omit `direction` (read absent as "outbound" unless
 *   `sender == "user"`). Senders: n8n_bridge (inbound WhatsApp, AI replies),
 *   conversation.py (agent reply / AI message / agent media / transfer
 *   notice), meta_webhook (Messenger / Instagram / Facebook inbound), sms.py,
 *   public.py (website measurement form), agent/tools.py (product photo).
 * - `message` — the OLDER shape some channels still use: `{type,
 *   conversationId, text, direction: "inbound"|"outbound", waId?, channel?,
 *   sender?, reply_to?}` (web_chat.py and manychat / tiktok inbound;
 *   n8n_bridge outbound channel sends and comment replies). The web ignores
 *   it; treat it as "this thread moved".
 * - `intercept_changed` — the thread's mode changed. `{type, conversationId,
 *   mode?: "ai"|"human"|"paused", assignedAgentId?: string|null,
 *   assignedAgentName?, eventKind: "intercept"|"release"|"pause"|"transfer"|
 *   "escalated"|"flag", eventAgentName?, eventReason?, eventNote?}`. `mode` is
 *   missing on an AI escalation (conversation.record_escalation).
 * - `ai_draft_ready` — a suggested reply for a human-held thread. `{type,
 *   conversationId, draft, waId?}` (n8n_bridge, copilot, agent/runtime).
 * - `translations` — the background translator finished. `{type,
 *   conversationId, items: [{id, text, lang: string|null}]}` (translate.py).
 * - `history_cleared` — `{type, conversationId, clearedBy}` (admin.py
 *   clear_chat_history).
 *
 * ## Agent notifications — channel `ws:channel:agents:all`
 * Always `{event: "notification", type, title, body}` plus a pointer to the
 * thread that is spelled differently by each sender: `conversationId`,
 * `conv_id`, `wa_id` or `waId`. `type` is one of:
 * `new_conversation` (wa_native), `new_message` (sms.py — note the same name
 * as the conversation frame, told apart by `event`), `human_transfer`
 * (n8n_bridge media, + `mediaType`), `media_escalation` (wa_native),
 * `intercept` (pick-up / AI escalation), `system` (released to AI),
 * `draft_ready` (agent/runtime), `availability_check` (agent/tools),
 * `take_back` (copilot), `planned_action` (actions.py), `standup`
 * (actions.py), `hub_event` (hub_events.py), `selfcheck` (selfcheck.py).
 * `order_update`, `transfer` and `daily_summary` are named by the web's
 * AgentNotification type but no longer sent by anything.
 *
 * ## Calls — channel `ws:channel:calls` (whatsapp_webhook.py)
 * Keys are snake_case.
 * - `incoming_call` — `{type, call_id, from, name: string|null, at}` (`at` is
 *   Meta's epoch-seconds timestamp, a string).
 * - `outbound_answer` — `{type, call_id, sdp}`: the customer picked up our call.
 * - `call_ended` — `{type, call_id, status, duration: number|null}`.
 */
class LiveSocket(
    /** An OkHttpClient in the app; a fake in tests. */
    private val client: WebSocket.Factory,
    private val baseUrl: String,
    private val scope: CoroutineScope,
    private val reconnectDelayMs: Long = 2_000,
    private val pingEveryMs: Long = 25_000,
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

    internal fun url(agentId: String): String {
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
    /**
     * Reconnect immediately if the socket is down but wanted (the app came
     * back to the foreground mid-backoff). A socket closed on purpose —
     * signed out, or backgrounded without live mode — stays closed: the
     * session/foreground watcher in NeemaApplication decides when to reopen.
     */
    @Synchronized
    fun nudge() {
        if (agentId == null || closed || _connected.value) return
        reconnectJob?.cancel(); ws?.cancel(); ws = null; open()
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
                        delay(pingEveryMs)
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
                runCatching { Log.w("LiveSocket", "socket failure: ${t.message}") }
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
        reconnectJob = scope.launch { delay(reconnectDelayMs); if (!closed) open() }
    }
}

/** Convenience readers for the loosely-typed socket frames. */
fun JsonObject.str(key: String): String? = this[key]?.let { runCatching { it.jsonPrimitive.contentOrNull }.getOrNull() }
