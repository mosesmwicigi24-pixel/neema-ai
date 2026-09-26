package ke.co.bethanyhouse.neema.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.JsonTransformingSerializer
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

// Wire models: a 1:1 port of the interfaces in apps/web/src/lib/api.ts and
// apps/web/src/types/index.ts. Every field the web reads is here; unknown
// fields are ignored so a newer API never breaks an older app.

// ── Conversations ───────────────────────────────────────────────────────────

@Serializable
data class Conversation(
    val id: String,
    @SerialName("wa_id") val waId: String? = null,
    @SerialName("person_id") val personId: String? = null,
    @SerialName("external_id") val externalId: String? = null,
    /** "ai" | "human" | "paused" */
    @SerialName("intercept_mode") val interceptMode: String = "ai",
    @SerialName("lead_stage") val leadStage: String? = null,
    @SerialName("assigned_agent_id") val assignedAgentId: String? = null,
    @SerialName("assigned_agent_name") val assignedAgentName: String? = null,
    @SerialName("intercept_since") val interceptSince: String? = null,
    @SerialName("last_message_at") val lastMessageAt: String? = null,
    @SerialName("last_message_preview") val lastMessagePreview: String? = null,
    /** "open" | "closed" */
    val status: String = "open",
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    val name: String? = null,
    @SerialName("avatar_url") val avatarUrl: String? = null,
    /** Paid hub orders for this customer — the repeat-buyer badge. */
    @SerialName("orders_count") val ordersCount: Int = 0,
    val channel: String = "whatsapp",
    val unread: Int = 0,
    val country: String? = null,
    @SerialName("country_iso") val countryIso: String? = null,
    @SerialName("flag_url") val flagUrl: String? = null,
    // Read straight from customer JSONB: may be null, a bare string, or hold non-strings.
    @Serializable(with = LenientStringListSerializer::class)
    val tags: List<String> = emptyList(),
) {
    /** Channel-native handle: wa_id for WhatsApp, PSID/IGSID otherwise. */
    val handle: String get() = externalId ?: waId ?: ""
    /** Sort key: when did this thread last move. */
    val recency: String get() = lastMessageAt ?: createdAt ?: ""
}

@Serializable
data class ConversationPage(
    val items: List<Conversation> = emptyList(),
    @SerialName("next_cursor") val nextCursor: String? = null,
)

@Serializable
data class InboxSummary(
    val unread: Int = 0,
    val human: Int = 0,
    val yours: Int = 0,
    @SerialName("unread_messages") val unreadMessages: Map<String, Int> = emptyMap(),
    @Serializable(with = LenientStringListSerializer::class)
    val tags: List<String> = emptyList(),
)

@Serializable
data class CommentContext(
    @SerialName("post_id") val postId: String? = null,
    val title: String? = null,
    val permalink: String? = null,
    val thumb: String? = null,
    @SerialName("reply_to") val replyTo: String? = null,
)

@Serializable
data class ReplyTo(
    val id: String,
    val text: String? = null,
    val sender: String? = null,
    @SerialName("media_type") val mediaType: String? = null,
    @SerialName("media_url") val mediaUrl: String? = null,
)

/** One item of the merged thread: a chat message or an inline system event. */
@Serializable
data class Message(
    val id: String,
    /** "message" | "system_event" */
    val type: String = "message",
    /** "inbound" | "outbound" */
    val direction: String = "inbound",
    /** "user" | "ai" | "human_agent" */
    val sender: String = "user",
    val text: String = "",
    @SerialName("created_at") val createdAt: String = "",
    val isNote: Boolean = false,
    /** Team-facing English rendering of a foreign-language message. */
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
    @SerialName("comment_context") val commentContext: CommentContext? = null,
    @SerialName("reply_to") val replyTo: ReplyTo? = null,
    /** Local-only: an optimistic bubble not yet confirmed by the server. */
    val pending: Boolean = false,
    /** Local-only: the send failed. */
    val failed: Boolean = false,
) {
    val isSystemEvent: Boolean get() = type == "system_event"
    val isInbound: Boolean get() = direction == "inbound"
}

@Serializable
data class ActivityEvent(
    val id: String,
    val kind: String,
    val label: String,
    val detail: String? = null,
    val at: String? = null,
)

@Serializable
data class ConversationWindow(
    /** "open" | "human_agent" | "closed" | "n/a" */
    val mode: String = "n/a",
    val channel: String = "",
    @SerialName("last_inbound_at") val lastInboundAt: String? = null,
    @SerialName("expires_at") val expiresAt: String? = null,
    @SerialName("human_agent_until") val humanAgentUntil: String? = null,
    val reason: String? = null,
)

