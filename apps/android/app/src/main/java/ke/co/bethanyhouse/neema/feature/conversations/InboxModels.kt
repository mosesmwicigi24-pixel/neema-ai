package ke.co.bethanyhouse.neema.feature.conversations

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.content.ContentResolver
import android.net.Uri
import ke.co.bethanyhouse.neema.core.api.InboxQuery
import ke.co.bethanyhouse.neema.core.model.ActivityEvent
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.ConversationPage
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.Fmt
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import okio.source
import java.net.URLEncoder

// The thread's wire shapes. The core `Message` model is the api.ts subset; the
// inbox reads a few more fields the server sends on comment threads
// (media_type / has_video on comment_context), so it keeps its own copy here
// rather than widening the shared model under other features.

/** What a Facebook/Instagram comment is ON (messages.comment_context). */
@Serializable
data class PostContext(
    @SerialName("post_id") val postId: String? = null,
    val title: String? = null,
    val permalink: String? = null,
    val thumb: String? = null,
    @SerialName("media_type") val mediaType: String? = null,
    @SerialName("has_video") val hasVideo: Boolean? = null,
    /** Set on OUR public reply: the comment id it answers. */
    @SerialName("reply_to") val replyTo: String? = null,
)

/** The message a bubble quotes (a threaded reply). */
@Serializable
data class QuotedRef(
    val id: String = "",
    val text: String? = null,
    val sender: String? = null,
    @SerialName("media_type") val mediaType: String? = null,
    @SerialName("media_url") val mediaUrl: String? = null,
)

/** One item of GET /admin/conversations/{id}/messages: a message or a system event. */
@Serializable
data class ThreadMsg(
    val id: String = "",
    val type: String = "message",
    val direction: String = "inbound",
    val sender: String = "user",
    val text: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val isNote: Boolean = false,
    val translation: String? = null,
    @SerialName("translated_from") val translatedFrom: String? = null,
    @SerialName("agent_name") val agentName: String? = null,
    @SerialName("event_kind") val eventKind: String? = null,
    @SerialName("event_reason") val eventReason: String? = null,
    @SerialName("media_type") val mediaType: String? = null,
    @SerialName("media_id") val mediaId: String? = null,
    @SerialName("media_url") val mediaUrl: String? = null,
    @SerialName("media_caption") val mediaCaption: String? = null,
    @SerialName("mime_type") val mimeType: String? = null,
    val filename: String? = null,
    /**
     * Free-form JSONB on the server (messages.comment_context) — kept as a raw
     * element and read field by field, so one odd value (or a non-object
     * blob) can't sink the thread.
     */
    @SerialName("comment_context") val commentRaw: JsonElement? = null,
    @SerialName("reply_to") val replyTo: QuotedRef? = null,
) {
    val commentContext: PostContext?
        get() = (commentRaw as? JsonObject)?.let {
            PostContext(
                postId = it.s("post_id"), title = it.s("title"), permalink = it.s("permalink"), thumb = it.s("thumb"),
                mediaType = it.s("media_type"), hasVideo = it.b("has_video"), replyTo = it.s("reply_to"),
            )
        }
    val isSystem: Boolean get() = type == "system_event"
    val inbound: Boolean get() = direction == "inbound"
    val body: String get() = text ?: ""
    /** A bubble this device made up (optimistic send, socket echo without an id). */
    val isLocal: Boolean get() = id.startsWith("optimistic-") || id.startsWith("ws-") || id.startsWith("live-evt-")
    val millis: Long get() = Fmt.millis(createdAt) ?: 0L
}

data class TxPreview(val src: String, val text: String, val lang: String?)

/** The message being replied to (reply-to-message / cross-channel quote). */
data class Quoted(
    val msgId: String?,
    val sender: String?,
    val text: String,
    val channel: String,
    val mediaUrl: String?,
    val mediaType: String?,
)

