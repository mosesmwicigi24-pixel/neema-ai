package ke.co.bethanyhouse.neema.feature.leads

import ke.co.bethanyhouse.neema.core.model.OkResponse
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/** crm.py `_buying_rhythm` — how often this customer buys and whether they're overdue. */
@Serializable
data class BuyingRhythm(
    @SerialName("days_since_last") val daysSinceLast: Double? = null,
    @SerialName("avg_interval_days") val avgIntervalDays: Double? = null,
    @SerialName("cadence_label") val cadenceLabel: String? = null,
    val overdue: Boolean = false,
)

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
    /** 0–100; a Double on the wire-safe side (the server sums points). */
    @SerialName("lead_score") val leadScoreRaw: Double = 0.0,
    val tier: String? = null,
    @SerialName("tier_label") val tierLabel: String? = null,
    val tags: List<String> = emptyList(),
    val channels: List<String> = emptyList(),
    @SerialName("total_orders") val totalOrders: Int = 0,
    @SerialName("total_spent") val totalSpent: Double = 0.0,
    @SerialName("buying_rhythm") val buyingRhythm: BuyingRhythm? = null,
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
    val notes: String? = null,
) {
    val leadScore: Int get() = leadScoreRaw.toInt().coerceIn(0, 100)

    /** The handle shown and searched — wa_id, else the phone, else the id. */
    val handle: String get() = waId?.takeIf { it.isNotBlank() } ?: phone?.takeIf { it.isNotBlank() } ?: id
}

/** The leads routes the web reaches with bare fetch() (outside api.ts). */
class LeadsApi(private val http: NeemaHttp) {
    suspend fun list(stage: String? = null): List<Lead> =
        http.get("/admin/leads" + (stage?.let { "?stage=${java.net.URLEncoder.encode(it, "UTF-8")}" } ?: ""))

    /**
     * PATCH /admin/leads/{id} — any of `lead_stage` (locks the AI out of
     * re-staging), `tags`, `notes` (+ `notes_base`, the text the edit started
     * from, so the server's three-way merge keeps notes appended meanwhile).
     */
    suspend fun update(id: String, body: JsonObject): OkResponse =
        http.patch("/admin/leads/${java.net.URLEncoder.encode(id, "UTF-8")}", body)
}
