package ke.co.bethanyhouse.neema.feature.conversations.customer

import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.feature.conversations.isWebVisitor
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.net.URLEncoder

// Wire models for the CRM panel (routers/crm.py `_build_profile`, the merge
// endpoints and the production-enquiry routes). The web types these loosely
// inside CustomerSidebar.tsx; field shapes here follow what the server sends.

@Serializable
data class CustomerChannel(
    val channel: String = "whatsapp",
    /** The conversation's wa_id — null for Messenger/IG/FB threads. */
    val identifier: String? = null,
    @SerialName("first_seen") val firstSeen: String? = null,
    @SerialName("last_seen") val lastSeen: String? = null,
    @SerialName("conversation_count") val conversationCount: Int = 0,
)

@Serializable
data class PanelOrderItem(
    val name: String = "",
    val qty: Double? = null,
    val quantity: Double? = null,
    val total: Double? = null,
)

/** An order as the panel renders it: hub-sourced (POS, web AND WhatsApp) or a local WhatsApp order_event. */
@Serializable
data class PanelOrder(
    val id: String = "",
    @SerialName("order_number") val orderNumber: String? = null,
    val status: String? = null,
    @SerialName("payment_status") val paymentStatus: String? = null,
    val total: Double? = null,
    val subtotal: Double? = null,
    @SerialName("currency_code") val currencyCode: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val items: List<PanelOrderItem> = emptyList(),
    /** "hub" | "whatsapp" */
    val source: String? = null,
) {
    /** `o.total || o.subtotal` — the web treats 0 as missing. */
    val amount: Double get() = total?.takeIf { it != 0.0 } ?: subtotal ?: 0.0
}

@Serializable
data class AdRef(
    val headline: String? = null,
    @SerialName("ad_id") val adId: String? = null,
    @SerialName("source_type") val sourceType: String? = null,
    @SerialName("source_id") val sourceId: String? = null,
    @SerialName("source_url") val sourceUrl: String? = null,
    val source: String? = null,
)

@Serializable
data class ScorePart(val label: String = "", val pts: Double = 0.0, val max: Double = 0.0)

@Serializable
data class BuyingRhythm(
    @SerialName("days_since_last") val daysSinceLast: Int? = null,
    @SerialName("avg_interval_days") val avgIntervalDays: Double? = null,
    @SerialName("cadence_label") val cadenceLabel: String? = null,
    val overdue: Boolean = false,
)

@Serializable
data class Parish(val id: String = "", val name: String? = null, val location: String? = null)

@Serializable
data class LinkedIdentity(
    val channel: String = "",
    @SerialName("external_id") val externalId: String = "",
    @SerialName("display_name") val displayName: String? = null,
    val source: String? = null,
    val confidence: String? = null,
)

/** GET /admin/customers/{id}?channel= — the full CRM profile. */
@Serializable
data class CustomerProfile(
    val id: String = "",
    @SerialName("wa_id") val waId: String? = null,
    val name: String? = null,
    @SerialName("name_confirmed") val nameConfirmed: Boolean = false,
    val email: String? = null,
    val phone: String? = null,
    val location: String? = null,
    val age: Int? = null,
    val tags: List<String> = emptyList(),
    @SerialName("lead_stage") val leadStage: String = "new",
    /** "auto" | "manual" */
    @SerialName("lead_stage_source") val leadStageSource: String? = null,
    @SerialName("suggested_lead_stage") val suggestedLeadStage: String? = null,
    @SerialName("lead_source") val leadSource: String? = null,
    @SerialName("ad_ref") val adRef: AdRef? = null,
    val role: String? = null,
    val organization: String? = null,
    val orders: List<PanelOrder>? = null,
    @SerialName("orders_source") val ordersSource: String? = null,
    @SerialName("hub_linked") val hubLinked: Boolean = false,
    @SerialName("hub_customer_id") val hubCustomerId: JsonElement? = null,
    @SerialName("hub_customer_name") val hubCustomerName: String? = null,
    @SerialName("lead_score") val leadScore: Double = 0.0,
    @SerialName("phone_verified") val phoneVerified: Boolean = false,
    @SerialName("cart_items") val cartItems: Int = 0,
    @SerialName("lead_score_breakdown") val leadScoreBreakdown: List<ScorePart> = emptyList(),
    val parish: Parish? = null,
    val channels: List<CustomerChannel> = emptyList(),
    @SerialName("merged_ids") val mergedIds: List<String> = emptyList(),
    @SerialName("person_id") val personId: String? = null,
    @SerialName("linked_identities") val linkedIdentities: List<LinkedIdentity> = emptyList(),
    @SerialName("total_orders") val totalOrders: Int = 0,
    @SerialName("total_spent") val totalSpent: Double = 0.0,
    @SerialName("avg_order_value") val avgOrderValue: Double? = null,
    /** prospect | new | regular | loyal | vip | at_risk */
    val tier: String? = null,
    @SerialName("tier_label") val tierLabel: String? = null,
    @SerialName("buying_rhythm") val buyingRhythm: BuyingRhythm? = null,
    @SerialName("last_order_at") val lastOrderAt: String? = null,
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
    @SerialName("first_seen_at") val firstSeenAt: String? = null,
    val notes: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("country_iso") val countryIso: String? = null,
    val country: String? = null,
    @SerialName("flag_url") val flagUrl: String? = null,
)