/** A file picked for sending, with its own caption (WhatsApp-style). */
data class PickedMedia(
    val id: String,
    val uri: Uri,
    val name: String,
    val mime: String,
    val size: Long,
    /** Set when the image was re-encoded to fit the 5 MB cap. */
    val bytes: ByteArray? = null,
    val caption: String = "",
) {
    val isImage: Boolean get() = mime.startsWith("image/")
    override fun equals(other: Any?) = other is PickedMedia && other.id == id && other.caption == caption
    override fun hashCode() = id.hashCode() * 31 + caption.hashCode()
}

/** One PERSON in the list: the newest thread plus their other channels. */
data class RowGroup(
    val key: String,
    val rep: Conversation,
    val siblings: List<Conversation>,
    val unread: Int,
    val lastAt: String?,
)

/** A photo in an album / the viewer. */
data class AlbumItem(val src: String, val caption: String?)

/** A full-screen viewer request (image lightbox, video player, album). */
sealed interface Viewer {
    data class Image(val url: String) : Viewer
    data class Video(val url: String, val messageId: String? = null) : Viewer
    data class Album(val items: List<AlbumItem>, val start: Int) : Viewer
}

internal const val PAGE = 50
internal const val THREAD_PAGE = 50
internal const val SNAP_KEY = "inbox_v2"

internal fun filterKeyOf(f: InboxQuery): String =
    listOf(f.tab, f.channel, f.mode, f.tag ?: "", f.q.trim()).joinToString("\u0001")

internal val DEFAULT_KEY = filterKeyOf(InboxQuery())

/** mapConversation(): external_id falls back to wa_id, last_message_at to created_at. */
internal fun Conversation.normalized(): Conversation =
    copy(externalId = externalId ?: waId, lastMessageAt = lastMessageAt ?: createdAt)

/**
 * Union two thread slices by id, newest state winning, ordered by time — a
 * poll refresh never throws away older pages already loaded, and an older
 * page slots in without duplicating anything.
 */
internal fun mergeThread(existing: List<ThreadMsg>, incoming: List<ThreadMsg>): List<ThreadMsg> {
    val byId = LinkedHashMap<String, ThreadMsg>()
    existing.forEach { byId[it.id] = it }
    incoming.forEach { byId[it.id] = it }
    return byId.values.sortedWith(compareBy({ it.millis }, { it.createdAt ?: "" }))
}

/**
 * mergeThread for a SERVER page: bubbles this device invented (optimistic
 * sends, socket echoes that carried no id, live system pills) are dropped once
 * the server's own row for them has arrived — otherwise every sent message
 * would show twice after the next poll.
 */
internal fun mergeServer(existing: List<ThreadMsg>, incoming: List<ThreadMsg>): List<ThreadMsg> {
    val kept = existing.filter { m ->
        when {
            m.id.startsWith("optimistic-") || m.id.startsWith("ws-") -> incoming.none { s ->
                !s.isSystem && s.direction == m.direction && s.isNote == m.isNote &&
                    s.body.trim() == m.body.trim() &&
                    (s.mediaUrl == null || m.mediaUrl == null || s.mediaUrl == m.mediaUrl) &&
                    kotlin.math.abs(s.millis - m.millis) < 10 * 60_000
            }
            m.id.startsWith("live-evt-") -> incoming.none { s ->
                s.isSystem && s.eventKind == m.eventKind && s.millis >= m.millis - 60_000
            }
            else -> true
        }
    }
    return mergeThread(kept, incoming)
}

/**
 * A live `new_message` frame → a thread bubble (ConversationsView's socket
 * handler). What the server publishes varies by path: the AI reply
 * (n8n_bridge) carries an `id`; the human reply / approve / media paths
 * (services/conversation.py) carry no id, direction or created_at; the
 * INBOUND paths (the WhatsApp webhook, meta_webhook, sms, public forms)
 * carry `sender: "user"` but no `direction` at all. The web defaults a
 * missing direction to "outbound", which paints the customer's own words as
 * an outgoing bubble until the next poll — here it follows the sender.
 * Agent-level notification frames (`event: "notification"`, e.g. the SMS
 * bridge's `type: "new_message"` ping on agents:all) are not messages.
 */