// ── Deals & planned actions ─────────────────────────────────────────────────

@Serializable
data class DealItem(val name: String? = null, val qty: Double? = null, val price: Double? = null)

@Serializable
data class NextAction(
    val kind: String? = null,
    val owner: String? = null,
    @SerialName("due_at") val dueAt: String? = null,
    val note: String? = null,
)

@Serializable
data class Deal(
    val id: String,
    @SerialName("conversation_id") val conversationId: String? = null,
    val customer: String = "",
    @SerialName("wa_id") val waId: String? = null,
    val channel: String? = null,
    val title: String? = null,
    val items: List<DealItem> = emptyList(),
    val stage: String = "",
    val blocking: String? = null,
    @SerialName("next_action") val nextAction: NextAction? = null,
    val guidance: String? = null,
    val status: String = "open",
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class PlannedAction(
    val id: String,
    @SerialName("deal_id") val dealId: String? = null,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("due_at") val dueAt: String? = null,
    val kind: String = "",
    val reason: String? = null,
    val draft: String? = null,
    val status: String = "pending",
    @SerialName("created_by") val createdBy: String = "",
)

// ── Settings ────────────────────────────────────────────────────────────────

@Serializable
data class Campaign(
    val name: String = "",
    val percent: Double = 0.0,
    /** "all" | "category" | "products" */
    val scope: String = "all",
    val categories: List<String> = emptyList(),
    val skus: List<String> = emptyList(),
    @SerialName("starts_on") val startsOn: String? = null,
    /** Inclusive last day, YYYY-MM-DD. */
    @SerialName("ends_on") val endsOn: String = "",
)

@Serializable
data class OfferSetting(
    val campaign: Campaign? = null,
    val running: Boolean = false,
    val says: String = "",
    @SerialName("max_percent") val maxPercent: Double = 0.0,
)

@Serializable
data class TranslationSetting(
    val enabled: Boolean = false,
    val default: Boolean = false,
    @SerialName("spend_30d_usd") val spend30dUsd: Double = 0.0,
    @SerialName("calls_30d") val calls30d: Int = 0,
)

// ── Agents & roles ──────────────────────────────────────────────────────────

@Serializable
data class Agent(
    val id: String,
    val name: String = "",
    val email: String = "",
    /** "admin" | "agent" | "readonly" | "supervisor" */
    val role: String = "agent",
    @SerialName("is_available") val isAvailable: Boolean = false,
    @SerialName("is_superuser") val isSuperuser: Boolean = false,
    @SerialName("active_convs") val activeConvs: Int = 0,
    @SerialName("avatar_url") val avatarUrl: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
    @SerialName("custom_role_id") val customRoleId: String? = null,
    @SerialName("custom_permissions") val customPermissions: List<String>? = null,
    @SerialName("role_name") val roleName: String? = null,
    @SerialName("role_color") val roleColor: String? = null,
    @SerialName("role_permissions") val rolePermissions: List<String>? = null,
) {
    /** mapAgent(): per-agent overrides, else the DB role's permissions. */
    val permissions: List<String> get() = customPermissions ?: rolePermissions ?: emptyList()
}

@Serializable
data class CustomRole(
    val id: String = "",
    val name: String = "",
    val description: String = "",
    val color: String = "#589b31",
    val permissions: List<String> = emptyList(),
    val protected: Boolean = false,
    @SerialName("created_at") val createdAt: String? = null,
)

// ── Catalog ─────────────────────────────────────────────────────────────────

@Serializable
data class CatalogVariant(
    @SerialName("variant_id") val variantId: Long? = null,
    val sku: String? = null,
    val name: String? = null,
    /** "<product> — <what tells it apart>" */
    val label: String? = null,
    @Serializable(with = VariantAttributesSerializer::class) val attributes: Map<String, String> = emptyMap(),
    @SerialName("price_kes") val priceKes: Double? = null,
    @SerialName("price_usd") val priceUsd: Double? = null,
)

@Serializable
data class CatalogItem(
    @SerialName("id") val rawId: String? = null,
    @SerialName("hub_product_id") val hubProductId: Long? = null,
    @SerialName("available_qty") val availableQty: Double? = null,
    val sku: String = "",
    val name: String = "",
    @Serializable(with = LenientStringListSerializer::class)
    val aliases: List<String> = emptyList(),
    val price: Double = 0.0,
    val unit: String? = null,
    @SerialName("category") val rawCategory: String? = null,
    val description: String? = null,
    @SerialName("in_stock") val inStock: Boolean = true,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("thumbnail_url") val thumbnailUrl: String? = null,
    @SerialName("price_kes") val priceKes: Double? = null,
    @SerialName("price_usd") val priceUsd: Double? = null,
    @SerialName("product_type") val productType: String? = null,
    val variants: List<CatalogVariant> = emptyList(),
    @SerialName("price_min_kes") val priceMinKes: Double? = null,
    @SerialName("price_max_kes") val priceMaxKes: Double? = null,
) {
    /** Hub rows have no local id — a stable synthetic one (mapCatalogItem). */
    val id: String get() = rawId ?: (hubProductId?.toString() ?: sku)
    val category: String get() = rawCategory ?: "General"
    /** Hub-sourced rows are read-only here: edit them in the hub. */
    val isHub: Boolean get() = rawId == null && hubProductId != null
}

@Serializable
data class CreateCatalogPayload(
    val sku: String,
    val name: String,
    val price: Double,
    val unit: String? = null,
    val category: String? = null,
    val description: String? = null,
    val aliases: List<String>? = null,
    @SerialName("in_stock") val inStock: Boolean? = null,
)

@Serializable
data class PriceGap(
    val name: String = "",
    val category: String? = null,
    val kes: Double = 0.0,
    val usd: Double = 0.0,
    @SerialName("usd_expected") val usdExpected: Double = 0.0,
    val factor: Double? = null,
)

@Serializable
data class PerPieceRow(val name: String = "", val category: String? = null, val kes: Double? = null)

@Serializable
data class PriceAudit(
    @SerialName("currency_gaps") val currencyGaps: List<PriceGap> = emptyList(),
    @SerialName("per_piece") val perPiece: List<PerPieceRow> = emptyList(),
    val checked: Int = 0,
    val rate: Double = 0.0,
)

// ── Orders ──────────────────────────────────────────────────────────────────

@Serializable
data class OrderItem(
    val name: String = "",
    val qty: Double = 0.0,
    /** Unit price. */
    val unit: Double = 0.0,
    /** Line total. */
    val total: Double = 0.0,
    val sku: String? = null,
)

/**
 * `order_events.items` is free-form JSONB, and two writers disagree on its
 * shape. Orders Neema places itself (agent/tools.py confirm_order → the cart
 * lines of agent/tools.py add_to_cart) store
 * `{hub_product_id, name, sku, qty, unit_price, price_usd, prices, …}` — no
 * `unit` and no `total`; the hub bridge (routers/hub_bridge.py, items:
 * list[Any]) stores whatever it is sent, historically `{name, qty, unit,
 * total}`. The web reads only `unit`/`total`, so every order Neema placed
 * showed a blank price. Here each line is normalised before decoding: the
 * unit price comes from `unit`, else `unit_price`, else `price`; the quantity
 * from `qty`, else `quantity`; the total from `total`, else qty × unit.
 * Anything that isn't an object is dropped rather than failing the list.
 */
object OrderItemsSerializer : JsonTransformingSerializer<List<OrderItem>>(ListSerializer(OrderItem.serializer())) {
    private val leadingNumber = Regex("^-?\\d+(?:\\.\\d+)?")
    // n8n rows can carry text quantities ("2 pcs"): read the leading number.
    private fun num(e: JsonElement?): Double? = (e as? JsonPrimitive)?.let { p ->
        if (p is JsonNull) null else p.content.trim().let { t -> t.toDoubleOrNull() ?: leadingNumber.find(t)?.value?.toDoubleOrNull() }
    }

    override fun transformDeserialize(element: JsonElement): JsonElement {
        val rows = element as? JsonArray ?: return JsonArray(emptyList())
        return JsonArray(rows.mapNotNull { row ->
            val o = row as? JsonObject ?: return@mapNotNull null
            val qty = num(o["qty"]) ?: num(o["quantity"]) ?: 0.0
            val unit = num(o["unit"]) ?: num(o["unit_price"]) ?: num(o["price"]) ?: 0.0
            val total = num(o["total"]) ?: (qty * unit)
            buildJsonObject {
                put("name", (o["name"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content ?: "")
                put("qty", qty); put("unit", unit); put("total", total)
                (o["sku"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content?.let { put("sku", it) }
            }
        })
    }
}

/**
 * A list of strings that tolerates what hand-edited JSONB really holds: null
 * (→ empty), a bare string (→ one item), and non-string entries (numbers are
 * kept as text, nulls and objects dropped). One odd row must never fail a list.
 */
object LenientStringListSerializer : JsonTransformingSerializer<List<String>>(ListSerializer(String.serializer())) {
    override fun transformDeserialize(element: JsonElement): JsonElement = when (element) {
        is JsonArray -> JsonArray(element.mapNotNull { e ->
            (e as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content?.takeIf { it.isNotBlank() }?.let(::JsonPrimitive)
        })
        is JsonPrimitive -> if (element is JsonNull || element.content.isBlank()) JsonArray(emptyList()) else JsonArray(listOf(JsonPrimitive(element.content)))
        else -> JsonArray(emptyList())
    }
}

/**
 * Variant attributes come from the hub as `{"Size": "S", "Colour": "Gold"}`,
 * but a PHP empty map arrives as `[]`, and a value can be a number or null.
 * Read them as strings, dropping nulls; anything but an object is no attributes.
 */
object VariantAttributesSerializer : JsonTransformingSerializer<Map<String, String>>(
    MapSerializer(String.serializer(), String.serializer()),
) {
    override fun transformDeserialize(element: JsonElement): JsonElement {
        val o = element as? JsonObject ?: return JsonObject(emptyMap())
        return JsonObject(o.mapNotNull { (k, v) ->
            val p = v as? JsonPrimitive ?: return@mapNotNull null
            if (p is JsonNull) null else k to JsonPrimitive(p.content)
        }.toMap())
    }
}

@Serializable
data class Order(
    val id: String,
    @SerialName("wa_id") val waId: String = "",
    @SerialName("session_id") val sessionId: String? = null,
    @SerialName("event_type") val eventType: String? = null,
    @Serializable(with = OrderItemsSerializer::class) val items: List<OrderItem> = emptyList(),
    val subtotal: Double = 0.0,
    val currency: String = "KES",
    /** Raw: "open" | "pending" | "confirmed" | "delivered" | "cancelled" */
    @SerialName("status") val rawStatus: String = "open",
    @SerialName("payment_status") val paymentStatus: String? = null,
    @SerialName("fulfillment_status") val fulfillmentStatus: String? = null,
    @SerialName("reply_text") val replyText: String? = null,
    val channel: String = "whatsapp",
    val state: JsonObject? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("contact_name") val contactName: String? = null,
    @SerialName("contact_phone") val contactPhone: String? = null,
    @SerialName("hub_order_id") val hubOrderId: Long? = null,
    @SerialName("hub_order_number") val hubOrderNumber: String? = null,
    @SerialName("hub_push_status") val hubPushStatus: String? = null,
    @SerialName("hub_last_error") val hubLastError: String? = null,
    @SerialName("hub_public_token") val hubPublicToken: String? = null,
    @SerialName("hub_public_url") val hubPublicUrl: String? = null,
    /** What the HUB says — distinct from [status], our own triage flag. */
    @SerialName("hub_status") val hubStatus: String? = null,
    @SerialName("hub_payment_status") val hubPaymentStatus: String? = null,
) {
    /** mapOrder(): "open" is a cart snapshot that was never an order → shown as pending. */
    val status: String get() = if (rawStatus == "open") "pending" else rawStatus
    val customerName: String get() = contactName ?: waId
    val total: Double get() = subtotal
}

// ── Stats, calls, attribution ───────────────────────────────────────────────

@Serializable
data class ChannelCount(val channel: String = "", val count: Int = 0, val open: Int = 0)

@Serializable
data class Stats(
    @SerialName("open_conversations") val openConversations: Int = 0,
    @SerialName("human_conversations") val humanConversations: Int = 0,
    @SerialName("ai_conversations") val aiConversations: Int = 0,
    @SerialName("active_agents") val activeAgents: Int = 0,
    @SerialName("total_agents") val totalAgents: Int = 0,
    @SerialName("total_revenue") val totalRevenue: Double = 0.0,
    @SerialName("total_orders") val totalOrders: Int = 0,
    @SerialName("pending_orders") val pendingOrders: Int = 0,
    @SerialName("delivered_orders") val deliveredOrders: Int = 0,
    @SerialName("confirmed_orders") val confirmedOrders: Int = 0,
    @SerialName("cancelled_orders") val cancelledOrders: Int = 0,
    @SerialName("in_stock_items") val inStockItems: Int = 0,
    @SerialName("total_items") val totalItems: Int = 0,
    @SerialName("channel_breakdown") val channelBreakdown: List<ChannelCount> = emptyList(),
)

@Serializable
data class Call(
    val id: String = "",
    @SerialName("call_id") val callId: String = "",
    @SerialName("wa_id") val waId: String? = null,
    val name: String? = null,
    val direction: String = "inbound",
    /** ringing | answered | ended | missed | declined */
    val status: String = "",
    val duration: Int? = null,
    @SerialName("agent_name") val agentName: String? = null,
    @SerialName("started_at") val startedAt: String? = null,
    val summary: String? = null,
    /** none | recorded | pending | processing | done | failed */
    @SerialName("transcript_status") val transcriptStatus: String? = null,
    @SerialName("has_recording") val hasRecording: Boolean = false,
)

@Serializable
data class CallTranscript(
    @SerialName("call_id") val callId: String = "",
    val status: String = "",
    val transcript: String? = null,
    val summary: String? = null,
    val language: String? = null,
    @SerialName("has_recording") val hasRecording: Boolean = false,
    @SerialName("recording_url") val recordingUrl: String? = null,
)

@Serializable
data class IceServer(
    val urls: JsonElement? = null,
    val username: String? = null,
    val credential: String? = null,
)

@Serializable
data class IceConfig(
    @SerialName("ice_servers") val iceServers: List<IceServer> = emptyList(),
    val record: Boolean? = null,
)

@Serializable
data class CallOffer(@SerialName("call_id") val callId: String = "", val sdp: String = "", val from: String = "")

@Serializable
data class AttributionRow(
    val source: String = "",
    val post: String? = null,
    @SerialName("post_title") val postTitle: String? = null,
    val leads: Int = 0,
    val orders: Int = 0,
    val revenue: Double = 0.0,
    @SerialName("paid_revenue") val paidRevenue: Double = 0.0,
)

@Serializable
data class Unattributed(val orders: Int = 0, val revenue: Double = 0.0, @SerialName("paid_revenue") val paidRevenue: Double = 0.0)

@Serializable
data class AttributionTotals(val leads: Int = 0, val orders: Int = 0, val revenue: Double = 0.0)

@Serializable
data class Attribution(
    val sources: List<AttributionRow> = emptyList(),
    val unattributed: Unattributed = Unattributed(),
    val totals: AttributionTotals = AttributionTotals(),
)

// ── Small response envelopes ────────────────────────────────────────────────

@Serializable data class OkResponse(val ok: Boolean = true)
@Serializable data class AnswerResponse(val answer: String = "")
@Serializable data class SentResponse(val ok: Boolean = true, val sent: String = "")
@Serializable data class DraftResponse(val draft: String? = null)
@Serializable data class TranslateResponse(val text: String = "", val lang: String? = null)
@Serializable data class ResolveResponse(@SerialName("conversation_id") val conversationId: String? = null)
@Serializable data class RecoverMediaResponse(
    val ok: Boolean = true,
    @SerialName("media_url") val mediaUrl: String = "",
    @SerialName("media_type") val mediaType: String? = null,
)
@Serializable data class VideoUrlResponse(@SerialName("video_url") val videoUrl: String = "")
@Serializable data class DealsResponse(val deals: List<Deal> = emptyList())
@Serializable data class ActionsResponse(val actions: List<PlannedAction> = emptyList())
@Serializable data class ActivityResponse(val events: List<ActivityEvent> = emptyList())
@Serializable data class DirectivesResponse(val directives: String = "", @SerialName("max_chars") val maxChars: Int = 0)
@Serializable data class StagesResponse(val stages: List<String> = emptyList())
@Serializable data class OfferPutResponse(val ok: Boolean = true, val campaign: Campaign? = null, val running: Boolean = false, val says: String = "")
@Serializable data class InviteResponse(val ok: Boolean = true, @SerialName("wa_id") val waId: String = "")
@Serializable data class ConnectResponse(val ok: Boolean = true, @SerialName("call_id") val callId: String = "")
@Serializable data class TranscribeResponse(val ok: Boolean = true, val status: String = "")
@Serializable data class RecordingResponse(val ok: Boolean = true, @SerialName("will_transcribe") val willTranscribe: Boolean? = null)
@Serializable data class RoleAssignResponse(val ok: Boolean = true, val permissions: List<String> = emptyList())