@Serializable
data class MergeSuggestion(
    @SerialName("merge_with") val mergeWith: String = "",
    val name: String? = null,
    val phone: String? = null,
    val country: String? = null,
    @SerialName("channel_hint") val channelHint: String? = null,
    val evidence: List<String> = emptyList(),
    /** "strong" | "possible" */
    val strength: String = "possible",
)

@Serializable
data class MergeSuggestionsResponse(val suggestions: List<MergeSuggestion> = emptyList())

/** A made-to-order request (measurement form) waiting to go to hub production. */
@Serializable
data class ProductionEnquiry(
    val id: String = "",
    @SerialName("product_name") val productName: String? = null,
    /** Values are whatever the form captured — usually strings, sometimes numbers. */
    val measurements: Map<String, JsonElement> = emptyMap(),
    val notes: String? = null,
    val location: String? = null,
    /** "new" | "pushed" | "declined" */
    val status: String = "new",
    @SerialName("hub_order_number") val hubOrderNumber: String? = null,
    val pushable: Boolean = false,
)

@Serializable
data class EnquiryResponse(val enquiry: ProductionEnquiry? = null)

@Serializable
data class PushResponse(@SerialName("hub_order_number") val hubOrderNumber: String? = null)

internal fun JsonElement.display(): String = (this as? JsonPrimitive)?.contentOrNull ?: toString()

/**
 * Dialable digits (7–15, E.164) of a phone — never a web-chat visitor's key.
 * Web visitors are keyed `web_<sha1 hex>` (routers/web_chat.py) and that hash
 * often holds 7–15 digits: the web reads them as a number and offers a Call,
 * a template and an Invite to a phone that does not exist. The server already
 * refuses to treat that key as a phone (core/phone.py is_plausible_phone).
 */
internal fun realPhoneDigits(raw: String?): String? =
    if (isWebVisitor(raw?.trim())) null else (raw ?: "").filter { it.isDigit() }.takeIf { it.length in 7..15 }

/**
 * A channel's display name. The web writes the raw key through CSS
 * `capitalize` in some places ("Whatsapp", "Sms") and CH_META's brand names
 * in others ("WhatsApp", "SMS"); the panel uses the brand names everywhere.
 * A web-chat visitor rides the default "whatsapp" channel but has no WhatsApp
 * thread at all, so their row says what it really is.
 */
internal fun channelLabel(channel: String, identifier: String? = null): String =
    if (isWebVisitor(identifier)) "Web chat" else chMeta(channel).first

/** The badge for a channel row: a web visitor gets the web badge, not WhatsApp's. */
internal fun badgeKey(channel: String, identifier: String?): String = if (isWebVisitor(identifier)) "web" else channel

/**
 * The CRM routes the web reaches through its own `crmReq` (not api.ts), so they
 * live here on top of the shared HTTP client.
 */
class CrmApi(private val http: NeemaHttp) {
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
    private fun ch(channel: String?) = if (channel.isNullOrEmpty()) "" else "?channel=${enc(channel)}"

    suspend fun profile(key: String, channel: String?): CustomerProfile =
        http.get("/admin/customers/${enc(key)}${ch(channel)}")

    suspend fun patch(key: String, channel: String?, body: JsonObject) {
        http.raw("PATCH", "/admin/customers/${enc(key)}${ch(channel)}", http.jsonBody(body))
    }

    suspend fun mergeSuggestions(key: String, channel: String?): List<MergeSuggestion> =
        http.get<MergeSuggestionsResponse>("/admin/customers/${enc(key)}/merge_suggestions${ch(channel)}").suggestions

    suspend fun merge(key: String, channel: String?, target: String) {
        http.raw("POST", "/admin/customers/${enc(key)}/merge${ch(channel)}",
            http.jsonBody(buildJsonObject { put("merge_with", target) }))
    }

    suspend fun unmerge(key: String, channel: String?, target: String) {
        http.raw("POST", "/admin/customers/${enc(key)}/unmerge${ch(channel)}",
            http.jsonBody(buildJsonObject { put("merge_with", target) }))
    }

    suspend fun enquiry(conversationId: String): ProductionEnquiry? =
        http.get<EnquiryResponse>("/admin/production/conversation/${enc(conversationId)}").enquiry

    suspend fun pushProduction(enquiryId: String): PushResponse =
        http.post("/admin/production/${enc(enquiryId)}/push", JsonObject(emptyMap()))

    suspend fun declineProduction(enquiryId: String) {
        http.raw("POST", "/admin/production/${enc(enquiryId)}/decline", http.jsonBody(JsonObject(emptyMap())))
    }
}