internal fun wsMessageOf(e: JsonObject): ThreadMsg? {
    if (e.s("event") == "notification") return null
    val sender = e.s("sender") ?: "ai"
    return ThreadMsg(
        id = e.s("id") ?: "ws-${java.util.UUID.randomUUID()}",
        type = "message",
        direction = e.s("direction") ?: if (sender == "user") "inbound" else "outbound",
        sender = sender,
        text = e.s("text"),
        createdAt = e.s("created_at") ?: nowIso(),
        mediaType = e.s("mediaType"),
        mediaId = e.s("mediaId"),
        mediaUrl = e.s("mediaUrl"),
        mediaCaption = e.s("mediaCaption"),
        mimeType = e.s("mimeType"),
        filename = e.s("filename"),
        // Sent-in-their-language replies carry the human's English.
        translation = e.s("translation"),
        translatedFrom = e.s("translatedFrom"),
        replyTo = (e["replyTo"] as? JsonObject)?.let { runCatching { NeemaJson.decodeFromJsonElement(QuotedRef.serializer(), it) }.getOrNull() },
    )
}

/**
 * Add a socket bubble unless the thread already shows it: the exact DB id;
 * an audio/media echo within 15 s (the web's guard); our own reply echoing
 * while its optimistic bubble is up; or — frames from the reply/approve/media
 * paths carry no id — an OUTBOUND echo of a row the after-send refetch
 * already brought in (same sender and text, within two minutes). A
 * customer's repeated "ok" is never swallowed: inbound frames only dedupe by id.
 */
internal fun appendWs(existing: List<ThreadMsg>, msg: ThreadMsg): List<ThreadMsg> = when {
    existing.any { it.id == msg.id } -> existing
    msg.mediaUrl != null && existing.any { x ->
        x.mediaUrl == msg.mediaUrl && x.direction == msg.direction && kotlin.math.abs(x.millis - msg.millis) < 15_000
    } -> existing
    msg.sender == "human_agent" && existing.any { x ->
        x.id.startsWith("optimistic-") && !x.isNote && x.body.trim() == msg.body.trim()
    } -> existing
    msg.id.startsWith("ws-") && !msg.inbound && existing.any { x ->
        !x.isLocal && !x.isSystem && !x.isNote && !x.inbound && x.sender == msg.sender &&
            x.body.trim() == msg.body.trim() && kotlin.math.abs(x.millis - msg.millis) < 120_000
    } -> existing
    else -> existing + msg
}

/**
 * What to tell the agent when one upload fails (admin.py upload_media):
 * the server's own `detail` when it sent one ("Image too large — max 5 MB.",
 * "Unsupported media type: …", "Couldn't convert this video for WhatsApp…"),
 * never a proxy's HTML error page or a pydantic error list.
 */
internal fun uploadErrorOf(e: Throwable): String {
    val api = e as? ke.co.bethanyhouse.neema.core.net.ApiException ?: return e.message?.ifBlank { null } ?: "failed"
    val d = api.detail.trim()
    // A pydantic 422 list names form fields ("Field required") — not something a
    // person uploading a photo can act on, so it gets the plain wording below.
    val validationList = Regex("\"detail\"\\s*:\\s*\\[").containsMatchIn(api.body)
    val readable = d.isNotEmpty() && !validationList && !d.startsWith("<") && !d.startsWith("[") && !d.startsWith("{")
    return when {
        readable && api.status != 0 -> d
        api.status == 413 -> "too large to upload"
        api.status == 415 -> "unsupported file type"
        api.status == 422 -> "the server couldn't process this file"
        api.status == 0 -> if (d.contains("timed out")) "upload timed out — check your connection and try again" else "network error — try again"
        else -> "upload failed (${api.status})"
    }
}

