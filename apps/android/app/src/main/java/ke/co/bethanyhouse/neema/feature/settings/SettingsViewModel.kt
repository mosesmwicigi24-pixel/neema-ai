package ke.co.bethanyhouse.neema.feature.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Campaign
import ke.co.bethanyhouse.neema.core.model.OfferSetting
import ke.co.bethanyhouse.neema.core.model.TranslationSetting
import ke.co.bethanyhouse.neema.core.net.ApiException
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

// ── Local-only sections (the web keeps these in component state, no API) ─────

data class BizSettings(
    val businessName: String = "Bethany House",
    val currency: String = "KES",
    val waNumber: String = "+254785490805",
    val openHours: String = "08:00–18:00",
    val timezone: String = "Africa/Nairobi",
)

data class AiSettings(
    val autoInterceptThreshold: String = "3",
    val draftApproval: Boolean = true,
    val responseDelayMs: String = "1500",
    val escalationKeywords: String = "refund, complaint, manager, urgent",
)

data class ConfigField(val label: String, val key: String, val secret: Boolean = false, val placeholder: String? = null)

data class Integration(
    val key: String,
    val name: String,
    val connected: Boolean,
    val description: String,
    val fields: List<ConfigField>,
)

val INTEGRATIONS = listOf(
    Integration("whatsapp", "WhatsApp Business API", true, "Primary messaging channel", listOf(
        ConfigField("Phone Number ID", "phone_id", placeholder = "752950797900067"),
        ConfigField("Access Token", "token", true, "EAAx…"),
        ConfigField("Webhook Secret", "secret", true, "your-secret"),
    )),
    Integration("messenger", "Facebook Messenger", true, "Meta messaging platform", listOf(
        ConfigField("Page ID", "page_id", placeholder = "123456789"),
        ConfigField("Access Token", "page_token", true, "EAAx…"),
    )),
    Integration("instagram", "Instagram DMs", true, "Instagram direct messages", listOf(
        ConfigField("Business Account ID", "ig_id", placeholder = "17841…"),
        ConfigField("Access Token", "ig_token", true, "EAAx…"),
    )),
    Integration("mpesa", "M-Pesa Daraja API", true, "Mobile payment processing", listOf(
        ConfigField("Consumer Key", "consumer_key", true),
        ConfigField("Consumer Secret", "consumer_secret", true),
        ConfigField("Paybill Number", "paybill", placeholder = "542542"),
        ConfigField("Account Number", "account", placeholder = "50036"),
    )),
    Integration("email", "Email (SMTP)", true, "Email channel integration", listOf(
        ConfigField("SMTP Host", "smtp_host", placeholder = "smtp.gmail.com"),
        ConfigField("SMTP Port", "smtp_port", placeholder = "587"),
        ConfigField("Username", "smtp_user", placeholder = "hello@bethanyhouse.co.ke"),
        ConfigField("Password", "smtp_pass", true),
    )),
    Integration("slack", "Slack Notifications", false, "Team alert channel", listOf(
        ConfigField("Webhook URL", "slack_url", placeholder = "https://hooks.slack.com/…"),
        ConfigField("Channel", "slack_channel", placeholder = "#neema-alerts"),
    )),
    Integration("sheets", "Google Sheets", false, "Data export and reporting", listOf(
        ConfigField("Sheet ID", "sheet_id", placeholder = "1BxiMVs0XRA5nFM…"),
        ConfigField("Service Account JSON", "gcp_json", true, "Paste service account JSON…"),
    )),
)

/** The pipeline's fixed stages, for the preview line (crm.py PIPELINE_CANONICAL). */
val CANONICAL_BEFORE = listOf("New", "Contacted", "Qualified", "Proposal")
const val PIPELINE_CUSTOM_MAX = 4
const val PIPELINE_LABEL_MAX = 18
/** crm.py PIPELINE_CANONICAL — the server silently drops a custom stage with one of these names. */
val PIPELINE_CANONICAL = setOf("new", "contacted", "qualified", "proposal", "negotiation", "won", "lost")

