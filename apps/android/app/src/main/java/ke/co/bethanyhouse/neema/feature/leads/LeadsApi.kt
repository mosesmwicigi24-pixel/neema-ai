package ke.co.bethanyhouse.neema.feature.leads

import ke.co.bethanyhouse.neema.core.model.OkResponse
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** crm.py `_buying_rhythm` — how often this customer buys and whether they're overdue. */
@Serializable
data class BuyingRhythm(
    @SerialName("days_since_last") val daysSinceLast: Double? = null,
    @SerialName("avg_interval_days") val avgIntervalDays: Double? = null,
    @SerialName("cadence_label") val cadenceLabel: String? = null,
    val overdue: Boolean = false,
)

/**
 * `tags` straight from `users.state["tags"]` (crm.py `list_leads`), which
 * PATCH /admin/leads and PATCH /admin/customers store verbatim — so a row can
 * hold a list, a lone string, null, or a list with a stray number. One odd row
 * must not fail the whole board: a string becomes its comma-separated tags,
 * primitives become their text, anything else is dropped.
 */
object LenientTagsSerializer : KSerializer<List<String>> {
    private val list = ListSerializer(String.serializer())
    override val descriptor: SerialDescriptor = list.descriptor
    override fun serialize(encoder: Encoder, value: List<String>) = list.serialize(encoder, value)
    override fun deserialize(decoder: Decoder): List<String> {
        val json = decoder as? JsonDecoder ?: return list.deserialize(decoder)
        return when (val el = json.decodeJsonElement()) {
            is JsonArray -> el.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p !is JsonNull }?.content?.trim()?.ifEmpty { null } }
            is JsonPrimitive -> if (el is JsonNull) emptyList() else parseTags(el.content)
            else -> emptyList()
        }
    }
}

/**
 * One row of GET /admin/leads (crm.py `list_leads`). The web's `Lead`
 * interface omits tier / buying_rhythm; the server sends them, so they're
 * modelled here. `id` is the internal User id — the PATCH key.
 */
@Serializable
data class Lead(
    val id: String,
    @SerialName("wa_id") val waId: String? = null,
    val name: String? = null,
    val phone: String? = null,
    val email: String? = null,
    val location: String? = null,
    @SerialName("lead_stage") val leadStage: String = "new",
    /** 0–100: crm.py `_compute_lead_score` sends an int; read as a Double so a float never fails the row. */
    @SerialName("lead_score") val leadScoreRaw: Double = 0.0,
    val tier: String? = null,
    @SerialName("tier_label") val tierLabel: String? = null,
    @Serializable(with = LenientTagsSerializer::class) val tags: List<String> = emptyList(),
    val channels: List<String> = emptyList(),
    @SerialName("total_orders") val totalOrders: Int = 0,
    /** `sum(float(o.subtotal))` — a float, or the int 0 when there are no orders. */
    @SerialName("total_spent") val totalSpent: Double = 0.0,
    @SerialName("buying_rhythm") val buyingRhythm: BuyingRhythm? = null,
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
    val notes: String? = null,
) {
    val leadScore: Int get() = leadScoreRaw.toInt().coerceIn(0, 100)

    /** The handle shown and searched — wa_id, else the phone, else the id. */
    val handle: String get() = waId?.takeIf { it.isNotBlank() } ?: phone?.takeIf { it.isNotBlank() } ?: id
}

/** lead_signals.py `normalise_stage`. */
fun normaliseStage(s: String?): String =
    (s?.ifEmpty { null } ?: "new").trim().lowercase().let { if (it == "negotiating") "negotiation" else it }

/** The leads routes the web reaches with bare fetch() (outside api.ts). */
class LeadsApi(private val http: NeemaHttp) {
    /**
     * GET /admin/leads — a bare array (crm.py `list_leads`), score-descending.
     * `stage` is compared with the row's `normalise_stage`d value (trimmed,
     * lower-cased, "negotiating" → "negotiation"), so it is sent normalised too:
     * a custom column's label ("Measuring") would otherwise match nothing.
     */
    suspend fun list(stage: String? = null): List<Lead> =
        http.get("/admin/leads" + (stage?.let { "?stage=${java.net.URLEncoder.encode(normaliseStage(it), "UTF-8")}" } ?: ""))

    /**
     * PATCH /admin/leads/{id} — any of `lead_stage` (locks the AI out of
     * re-staging), `tags`, `notes` (+ `notes_base`, the text the edit started
     * from, so the server's three-way merge keeps notes appended meanwhile).
     */
    suspend fun update(id: String, body: JsonObject): OkResponse =
        http.patch("/admin/leads/${java.net.URLEncoder.encode(id, "UTF-8")}", body)
}