/** upload-media's ALLOWED_MIME (admin.py) — anything else is refused with a 415. */
internal val UPLOAD_MIME = setOf(
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "video/mp4", "video/3gpp", "video/quicktime", "video/hevc", "video/x-m4v",
    "audio/ogg", "audio/aac", "audio/mpeg",
)

/**
 * Whether upload-media will take this file. The server trusts a `.mov` /
 * `.hevc` / `.mp4` / `.m4v` extension when the type arrives as
 * octet-stream (iPhone clips), so those pass too.
 */
internal fun uploadable(mime: String, name: String): Boolean =
    mime in UPLOAD_MIME ||
        ((mime.isEmpty() || mime == "application/octet-stream") &&
            name.substringAfterLast('.', "").lowercase() in setOf("mov", "hevc", "mp4", "m4v"))

/** buildSystemEventFromWs (lib/websocket.tsx): a live divider pill from `intercept_changed`. */
internal fun systemEventFromWs(e: JsonObject): ThreadMsg? {
    val kind = e.s("eventKind") ?: return null
    val agent = e.s("eventAgentName")
    val note = e.s("eventNote")
    val label = when (kind) {
        "escalated" -> "Escalated — needs human"
        "flag" -> "Flagged: Needs Attention"
        "intercept" -> if (agent != null) "Picked up by $agent" else "Picked up by agent"
        "release" -> if (agent != null) "Released to AI by $agent" else "Released to AI"
        "transfer" -> if (note != null) "Transferred — $note" else "Transferred"
        "pause" -> if (agent != null) "Paused by $agent — replies held" else "Paused — replies held"
        "approve_draft" -> "AI draft approved"
        else -> kind
    }
    return ThreadMsg(
        id = "live-evt-${AppClock.now()}",
        type = "system_event", direction = "outbound", sender = "ai",
        text = label, createdAt = nowIso(),
        eventKind = kind, eventReason = e.s("eventReason"), agentName = agent,
    )
}

internal fun nowIso(): String = AppClock.instant().toString()

/** Null-safe string read that also treats JSON null as absent. */
internal fun JsonObject.s(key: String): String? =
    this[key]?.let { runCatching { it.jsonPrimitive.contentOrNull }.getOrNull() }?.takeIf { it.isNotEmpty() }

internal fun JsonObject.b(key: String): Boolean? =
    this[key]?.let { runCatching { it.jsonPrimitive.booleanOrNull }.getOrNull() }

/** Streams a picked file into a multipart part — a 150 MB clip never sits in memory. */
private class UriBody(
    private val cr: ContentResolver,
    private val uri: Uri,
    private val type: MediaType?,
    private val length: Long,
) : RequestBody() {
    override fun contentType() = type
    override fun contentLength() = if (length > 0) length else -1
    override fun writeTo(sink: BufferedSink) {
        val input = cr.openInputStream(uri) ?: throw java.io.IOException("Can't read the file")
        input.source().use { sink.writeAll(it) }
    }
}

/**
 * Calls the inbox makes beyond NeemaApi's typed ones: the thread in the
 * inbox's own wire shape, a reply that can answer 200 {ok:false}, and a
 * streaming media upload.
 */
class InboxApi(private val http: NeemaHttp) {
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    /**
     * GET /admin/conversations/{id}/messages?limit=&before= (admin.py get_thread):
     * a bare array, oldest first. Decoded item by item — one malformed row
     * (a hand-edited JSONB blob, a future field shape) drops out instead of
     * blanking the whole thread.
     */
    suspend fun messages(id: String, before: String? = null, limit: Int = THREAD_PAGE): List<ThreadMsg> {
        val qs = buildString {
            append("?limit=").append(limit)
            if (before != null) append("&before=").append(enc(before))
        }
        val arr = when (val el = parse(http.raw("GET", "/admin/conversations/$id/messages$qs"))) {
            is JsonArray -> el
            is JsonNull -> JsonArray(emptyList())
            // Not a thread at all: an error, never "No messages yet".
            else -> throw IllegalStateException("Unreadable thread")
        }
        return arr.mapNotNull { item ->
            runCatching { NeemaJson.decodeFromJsonElement(ThreadMsg.serializer(), item) }.getOrNull()
        }
    }

