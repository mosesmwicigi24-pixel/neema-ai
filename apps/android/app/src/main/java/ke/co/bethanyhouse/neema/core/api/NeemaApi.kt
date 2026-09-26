package ke.co.bethanyhouse.neema.core.api

import ke.co.bethanyhouse.neema.core.model.*
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import android.content.ContentResolver
import android.net.Uri
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import okio.source
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.net.URLEncoder

// Form-encoding writes spaces as "+", which is wrong inside a path segment; %20 is right in both.
private fun enc(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")
private fun query(vararg pairs: Pair<String, String?>): String =
    pairs.filter { !it.second.isNullOrEmpty() }
        .joinToString("&") { "${it.first}=${enc(it.second!!)}" }
        .let { if (it.isEmpty()) "" else "?$it" }

/**
 * A binary part for multipart uploads (file picker / recorder output).
 *
 * Either bytes already in memory (a re-encoded photo), or — through [of] —
 * a file or content Uri that is STREAMED into the request as it is written,
 * so a 150 MB video or an hour-long call recording never sits whole in
 * memory. A streamed part re-opens its source on every write, so the one
 * retry [NeemaHttp] makes after a token refresh sends it again intact.
 */
class UploadFile private constructor(
    /** The in-memory content, or null for a streamed part. */
    val bytes: ByteArray?,
    val filename: String,
    val mimeType: String,
    /** Bytes that will be sent, or -1 when the source can't say in advance. */
    val length: Long,
    private val open: (() -> InputStream)?,
) {
    constructor(bytes: ByteArray, filename: String, mimeType: String) :
        this(bytes, filename, mimeType, bytes.size.toLong(), null)

    /** The multipart body for this part. */
    fun requestBody(): RequestBody {
        val type = mimeType.toMediaTypeOrNull()
        bytes?.let { return it.toRequestBody(type) }
        val source = open!!
        return object : RequestBody() {
            override fun contentType(): MediaType? = type
            override fun contentLength(): Long = length
            override fun writeTo(sink: BufferedSink) {
                source().source().use { sink.writeAll(it) }
            }
        }
    }

    companion object {
        /** Stream [file] from disk. */
        fun of(file: File, filename: String = file.name, mimeType: String): UploadFile =
            UploadFile(null, filename, mimeType, file.length(), { file.inputStream() })

        /** Stream a picked document (`content://…`) through the content resolver. */
        fun of(resolver: ContentResolver, uri: Uri, filename: String, mimeType: String, length: Long = -1): UploadFile =
            UploadFile(null, filename, mimeType, if (length > 0) length else -1, {
                resolver.openInputStream(uri) ?: throw IOException("Can't read the file")
            })
    }
}

/** The inbox's server-side filters. Mirrors GET /admin/conversations. */
data class InboxQuery(
    /** "all" | "unread" | "read" | "human" | "yours" */
    val tab: String = "all",
    val channel: String = "all",
    val mode: String = "all",
    val tag: String? = null,
    val q: String = "",
)

/**
 * Every endpoint the web dashboard calls (apps/web/src/lib/api.ts), grouped the
 * same way. Features may add their own calls on [http] for endpoints that the
 * web reaches outside api.ts (e.g. the CRM/leads routes).
 */
class NeemaApi(val http: NeemaHttp) {

    // ── Ask / answer via Neema ──────────────────────────────────────────────
    // Ask, answer and generate-draft run a whole AI turn server-side: give them
    // the long-lived client so a slow model is never reported as a failure.
    suspend fun askNeema(convId: String, question: String): AnswerResponse =
        http.decode(http.raw("POST", "/admin/conversations/$convId/ask", http.encode(buildJsonObject { put("question", question) }), upload = true))

    suspend fun answerViaNeema(convId: String, facts: String): SentResponse =
        http.decode(http.raw("POST", "/admin/conversations/$convId/answer", http.encode(buildJsonObject { put("facts", facts) }), upload = true))

    val conversations = Conversations()
    val deals = Deals()
    val actions = Actions()
    val settings = Settings()
    val agents = Agents()
    val catalog = CatalogApi()
    val orders = Orders()
    val stats = StatsApi()
    val calls = Calls()
    val profile = Profile()
    val roles = Roles()

    inner class Deals {
        suspend fun list(status: String = "open"): List<Deal> =
            http.get<DealsResponse>("/admin/deals?status=${enc(status)}").deals
        suspend fun patch(id: String, body: JsonObject): OkResponse = http.patch("/admin/deals/$id", body)
    }

    inner class Actions {
        suspend fun list(status: String = "pending"): List<PlannedAction> =
            http.get<ActionsResponse>("/admin/actions?status=${enc(status)}").actions
        /**
         * Approving runs the action server-side (sends the message, pushes the
         * order to the hub), which can outlast the 30 s ceiling: the long client.
         */
        suspend fun approve(id: String, draft: String? = null): OkResponse = http.decode(
            http.raw(
                "POST", "/admin/actions/$id/approve",
                http.encode(buildJsonObject { if (!draft.isNullOrEmpty()) put("draft", draft) }), upload = true,
            ),
        )
        suspend fun veto(id: String): OkResponse = http.post("/admin/actions/$id/veto", JsonObject(emptyMap()))
    }

    inner class Settings {
        suspend fun getDirectives(): DirectivesResponse = http.get("/admin/settings/directives")
        suspend fun putDirectives(directives: String): JsonObject =
            http.put("/admin/settings/directives", buildJsonObject { put("directives", directives) })
        suspend fun getPipelineStages(): List<String> = http.get<StagesResponse>("/admin/settings/pipeline-stages").stages
        suspend fun putPipelineStages(stages: List<String>): StagesResponse =
            http.put("/admin/settings/pipeline-stages", buildJsonObject { putJsonArray("stages") { stages.forEach { add(JsonPrimitive(it)) } } })
        suspend fun getTranslation(): TranslationSetting = http.get("/admin/settings/translation")
        suspend fun putTranslation(enabled: Boolean): JsonObject =
            http.put("/admin/settings/translation", buildJsonObject { put("enabled", enabled) })
        suspend fun getOffer(): OfferSetting = http.get("/admin/settings/offer")
        suspend fun putOffer(campaign: Campaign?): OfferPutResponse =
            http.put("/admin/settings/offer", buildJsonObject {
                put("campaign", campaign?.let { NeemaJson.encodeToJsonElement(Campaign.serializer(), it) } ?: JsonNull)
            })
    }

    inner class Conversations {
        /** Resolve a hub deep link (phone and/or order number) to a conversation id. */
        suspend fun resolve(key: String, ref: String? = null): String? =
            http.get<ResolveResponse>("/admin/conversations/resolve${query("key" to key, "ref" to ref)}").conversationId

        suspend fun list(mode: String? = null, status: String? = null): List<Conversation> =
            http.get("/admin/conversations${query("mode" to mode, "status" to status)}")

        suspend fun get(id: String): Conversation = http.get("/admin/conversations/$id")

        /** One page of the inbox — whole PEOPLE. Tolerates the legacy bare-array reply. */
        suspend fun page(q: InboxQuery, limit: Int, cursor: String? = null): ConversationPage {
            val qs = query(
                "limit" to limit.toString(),
                "cursor" to cursor,
                "tab" to q.tab.takeIf { it != "all" },
                "channel" to q.channel.takeIf { it != "all" },
                "mode" to q.mode.takeIf { it != "all" },
                "tag" to q.tag,
                "q" to q.q.trim().ifEmpty { null },
            )
            val el = http.get<JsonElement>("/admin/conversations$qs")
            return if (el is JsonArray) ConversationPage(NeemaJson.decodeFromJsonElement(el), null)
            else NeemaJson.decodeFromJsonElement(el)
        }

        suspend fun summary(): InboxSummary = http.get("/admin/conversations/summary")
        suspend fun activity(id: String): List<ActivityEvent> =
            http.get<ActivityResponse>("/admin/conversations/$id/activity").events

        /** One page of the merged message + system-event timeline (newest 50 by default). */
        suspend fun messages(id: String, before: String? = null, limit: Int? = null): List<Message> =
            http.get("/admin/conversations/$id/messages${query("before" to before, "limit" to limit?.toString())}")

        // These answer small envelopes ({ok, mode} / {ok, transferred_to}), not the
        // conversation row — decode loosely so a success is never read as a failure.
        suspend fun intercept(id: String): JsonObject = http.post("/admin/conversations/$id/intercept", JsonObject(emptyMap()))
        suspend fun release(id: String): JsonObject = http.post("/admin/conversations/$id/release", JsonObject(emptyMap()))
        suspend fun pause(id: String): JsonObject = http.post("/admin/conversations/$id/pause", JsonObject(emptyMap()))
        suspend fun transfer(id: String, agentId: String): JsonObject =
            http.post("/admin/conversations/$id/transfer", buildJsonObject { put("agent_id", agentId) })

        suspend fun sendReply(
            id: String, text: String, replyTo: String? = null,
            originalText: String? = null, originalLang: String? = null,
            clientMsgId: String? = null,
        ): Message = http.post("/admin/conversations/$id/reply", buildJsonObject {
            put("text", text)
            if (clientMsgId != null) put("client_msg_id", clientMsgId)
            if (replyTo != null) put("reply_to", replyTo)
            if (originalText != null) put("original_text", originalText)
            if (originalLang != null) put("original_lang", originalLang)
        })

        /** Reply-box translate toggle: English in, the customer's language out. */
        suspend fun translateReply(id: String, text: String): TranslateResponse =
            http.post("/admin/conversations/$id/translate-reply", buildJsonObject { put("text", text) })

        suspend fun approveDraft(id: String, text: String? = null): OkResponse =
            http.post("/admin/conversations/$id/approve-draft", buildJsonObject { put("text", text?.let(::JsonPrimitive) ?: JsonNull) })
        suspend fun latestDraft(id: String): String? = http.get<DraftResponse>("/admin/conversations/$id/latest-draft").draft
        suspend fun generateDraft(id: String): String? =
            http.decode<DraftResponse>(http.raw("POST", "/admin/conversations/$id/generate-draft", http.encode(JsonObject(emptyMap())), upload = true)).draft
        suspend fun addNote(id: String, text: String): Message =
            http.post("/admin/conversations/$id/note", buildJsonObject { put("text", text) })

        /** Can a free-form reply go out right now? (Meta/WhatsApp 24h window.) */
        suspend fun window(id: String): ConversationWindow = http.get("/admin/conversations/$id/window")

        /** Re-fetch an expired Meta attachment from the source and re-host it. */
        suspend fun recoverMedia(messageId: String): RecoverMediaResponse =
            http.post("/admin/messages/$messageId/recover-media", JsonObject(emptyMap()))

        suspend fun close(id: String): OkResponse = http.post("/admin/conversations/$id/release", JsonObject(emptyMap()))
        suspend fun clearHistory(id: String): OkResponse = http.delete("/admin/conversations/$id/messages")

        /** A fresh direct video URL for a page reel/video post (source URLs expire). */
        suspend fun postVideo(postId: String, channel: String? = null): String =
            http.get<VideoUrlResponse>("/admin/post-video/${enc(postId)}${query("channel" to channel)}").videoUrl

        /** Upload a file from the device and send it to the customer. */
        suspend fun uploadMedia(convId: String, file: UploadFile, caption: String? = null): Message {
            val parts = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("file", file.filename, file.requestBody())
                .apply { if (!caption.isNullOrEmpty()) addFormDataPart("caption", caption) }
                .build()
            return http.multipart("/admin/conversations/$convId/upload-media", parts)
        }

        /** Send a media message by supplying an existing public URL. */
        suspend fun sendMediaUrl(convId: String, mediaUrl: String, mediaType: String, caption: String? = null, filename: String? = null): Message =
            http.post("/admin/conversations/$convId/reply-media", buildJsonObject {
                put("media_url", mediaUrl); put("media_type", mediaType)
                if (caption != null) put("caption", caption)
                if (filename != null) put("filename", filename)
            })
    }

    inner class Agents {
        suspend fun list(): List<Agent> = http.get("/admin/agents")
        suspend fun create(name: String, email: String, password: String, role: String? = null): JsonObject =
            http.post("/admin/agents", buildJsonObject {
                put("name", name); put("email", email); put("password", password)
                if (role != null) put("role", role)
            })
        /** The server answers `{"ok": true}`, not the agent row. */
        suspend fun update(id: String, body: JsonObject): OkResponse = http.patch("/admin/agents/$id", body)
        suspend fun delete(id: String): OkResponse = http.delete("/admin/agents/$id")
        suspend fun setAvailable(id: String, available: Boolean): OkResponse =
            http.patch("/admin/agents/$id", buildJsonObject { put("is_available", available) })
    }

    inner class CatalogApi {
        suspend fun list(category: String? = null, search: String? = null): List<CatalogItem> =
            http.get("/admin/catalog${query("category" to category, "search" to search)}")
        suspend fun create(p: CreateCatalogPayload): CatalogItem = http.post("/admin/catalog", p)
        suspend fun update(id: String, body: JsonObject): CatalogItem = http.patch("/admin/catalog/$id", body)
        suspend fun toggleStock(id: String, inStock: Boolean): CatalogItem =
            http.patch("/admin/catalog/$id", buildJsonObject { put("in_stock", inStock) })
        suspend fun delete(id: String) { http.raw("DELETE", "/admin/catalog/$id") }
        /** Where the hub's prices disagree with themselves. */
        suspend fun audit(): PriceAudit = http.get("/admin/catalog/audit")
    }

    inner class Orders {
        suspend fun list(status: String? = null, waId: String? = null): List<Order> =
            http.get("/admin/orders${query("status" to status, "wa_id" to waId)}")
        suspend fun get(id: String): Order = http.get("/admin/orders/$id")
        suspend fun updateStatus(id: String, status: String, paymentStatus: String? = null, fulfillmentStatus: String? = null): Order =
            http.patch("/admin/orders/$id", buildJsonObject {
                put("status", status)
                if (paymentStatus != null) put("payment_status", paymentStatus)
                if (fulfillmentStatus != null) put("fulfillment_status", fulfillmentStatus)
            })
    }

    inner class StatsApi {
        suspend fun overview(): Stats = http.get("/admin/stats")
    }

    /** Send the approved WhatsApp invite template to a customer's number. */
    suspend fun whatsappInvite(phone: String, name: String? = null): InviteResponse =
        http.post("/admin/whatsapp-invite", buildJsonObject { put("phone", phone); if (name != null) put("name", name) })

    inner class Calls {
        suspend fun list(): List<Call> = http.get("/admin/calls")
        suspend fun iceConfig(): IceConfig = http.get("/admin/calls/ice-config")
        suspend fun offer(callId: String): CallOffer = http.get("/admin/calls/${enc(callId)}/offer")
        suspend fun answer(callId: String, sdp: String): OkResponse =
            http.post("/admin/calls/${enc(callId)}/answer", buildJsonObject { put("sdp", sdp) })
        suspend fun terminate(callId: String): OkResponse = http.post("/admin/calls/${enc(callId)}/terminate", JsonObject(emptyMap()))
        suspend fun callback(callId: String): OkResponse = http.post("/admin/calls/${enc(callId)}/callback", JsonObject(emptyMap()))
        suspend fun connect(to: String, sdp: String, name: String? = null): ConnectResponse =
            http.post("/admin/calls/connect", buildJsonObject { put("to", to); put("sdp", sdp); if (name != null) put("name", name) })
        suspend fun requestPermission(to: String): OkResponse =
            http.post("/admin/calls/request-permission", buildJsonObject { put("to", to) })
        suspend fun transcript(callId: String): CallTranscript = http.get("/admin/calls/${enc(callId)}/transcript")
        suspend fun transcribe(callId: String): TranscribeResponse =
            http.post("/admin/calls/${enc(callId)}/transcribe", JsonObject(emptyMap()))
        /** Upload the recorded call audio (both sides mixed) on hangup — pass [UploadFile.of] a File to stream it. */
        suspend fun uploadRecording(callId: String, file: UploadFile): RecordingResponse {
            val parts = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("file", file.filename, file.requestBody())
                .build()
            return http.multipart("/admin/calls/${enc(callId)}/recording", parts)
        }
    }

    suspend fun attribution(): Attribution = http.get("/admin/attribution")

    inner class Profile {
        suspend fun me(): Agent = http.get("/admin/me")
        suspend fun update(name: String? = null, email: String? = null, password: String? = null): JsonObject =
            http.patch("/admin/me", buildJsonObject {
                if (name != null) put("name", name)
                if (email != null) put("email", email)
                if (password != null) put("password", password)
            })
    }

    inner class Roles {
        suspend fun list(): List<CustomRole> = http.get("/admin/roles")
        suspend fun create(id: String, name: String, description: String, color: String, permissions: List<String>): CustomRole =
            http.post("/admin/roles", buildJsonObject {
                put("id", id); put("name", name); put("description", description); put("color", color)
                putJsonArray("permissions") { permissions.forEach { add(JsonPrimitive(it)) } }
            })
        suspend fun update(id: String, body: JsonObject): CustomRole = http.patch("/admin/roles/$id", body)
        suspend fun delete(id: String): OkResponse = http.delete("/admin/roles/$id")
        suspend fun assignToAgent(agentId: String, roleId: String): RoleAssignResponse =
            http.patch("/admin/agents/$agentId/role", buildJsonObject { put("custom_role_id", roleId) })
    }
}