/** The Material date picker works in UTC midnight millis; offers store YYYY-MM-DD. */
fun isoDateToUtcMillis(iso: String?): Long? =
    iso?.let { runCatching { LocalDate.parse(it).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli() }.getOrNull() }

fun utcMillisToIsoDate(ms: Long): String = Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate().toString()

/** promotions.SCOPES */
val OFFER_SCOPES = setOf("all", "category", "products")

/**
 * What promotions.parse would refuse in [c] (set_campaign then answers 422),
 * in words that say which field to fix; null when the server will accept it.
 * The server keeps int(percent), so the percentage must be a whole number,
 * and a category / products offer needs at least one category / SKU.
 */
fun offerProblem(c: Campaign, maxPercent: Int): String? = when {
    c.name.isBlank() -> "Give the offer a name"
    c.percent != Math.floor(c.percent) || c.percent < 1 || c.percent > maxPercent -> "The discount must be a whole number from 1 to $maxPercent%"
    c.scope !in OFFER_SCOPES -> "Choose what the offer applies to"
    c.scope == "category" && c.categories.none { it.isNotBlank() } -> "Pick at least one category for the offer"
    c.scope == "products" && c.skus.none { it.isNotBlank() } -> "Pick at least one product for the offer"
    runCatching { LocalDate.parse(c.endsOn) }.isFailure -> "Pick the offer's last day"
    else -> null
}

/** The server's own checks on an offer (promotions.set_campaign). */
fun offerIsValid(c: Campaign, maxPercent: Int): Boolean = offerProblem(c, maxPercent) == null

/** The web's catch-all for a refused offer. */
const val OFFER_SAVE_FAILED = "Couldn't save that offer (admin only, and it needs a name, a percentage and an end date)"

/**
 * SettingsView.tsx. Four cards are live (standing orders, translation, the
 * offer, and the custom pipeline stages the web edits from the customer
 * panel); Business, AI, Integrations and Danger Zone are local-only on the
 * web too and behave the same here (they toast but persist nothing).
 */
class SettingsViewModel(private val dash: DashboardViewModel) : ViewModel() {
    private val api = dash.api.settings

    // Standing orders
    private val _directives = MutableStateFlow("")
    val directives: StateFlow<String> = _directives.asStateFlow()
    private val _maxChars = MutableStateFlow(600)
    val maxChars: StateFlow<Int> = _maxChars.asStateFlow()
    private val _directivesLoaded = MutableStateFlow(false)
    val directivesLoaded: StateFlow<Boolean> = _directivesLoaded.asStateFlow()
    private val _savingDirectives = MutableStateFlow(false)
    val savingDirectives: StateFlow<Boolean> = _savingDirectives.asStateFlow()

    // Translation
    private val _translation = MutableStateFlow<TranslationSetting?>(null)
    val translation: StateFlow<TranslationSetting?> = _translation.asStateFlow()
    private var savingTranslation = false

    // Offer
    private val _offer = MutableStateFlow<OfferSetting?>(null)
    val offer: StateFlow<OfferSetting?> = _offer.asStateFlow()
    private val _draft = MutableStateFlow(blankCampaign())
    val draft: StateFlow<Campaign> = _draft.asStateFlow()
    private val _savingOffer = MutableStateFlow(false)
    val savingOffer: StateFlow<Boolean> = _savingOffer.asStateFlow()

    // Pipeline stages
    private val _stages = MutableStateFlow<List<String>?>(null)
    val stages: StateFlow<List<String>?> = _stages.asStateFlow()
    private val _savingStages = MutableStateFlow(false)
    val savingStages: StateFlow<Boolean> = _savingStages.asStateFlow()

    // Local-only
    val biz = MutableStateFlow(BizSettings())
    val ai = MutableStateFlow(AiSettings())
    val integrations = MutableStateFlow(INTEGRATIONS)
    val integConfig = MutableStateFlow<Map<String, Map<String, String>>>(emptyMap())
    private val _savingBiz = MutableStateFlow(false)
    val savingBiz: StateFlow<Boolean> = _savingBiz.asStateFlow()
    private val _savingAi = MutableStateFlow(false)
    val savingAi: StateFlow<Boolean> = _savingAi.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    init { viewModelScope.launch { loadAll() } }