    /**
     * One inbox page (admin.py list_conversations with `limit`):
     * {items, next_cursor}. An API older than this client answers the legacy
     * bare array — taken as one final page, as the web does.
     */
    suspend fun page(q: InboxQuery, limit: Int, cursor: String? = null): ConversationPage {
        val params = listOfNotNull(
            "limit" to limit.toString(),
            cursor?.let { "cursor" to it },
            q.tab.takeIf { it != "all" }?.let { "tab" to it },
            q.channel.takeIf { it != "all" }?.let { "channel" to it },
            q.mode.takeIf { it != "all" }?.let { "mode" to it },
            q.tag?.takeIf { it.isNotEmpty() }?.let { "tag" to it },
            q.q.trim().ifEmpty { null }?.let { "q" to it },
        ).joinToString("&") { (k, v) -> "$k=${enc(v)}" }
        val el = parse(http.raw("GET", "/admin/conversations?$params"))
        if (el is JsonArray) return ConversationPage(conversationsOf(el), null)
        val obj = el as? JsonObject ?: throw IllegalStateException("Unreadable inbox page")
        return ConversationPage(
            items = conversationsOf(obj["items"] as? JsonArray),
            nextCursor = obj.s("next_cursor"),
        )
    }

    /** GET /admin/conversations/{id} (admin.py get_conversation): one row, the list's shape. */
    suspend fun get(id: String): Conversation =
        conversationOf(parse(http.raw("GET", "/admin/conversations/$id")))
            ?: throw IllegalStateException("Unreadable conversation $id")

    /** GET /admin/conversations/{id}/activity (admin.py get_conversation_activity): {events: [...]}. */
    suspend fun activity(id: String): List<ActivityEvent> {
        val obj = parse(http.raw("GET", "/admin/conversations/$id/activity")) as? JsonObject ?: return emptyList()
        return (obj["events"] as? JsonArray).orEmpty().mapIndexedNotNull { i, e ->
            val o = e as? JsonObject ?: return@mapIndexedNotNull null
            val label = o.s("label") ?: return@mapIndexedNotNull null
            ActivityEvent(id = o.s("id") ?: "ev-$i", kind = o.s("kind") ?: "", label = label, detail = o.s("detail"), at = o.s("at"))
        }
    }

    /**
     * The conversation controls: POST /intercept, /release, /pause, /transfer.
     * The server answers {ok, mode, …} — not a conversation row — so the body
     * is not decoded (the web ignores it too); only the status code counts.
     */
    suspend fun intercept(id: String) { http.raw("POST", "/admin/conversations/$id/intercept", http.jsonBody(JsonObject(emptyMap()))) }
    suspend fun release(id: String) { http.raw("POST", "/admin/conversations/$id/release", http.jsonBody(JsonObject(emptyMap()))) }
    suspend fun pause(id: String) { http.raw("POST", "/admin/conversations/$id/pause", http.jsonBody(JsonObject(emptyMap()))) }
    suspend fun transfer(id: String, agentId: String) {
        http.raw("POST", "/admin/conversations/$id/transfer", http.jsonBody(buildJsonObject { put("agent_id", agentId) }))
    }

    /**
     * POST /reply. The server answers 200 {ok:false, error} when DELIVERY
     * failed (Graph refused, window closed, page token) — surfaced as a throw
     * so a failed send never vanishes silently.
     */
    suspend fun reply(id: String, text: String, replyTo: String?, originalText: String?, originalLang: String?) {
        val body = buildJsonObject {
            put("text", text)
            if (replyTo != null) put("reply_to", replyTo)
            if (originalText != null) put("original_text", originalText)
            if (originalLang != null) put("original_lang", originalLang)
        }
        val res = http.raw("POST", "/admin/conversations/$id/reply", http.jsonBody(body))
        val obj = runCatching { NeemaJson.parseToJsonElement(res) as? JsonObject }.getOrNull()
        if (obj != null && obj.b("ok") == false) {
            throw IllegalStateException(obj.s("error") ?: "Couldn't send the reply")
        }
    }

