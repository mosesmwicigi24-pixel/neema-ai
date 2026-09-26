package ke.co.bethanyhouse.neema.feature.settings

import ke.co.bethanyhouse.neema.core.util.AppClock

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Campaign
import ke.co.bethanyhouse.neema.core.model.OfferSetting
import ke.co.bethanyhouse.neema.core.model.TranslationSetting
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.agents.UNCERTAIN_SAVE
import ke.co.bethanyhouse.neema.feature.agents.refreshAfterForbidden
import ke.co.bethanyhouse.neema.feature.reports.BUSY_TEXT
import ke.co.bethanyhouse.neema.core.util.ScreenLife
import ke.co.bethanyhouse.neema.feature.reports.attempt
import ke.co.bethanyhouse.neema.feature.reports.friendlyError
import ke.co.bethanyhouse.neema.feature.reports.httpStatus
import ke.co.bethanyhouse.neema.feature.reports.mayHaveApplied
import ke.co.bethanyhouse.neema.feature.reports.readableDetail
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.coroutineScope
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
class SettingsViewModel(private val dash: DashboardViewModel) : ViewModel(), ke.co.bethanyhouse.neema.feature.reports.KeepsUiState {
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
    /** The "add a stage" box. Held here so a save on the wire when the phone turns still clears it. */
    val newStage = MutableStateFlow("")
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

    /**
     * Why a live card couldn't be read, by card ("directives", "translation",
     * "offer", "stages"). The web leaves such a card on "Loading…" forever
     * (or, for standing orders, unlocks an empty box whose save would wipe
     * the real ones); here the card says why and offers Retry.
     */
    private val _loadErrors = MutableStateFlow<Map<String, String>>(emptyMap())
    val loadErrors: StateFlow<Map<String, String>> = _loadErrors.asStateFlow()

    private fun loadFailed(card: String, e: Throwable) {
        _loadErrors.update { it + (card to friendlyError(e, fallback = "The server couldn't send this setting just now.")) }
    }
    private fun loaded(card: String) { _loadErrors.update { it - card } }

    /**
     * SettingsView reads its four live cards on mount. This ViewModel outlives
     * the screen, so each return to it re-reads them — except a card with
     * unsaved typing: the web's remount throws a half-written standing order
     * or offer away, here it is kept (pull-to-refresh still reloads all).
     */
    val life = ScreenLife(viewModelScope, dash.foreground, catchUpOnForeground = false, catchUp = ::reread)

    /** What the directives box / offer draft held when last loaded or saved: equal means nothing unsaved. */
    private var directivesBase: String? = null
    private var draftBase: Campaign? = null

    init { viewModelScope.launch { loadAll() } }

    private suspend fun reread() {
        coroutineScope {
            if (_directives.value == directivesBase) launch { loadDirectives() }
            launch { loadTranslation() }
            if (_draft.value == draftBase) launch { loadOffer() }
            launch { loadStages() }
        }
    }