    private suspend fun loadAll() {
        // Each card loads on its own; one failing must not blank the others.
        val a = viewModelScope.async { loadDirectives() }
        val b = viewModelScope.async { runCatching { _translation.value = api.getTranslation() } }
        val c = viewModelScope.async { loadOffer() }
        val d = viewModelScope.async { runCatching { _stages.value = api.getPipelineStages() }.onFailure { if (_stages.value == null) _stages.value = emptyList() } }
        a.await(); b.await(); c.await(); d.await()
    }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            loadAll()
            _refreshing.value = false
        }
    }

    // ── Standing orders ───────────────────────────────────────────────────────

    private suspend fun loadDirectives() {
        try {
            val r = api.getDirectives()
            _directives.value = r.directives
            if (r.maxChars > 0) _maxChars.value = r.maxChars
        } catch (_: Exception) {
            // The web still unlocks the box so an admin can write fresh orders.
        }
        _directivesLoaded.value = true
    }

    fun setDirectives(v: String) { _directives.value = v.take(_maxChars.value) }

    fun saveDirectives() {
        if (_savingDirectives.value || !_directivesLoaded.value) return
        viewModelScope.launch {
            _savingDirectives.value = true
            try {
                val r = api.putDirectives(_directives.value)
                (r["directives"] as? JsonPrimitive)?.content?.let { _directives.value = it }
                dash.toast("Standing orders saved — Neema follows them within ~5 minutes")
            } catch (e: Exception) {
                // The API never refuses the text itself (it trims and cuts to max_chars); a
                // refusal is the admin check. A dropped connection says so instead.
                dash.toast(if ((e as? ApiException)?.status == 0) dash.errorText(e) else "Couldn't save (admin only)", ToastType.Error)
            } finally { _savingDirectives.value = false }
        }
    }

    // ── Translation ───────────────────────────────────────────────────────────

    fun toggleTranslation() {
        val state = _translation.value ?: return
        if (savingTranslation) return
        val next = !state.enabled
        _translation.value = state.copy(enabled = next)   // optimistic: the switch must feel instant
        savingTranslation = true
        viewModelScope.launch {
            try {
                api.putTranslation(next)
                dash.toast(
                    if (next) "Translation on — foreign messages get an English line from the next thread you open"
                    else "Translation off — no new translations will be bought. Ones already saved stay visible."
                )
            } catch (e: Exception) {
                _translation.update { it?.copy(enabled = !next) }   // put it back; nothing was saved
                dash.toast(if ((e as? ApiException)?.status == 0) dash.errorText(e) else "Couldn't change that (admin only)", ToastType.Error)
            } finally { savingTranslation = false }
        }
    }

    // ── Offer ─────────────────────────────────────────────────────────────────

    private suspend fun loadOffer() {
        try {
            val r = api.getOffer()
            _offer.value = r
            _draft.value = r.campaign ?: blankCampaign()
        } catch (_: Exception) {
            // Leave it loading rather than show a wrong state.
        }
    }

    /** "For 1 month" is the common case, so a new offer ends a month from today. */
    private fun blankCampaign() = Campaign(
        name = "", percent = 10.0, scope = "all", categories = emptyList(), skus = emptyList(),
        startsOn = null, endsOn = LocalDate.now().plusMonths(1).toString(),
    )

    fun editDraft(change: (Campaign) -> Campaign) { _draft.update(change) }

    /** [campaign] null ends the offer now. */
    fun saveOffer(campaign: Campaign?) {
        if (_savingOffer.value) return
        val max = _offer.value?.maxPercent?.toInt()?.takeIf { it > 0 } ?: 70
        // What the server would answer with a 422 — said without the round trip, and naming the field.
        campaign?.let { offerProblem(it, max) }?.let { return dash.toast(it, ToastType.Error) }
        viewModelScope.launch {
            _savingOffer.value = true
            try {
                val r = api.putOffer(campaign)
                _offer.update { it?.copy(campaign = r.campaign, running = r.running, says = r.says) }
                _draft.value = r.campaign ?: blankCampaign()
                val saved = r.campaign
                dash.toast(
                    when {
                        saved == null -> "Offer ended — Neema stops mentioning it from her next reply"
                        r.running && r.says.isNotBlank() -> "Offer live — Neema will say: ${r.says}"
                        // Saved but not live today: `says` is empty, so "Neema will say: " would promise nothing.
                        saved.startsOn?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.isAfter(LocalDate.now()) == true ->
                            "Offer saved — Neema starts mentioning it on ${ke.co.bethanyhouse.neema.core.util.Fmt.date(saved.startsOn)}"
                        else -> "Offer saved, but its last day has passed — Neema won't mention it"
                    }
                )
            } catch (e: Exception) {
                val ex = e as? ApiException
                dash.toast(
                    when (ex?.status) {
                        0 -> dash.errorText(e)
                        403 -> "Couldn't save that offer (admin only)"
                        // promotions.set_campaign's own reason ("a campaign needs a name, 1-70%, …").
                        422 -> "Couldn't save that offer — ${ex.detail}"
                        else -> OFFER_SAVE_FAILED
                    },
                    ToastType.Error,
                )
            } finally { _savingOffer.value = false }
        }
    }

    // ── Pipeline stages ───────────────────────────────────────────────────────

    fun addStage(label: String): Boolean {
        val l = label.trim().take(PIPELINE_LABEL_MAX).trim()
        if (l.isEmpty()) return false
        val cur = _stages.value ?: emptyList()
        if (l.lowercase() in PIPELINE_CANONICAL) {
            dash.toast("“$l” is already a built-in stage", ToastType.Warning); return false
        }
        if (cur.any { it.equals(l, ignoreCase = true) }) {
            dash.toast("“$l” is already a stage", ToastType.Warning); return false
        }
        if (cur.size >= PIPELINE_CUSTOM_MAX) {
            dash.toast("At most $PIPELINE_CUSTOM_MAX custom stages", ToastType.Error); return false
        }
        saveStages(cur + l)
        return true
    }

    fun removeStage(label: String) = saveStages((_stages.value ?: emptyList()) - label)

    private fun saveStages(next: List<String>) {
        if (_savingStages.value) return
        viewModelScope.launch {
            _savingStages.value = true
            try {
                // The server drops blanks, duplicates and the built-in names; show what it kept.
                _stages.value = api.putPipelineStages(next).stages
            } catch (e: Exception) {
                val status = (e as? ApiException)?.status
                dash.toast(
                    when (status) {
                        403 -> "Only an admin can change pipeline stages."
                        422 -> (e as ApiException).detail
                        else -> "Couldn't save pipeline stages."
                    },
                    ToastType.Error,
                )
            } finally { _savingStages.value = false }
        }
    }

    // ── Local-only sections ───────────────────────────────────────────────────

    fun saveBiz() {
        if (_savingBiz.value) return
        viewModelScope.launch {
            _savingBiz.value = true
            delay(600)
            _savingBiz.value = false
            dash.toast("Business settings saved")
        }
    }

    fun saveAi() {
        if (_savingAi.value) return
        viewModelScope.launch {
            _savingAi.value = true
            delay(600)
            _savingAi.value = false
            dash.toast("AI settings saved")
        }
    }

    fun toggleIntegration(key: String) {
        val integ = integrations.value.find { it.key == key } ?: return
        integrations.update { list -> list.map { if (it.key == key) it.copy(connected = !it.connected) else it } }
        dash.toast("${integ.name} ${if (integ.connected) "disconnected" else "connected"}")
    }

    fun setConfig(integ: String, field: String, value: String) {
        integConfig.update { it + (integ to ((it[integ] ?: emptyMap()) + (field to value))) }
    }

    fun saveIntegConfig(key: String) {
        dash.toast("${integrations.value.find { it.key == key }?.name} settings saved")
    }

    fun dangerAction() = dash.toast("Requires confirmation — coming soon", ToastType.Warning)
}