    /** Upload one picked file (streamed, or its re-encoded bytes) with its caption. */
    suspend fun upload(cr: ContentResolver, convId: String, item: PickedMedia): ThreadMsg {
        val type = item.mime.toMediaTypeOrNull()
        val part: RequestBody = item.bytes?.toRequestBody(type) ?: UriBody(cr, item.uri, type, item.size)
        val parts = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", item.name, part)
            .apply { if (item.caption.isNotBlank()) addFormDataPart("caption", item.caption.trim()) }
            .build()
        val res = http.raw("POST", "/admin/conversations/$convId/upload-media", parts, upload = true)
        return runCatching { NeemaJson.decodeFromString(ThreadMsg.serializer(), res) }.getOrNull()
            ?.let { if (it.id.isEmpty()) it.copy(id = "optimistic-up-${System.nanoTime()}") else it }
            ?: ThreadMsg(id = "optimistic-up-${System.nanoTime()}", direction = "outbound", sender = "human_agent",
                text = item.caption, createdAt = nowIso())
    }
}

/**
 * Web-chat visitors (apps/api/app/routers/web_chat.py) are keyed `web_<sha1 hex>`
 * on the default "whatsapp" channel. The web runs that key through
 * formatPhone(), which turns the hash's digits into a made-up phone number —
 * one an agent could dial or message by mistake. Say what they are instead;
 * everything else (the channel chip, the filters) stays as the web has it.
 */
internal fun isWebVisitor(waId: String?): Boolean = waId?.startsWith("web_") == true

internal fun inboxName(c: Conversation): String =
    if (isWebVisitor(c.waId) && c.name.isNullOrBlank()) "Website visitor" else Fmt.displayName(c.name, c.waId)

internal fun inboxHandle(c: Conversation): String =
    if (isWebVisitor(c.waId)) "Web chat" else Fmt.formatPhone(c.waId)

/** A real dialable number (7–15 digits) — never a web visitor's hash or a Meta PSID. */
internal fun phoneDigits(c: Conversation): String? =
    if (isWebVisitor(c.waId)) null else c.waId?.filter { it.isDigit() }?.takeIf { it.length in 7..15 }

private fun parse(text: String): JsonElement =
    if (text.isBlank()) JsonNull else runCatching { NeemaJson.parseToJsonElement(text) }.getOrDefault(JsonNull)

private fun conversationsOf(arr: JsonArray?): List<Conversation> = arr.orEmpty().mapNotNull(::conversationOf)

/**
 * One inbox row (admin.py _conversation_rows), decoded defensively: `tags`
 * is read straight off the customer's free-form JSONB state
 * (`state.get("tags", [])`), so it can be null, a bare string or hold
 * non-strings — the server's own summary query guards `jsonb_typeof = 'array'`
 * for exactly that reason. Normalised to a list of strings so one odd
 * customer can't blank the whole inbox; a row with no id is dropped.
 */
internal fun conversationOf(el: JsonElement): Conversation? {
    val o = el as? JsonObject ?: return null
    if (o.s("id") == null) return null
    val tags = when (val t = o["tags"]) {
        is JsonArray -> t.mapNotNull { p -> (p as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content?.takeIf { it.isNotBlank() } }
        is JsonNull -> emptyList()
        is JsonPrimitive -> listOf(t.content).filter { it.isNotBlank() }
        else -> emptyList()
    }
    val fixed = JsonObject(o + ("tags" to JsonArray(tags.map(::JsonPrimitive))))
    return runCatching { NeemaJson.decodeFromJsonElement(Conversation.serializer(), fixed) }.getOrNull()
}