    private suspend fun loadAll() {
        // Each card loads on its own; one failing must not blank the others.
        coroutineScope {
            launch { loadDirectives() }
            launch { loadTranslation() }
            launch { loadOffer() }
            launch { loadStages() }
        }
    }

    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            try { loadAll() } finally { _refreshing.value = false }
        }
    }

    private val retrying = mutableSetOf<String>()

    /** A card's Retry: reads that one card again (a second tap while it is on the wire does nothing). */
    fun retry(card: String) {
        if (!retrying.add(card)) return
        viewModelScope.launch {
            try {
                when (card) {
                    "directives" -> loadDirectives()
                    "translation" -> loadTranslation()
                    "offer" -> loadOffer()
                    "stages" -> loadStages()
                }
            } finally { retrying -= card }
        }
    }

    private suspend fun loadTranslation() {
        attempt { api.getTranslation() }
            .onSuccess { _translation.value = it; loaded("translation") }
            // A card already showing the switch keeps it; only an empty one says why.
            .onFailure { if (_translation.value == null) loadFailed("translation", it) }
    }

    private suspend fun loadStages() {
        attempt { api.getPipelineStages() }
            .onSuccess { _stages.value = it; loaded("stages") }
            // Never fall back to "no custom stages": adding one to that would
            // replace the real list with a single stage.
            .onFailure { if (_stages.value == null) loadFailed("stages", it) }
    }

    /**
     * What a save that failed says. [adminOnly] is the web's words for a 403;
     * a timeout never reaches here (the caller re-reads the truth first).
     */
    private fun saveFailure(e: Throwable, adminOnly: String, fallback: String): String {
        dash.refreshAfterForbidden(e)
        return when (e.httpStatus()) {
            403 -> adminOnly
            429 -> BUSY_TEXT
            422 -> (e as? ApiException)?.readableDetail() ?: fallback
            else -> friendlyError(e, fallback)
        }
    }

    // ── Standing orders ───────────────────────────────────────────────────────

    /**
     * Deliberate fix: the web unlocks the box even when this read fails, so an
     * admin on a dropped connection sees an empty box, and saving it would
     * wipe the standing orders Neema is following. Here the box stays locked
     * until the real text has arrived, and the card says why, with Retry.
     */
    private suspend fun loadDirectives() {
        try {
            val r = api.getDirectives()
            _directives.value = r.directives
            if (r.maxChars > 0) _maxChars.value = r.maxChars
            directivesBase = _directives.value
            // Typing the process lost when Android closed the app goes back in the box, unsaved.
            pendingDirectives?.let { pendingDirectives = null; _directives.value = it.take(_maxChars.value) }
            _directivesLoaded.value = true
            loaded("directives")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ke.co.bethanyhouse.neema.feature.reports.stillHere()
            // Already loaded once: the box keeps what it holds.
            if (!_directivesLoaded.value) loadFailed("directives", e)
        }
    }

    fun setDirectives(v: String) { _directives.value = v.take(_maxChars.value) }

    fun saveDirectives() {
        if (_savingDirectives.value || !_directivesLoaded.value) return
        _savingDirectives.value = true
        val text = _directives.value
        viewModelScope.launch {
            try {
                val r = api.putDirectives(text)
                (r["directives"] as? JsonPrimitive)?.content?.let { _directives.value = it }
                directivesBase = _directives.value
                dash.toast("Standing orders saved — Neema follows them within ~5 minutes")
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                ke.co.bethanyhouse.neema.feature.reports.stillHere()
                // No answer: read what the server holds now. If it is what was sent, it saved.
                val landed = e.mayHaveApplied() &&
                    attempt { api.getDirectives().directives.trim() == text.trim().take(_maxChars.value).trim() }.getOrDefault(false)
                if (landed) {
                    directivesBase = text
                    dash.toast("Standing orders saved — Neema follows them within ~5 minutes")
                } else dash.toast(
                    // The API never refuses the text itself (it trims and cuts to
                    // max_chars); a refusal is the admin check. The typed text stays.
                    if (e.mayHaveApplied()) UNCERTAIN_SAVE else saveFailure(e, "Couldn't save (admin only)", "Couldn't save the standing orders — try again."),
                    ToastType.Error,
                )
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
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                ke.co.bethanyhouse.neema.feature.reports.stillHere()
                if (e.mayHaveApplied()) {
                    // No answer: it may have switched. Show the server's setting, not a guess.
                    val truth = attempt { api.getTranslation() }.getOrNull()
                    if (truth != null) _translation.value = truth else _translation.update { it?.copy(enabled = !next) }
                    if (truth?.enabled != next) dash.toast("Couldn't reach the server — translation is still ${if (next) "off" else "on"}", ToastType.Error)
                } else {
                    _translation.update { it?.copy(enabled = !next) }   // put it back; nothing was saved
                    dash.toast(saveFailure(e, "Couldn't change that (admin only)", "Couldn't change that — try again."), ToastType.Error)
                }
            } finally { savingTranslation = false }
        }
    }

    // ── Offer ─────────────────────────────────────────────────────────────────

    private suspend fun loadOffer() {
        try {
            val r = api.getOffer()
            _offer.value = r
            _draft.value = r.campaign ?: blankCampaign()
            draftBase = _draft.value
            pendingDraft?.let { pendingDraft = null; _draft.value = it }
            loaded("offer")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ke.co.bethanyhouse.neema.feature.reports.stillHere()
            // Never show a wrong state: an unread card says why (with Retry); a
            // card already showing the offer keeps it.
            if (_offer.value == null) { draftBase = _draft.value; loadFailed("offer", e) }
        }
    }

    /** "For 1 month" is the common case, so a new offer ends a month from today. */
    private fun blankCampaign() = Campaign(
        name = "", percent = 10.0, scope = "all", categories = emptyList(), skus = emptyList(),
        startsOn = null, endsOn = AppClock.today().plusMonths(1).toString(),
    )

    fun editDraft(change: (Campaign) -> Campaign) { _draft.update(change) }

    /** [campaign] null ends the offer now. */
    fun saveOffer(campaign: Campaign?) {
        if (_savingOffer.value) return
        val max = _offer.value?.maxPercent?.toInt()?.takeIf { it > 0 } ?: 70
        // What the server would answer with a 422 — said without the round trip, and naming the field.
        campaign?.let { offerProblem(it, max) }?.let { return dash.toast(it, ToastType.Error) }
        _savingOffer.value = true
        viewModelScope.launch {
            try {
                val r = api.putOffer(campaign)
                offerSaved(r.campaign, r.running, r.says)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                ke.co.bethanyhouse.neema.feature.reports.stillHere()
                // No answer: read the offer back. If it is the one sent (or gone,
                // when ending it), the save landed; either way the card shows the truth.
                val now = if (e.mayHaveApplied()) attempt { api.getOffer() }.getOrNull() else null
                if (now != null && sameOffer(now.campaign, campaign)) {
                    _offer.value = now
                    offerSaved(now.campaign, now.running, now.says)
                    return@launch
                }
                val ex = e as? ApiException
                dash.refreshAfterForbidden(e)
                dash.toast(
                    when {
                        e.mayHaveApplied() -> UNCERTAIN_SAVE
                        ex?.status == 403 -> "Couldn't save that offer (admin only)"
                        // promotions.set_campaign's own reason ("a campaign needs a name, 1-70%, …").
                        ex?.status == 422 -> ex.readableDetail()?.let { "Couldn't save that offer — $it" } ?: OFFER_SAVE_FAILED
                        ex?.status == 0 || ex?.status == 401 || ex?.status == 429 || ex?.status in 502..504 -> friendlyError(e)
                        else -> OFFER_SAVE_FAILED
                    },
                    ToastType.Error,
                )
            } finally { _savingOffer.value = false }
        }
    }

    /** The server kept [saved]: the card, the draft and the toast follow it. */
    private fun offerSaved(saved: Campaign?, running: Boolean, says: String) {
        _offer.update { it?.copy(campaign = saved, running = running, says = says) }
        _draft.value = saved ?: blankCampaign()
        draftBase = _draft.value
        dash.toast(
            when {
                saved == null -> "Offer ended — Neema stops mentioning it from her next reply"
                running && says.isNotBlank() -> "Offer live — Neema will say: $says"
                // Saved but not live today: `says` is empty, so "Neema will say: " would promise nothing.
                saved.startsOn?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.isAfter(AppClock.today()) == true ->
                    "Offer saved — Neema starts mentioning it on ${ke.co.bethanyhouse.neema.core.util.Fmt.date(saved.startsOn)}"
                else -> "Offer saved, but its last day has passed — Neema won't mention it"
            }
        )
    }

    /** Whether the stored offer is the one [sent] (the server may tidy lists and whitespace). */
    private fun sameOffer(stored: Campaign?, sent: Campaign?): Boolean = when {
        sent == null -> stored == null
        stored == null -> false
        else -> stored.name.trim() == sent.name.trim() && stored.percent == sent.percent &&
            stored.scope == sent.scope && stored.endsOn == sent.endsOn &&
            stored.startsOn.orEmpty() == sent.startsOn.orEmpty() &&
            stored.categories.map { it.trim().lowercase() }.toSet() == sent.categories.filter { it.isNotBlank() }.map { it.trim().lowercase() }.toSet() &&
            stored.skus.map { it.trim().lowercase() }.toSet() == sent.skus.filter { it.isNotBlank() }.map { it.trim().lowercase() }.toSet()
    }

    // ── Pipeline stages ───────────────────────────────────────────────────────

    /**
     * Sends [label] as a new stage; answers whether it went. [onSaved] runs
     * once the server has kept it — the screen clears the typed label only
     * then, so a failed save leaves it in the box to try again.
     */
    fun addStage(label: String, onSaved: () -> Unit = {}): Boolean {
        val l = label.trim().take(PIPELINE_LABEL_MAX).trim()
        if (l.isEmpty()) return false
        // Not read yet: adding to "nothing" would replace the real list.
        val cur = _stages.value ?: return false
        if (_savingStages.value) return false
        if (l.lowercase() in PIPELINE_CANONICAL) {
            dash.toast("“$l” is already a built-in stage", ToastType.Warning); return false
        }
        if (cur.any { it.equals(l, ignoreCase = true) }) {
            dash.toast("“$l” is already a stage", ToastType.Warning); return false
        }
        if (cur.size >= PIPELINE_CUSTOM_MAX) {
            dash.toast("At most $PIPELINE_CUSTOM_MAX custom stages", ToastType.Error); return false
        }
        saveStages(cur + l, onSaved)
        return true
    }

    fun removeStage(label: String) { _stages.value?.let { saveStages(it - label) } }

    private fun saveStages(next: List<String>, onSaved: () -> Unit = {}) {
        if (_savingStages.value) return
        _savingStages.value = true
        viewModelScope.launch {
            try {
                // The server drops blanks, duplicates and the built-in names; show what it kept.
                _stages.value = api.putPipelineStages(next).stages
                onSaved()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                ke.co.bethanyhouse.neema.feature.reports.stillHere()
                // No answer: read the list back. The server's cleaning is
                // idempotent, so a list equal to what we sent (as it would keep it) means it saved.
                val now = if (e.mayHaveApplied()) attempt { api.getPipelineStages() }.getOrNull() else null
                if (now != null) _stages.value = now
                if (now != null && now.map { it.lowercase() } == cleanStages(next).map { it.lowercase() }) { onSaved(); return@launch }
                val status = e.httpStatus()
                dash.refreshAfterForbidden(e)
                dash.toast(
                    when {
                        e.mayHaveApplied() -> UNCERTAIN_SAVE
                        status == 403 -> "Only an admin can change pipeline stages."
                        status == 422 -> (e as? ApiException)?.readableDetail() ?: "Couldn't save pipeline stages."
                        status == 0 || status == 401 || status == 429 || status in 502..504 -> friendlyError(e)
                        else -> "Couldn't save pipeline stages."
                    },
                    ToastType.Error,
                )
            } finally { _savingStages.value = false }
        }
    }

    /** crm.py put_pipeline_stages's cleaning: trim, cut to 18, drop blanks, built-ins and repeats. */
    private fun cleanStages(list: List<String>): List<String> {
        val out = mutableListOf<String>()
        list.forEach { s ->
            val label = s.trim().take(PIPELINE_LABEL_MAX)
            if (label.isNotEmpty() && label.lowercase() !in PIPELINE_CANONICAL && out.none { it.equals(label, true) }) out += label
        }
        return out
    }

    // ── Process death ─────────────────────────────────────────────────────────

    /** Unsaved standing orders / offer from before Android restarted the app, put back once the card has loaded. */
    private var pendingDirectives: String? = null
    private var pendingDraft: Campaign? = null

    /**
     * What a restarted app gets back: unsaved typing in the standing orders
     * and the offer (only when it differs from what the server holds), the
     * stage being typed, and the local-only Business, AI and integration
     * fields — every integration field marked secret (tokens, keys,
     * passwords) excepted: those are never written to saved state.
     */
    override fun saveUi(): String = kotlinx.serialization.json.buildJsonObject {
        val j = ke.co.bethanyhouse.neema.core.net.NeemaJson
        val d = pendingDirectives ?: _directives.value.takeIf { directivesBase != null && it != directivesBase }
        d?.let { put("directives", JsonPrimitive(it)) }
        val o = pendingDraft ?: _draft.value.takeIf { draftBase != null && it != draftBase }
        o?.let { put("offer", j.encodeToJsonElement(Campaign.serializer(), it)) }
        if (newStage.value.isNotEmpty()) put("stage", JsonPrimitive(newStage.value))
        if (biz.value != BizSettings()) biz.value.let {
            put("biz", kotlinx.serialization.json.buildJsonArray {
                listOf(it.businessName, it.currency, it.waNumber, it.openHours, it.timezone).forEach { v -> add(JsonPrimitive(v)) }
            })
        }
        if (ai.value != AiSettings()) ai.value.let {
            put("ai", kotlinx.serialization.json.buildJsonArray {
                add(JsonPrimitive(it.autoInterceptThreshold)); add(JsonPrimitive(it.draftApproval))
                add(JsonPrimitive(it.responseDelayMs)); add(JsonPrimitive(it.escalationKeywords))
            })
        }
        val connected = integrations.value.filter { it.connected != (INTEGRATIONS.firstOrNull { d -> d.key == it.key }?.connected ?: it.connected) }
        if (connected.isNotEmpty()) put("toggled", kotlinx.serialization.json.buildJsonArray { connected.forEach { add(JsonPrimitive(it.key)) } })
        val plain = integConfig.value.mapValues { (k, fields) ->
            val secret = INTEGRATIONS.find { it.key == k }?.fields.orEmpty().filter { it.secret }.map { it.key }.toSet()
            fields.filterKeys { it !in secret }
        }.filterValues { it.isNotEmpty() }
        if (plain.isNotEmpty()) put("config", kotlinx.serialization.json.buildJsonObject {
            plain.forEach { (k, fields) -> put(k, kotlinx.serialization.json.buildJsonObject { fields.forEach { (f, v) -> put(f, JsonPrimitive(v)) } }) }
        })
    }.toString()

    override fun restoreUi(saved: String) {
        val o = runCatching { ke.co.bethanyhouse.neema.core.net.NeemaJson.parseToJsonElement(saved) as kotlinx.serialization.json.JsonObject }
            .getOrNull() ?: return
        fun str(e: kotlinx.serialization.json.JsonElement?) = (e as? JsonPrimitive)?.takeIf { it.isString }?.content
        str(o["directives"])?.let { d ->
            if (_directivesLoaded.value) _directives.value = d.take(_maxChars.value) else pendingDirectives = d
        }
        o["offer"]?.let { e -> runCatching { ke.co.bethanyhouse.neema.core.net.NeemaJson.decodeFromJsonElement(Campaign.serializer(), e) }.getOrNull() }
            ?.let { c -> if (_offer.value != null) _draft.value = c else pendingDraft = c }
        str(o["stage"])?.let { newStage.value = it }
        (o["biz"] as? kotlinx.serialization.json.JsonArray)?.mapNotNull { str(it) }?.takeIf { it.size == 5 }?.let {
            biz.value = BizSettings(it[0], it[1], it[2], it[3], it[4])
        }
        (o["ai"] as? kotlinx.serialization.json.JsonArray)?.takeIf { it.size == 4 }?.let {
            ai.value = AiSettings(str(it[0]).orEmpty(), (it[1] as? JsonPrimitive)?.content == "true", str(it[2]).orEmpty(), str(it[3]).orEmpty())
        }
        (o["toggled"] as? kotlinx.serialization.json.JsonArray)?.mapNotNull { str(it) }?.toSet()?.let { keys ->
            integrations.update { list -> list.map { if (it.key in keys) it.copy(connected = !it.connected) else it } }
        }
        (o["config"] as? kotlinx.serialization.json.JsonObject)?.let { cfg ->
            integConfig.value = cfg.mapValues { (_, v) ->
                (v as? kotlinx.serialization.json.JsonObject)?.mapNotNull { (f, x) -> str(x)?.let { f to it } }?.toMap().orEmpty()
            }
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
