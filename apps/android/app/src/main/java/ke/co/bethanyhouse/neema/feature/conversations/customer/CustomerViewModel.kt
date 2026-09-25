package ke.co.bethanyhouse.neema.feature.conversations.customer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.conversations.isWebVisitor
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import java.net.URLEncoder

/** Operator-added pipeline stages (Settings-backed, global): fetched once per process, like the web's module cache. */
internal object StageCache {
    var stages: List<String>? = null
}

enum class CustomerTab(val label: String) { Profile("profile"), Insights("insights"), Activity("activity") }

/**
 * State and actions of the customer panel (components/ui/CustomerSidebar.tsx).
 * One per conversation: every edit PATCHes /admin/customers/{key}?channel=…,
 * keyed on the channel-native handle so Messenger/IG/FB contacts persist too.
 */
class CustomerViewModel(
    private val dash: DashboardViewModel,
    private var conversation: Conversation,
    /** Places the WhatsApp voice call (the web's callCtx.initiateCall); swappable for tests. */
    private val placeCall: suspend (to: String, name: String?) -> Result<Unit> =
        { to, name -> dash.container.calls.initiateCall(to, name) },
) : ViewModel() {
    private val crm = CrmApi(dash.api.http)

    /** wa_id for WhatsApp, else the PSID / IGSID (WhatsApp's wa_id IS its external_id). */
    private val custId: String = conversation.waId ?: conversation.externalId ?: ""
    private val channel: String? = conversation.channel.ifEmpty { null }

    private val _loading = MutableStateFlow(true)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _profile = MutableStateFlow<CustomerProfile?>(null)
    val profile: StateFlow<CustomerProfile?> = _profile.asStateFlow()

    /** Pull-to-refresh: reloading over an already-painted profile. */
    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving.asStateFlow()

    val tab = MutableStateFlow(CustomerTab.Profile)

    /** The web's stageEditorOpen / editNotes: open sub-editors, kept here so they survive recomposition. */
    val stageEditorOpen = MutableStateFlow(false)
    val editNotes = MutableStateFlow(false)

    private val _customStages = MutableStateFlow(StageCache.stages ?: emptyList())
    val customStages: StateFlow<List<String>> = _customStages.asStateFlow()

    private val _enquiry = MutableStateFlow<ProductionEnquiry?>(null)
    val enquiry: StateFlow<ProductionEnquiry?> = _enquiry.asStateFlow()
    private val _pushing = MutableStateFlow(false)
    val pushing: StateFlow<Boolean> = _pushing.asStateFlow()

    private val _showMerge = MutableStateFlow(false)
    val showMerge: StateFlow<Boolean> = _showMerge.asStateFlow()
    /** null = still scanning for duplicates. */
    private val _mergeSugs = MutableStateFlow<List<MergeSuggestion>?>(null)
    val mergeSugs: StateFlow<List<MergeSuggestion>?> = _mergeSugs.asStateFlow()
    private var mergeJob: Job? = null

    private val _templateBusy = MutableStateFlow(false)
    val templateBusy: StateFlow<Boolean> = _templateBusy.asStateFlow()

    init {
        load()
        loadEnquiry()
        if (StageCache.stages == null) {
            viewModelScope.launch {
                runCatching { dash.api.settings.getPipelineStages() }
                    .onSuccess { StageCache.stages = it; _customStages.value = it }
                    .onFailure { StageCache.stages = emptyList() }
            }
        }
    }

    /**
     * The web re-runs loadProfile whenever the thread's row changes (a new
     * message, a rename), so an AI-set stage or an appended call summary shows
     * up without reopening the panel. Same here, quietly over the painted profile.
     */
    fun sync(conv: Conversation) {
        val prev = conversation
        conversation = conv
        if (conv.id == prev.id && (conv.lastMessageAt != prev.lastMessageAt || conv.name != prev.name)) {
            load(showSpinner = false)
        }
    }

    /** The key edits persist against: the profile's own wa_id (a shim for non-WhatsApp contacts), else the handle. */
    private val key: String get() = _profile.value?.waId?.ifEmpty { null } ?: custId

    fun load(showSpinner: Boolean = _profile.value == null) {
        viewModelScope.launch {
            if (showSpinner) _loading.value = true else _refreshing.value = true
            try {
                _profile.value = crm.profile(custId, channel)
            } catch (_: Throwable) {
                // Fallback: a minimal profile from the conversation row, so the panel still works.
                if (_profile.value == null) _profile.value = fallbackProfile()
            } finally {
                _loading.value = false
                _refreshing.value = false
            }
        }
    }

    private fun fallbackProfile() = CustomerProfile(
        id = custId,
        waId = custId,
        name = conversation.name,
        // As the server does (crm.py phone_display): a web visitor's `web_<hash>` key is not a phone.
        phone = conversation.waId?.takeUnless { isWebVisitor(it) },
        leadStage = "new",
        channels = listOf(
            CustomerChannel(
                channel = conversation.channel.ifEmpty { "whatsapp" },
                identifier = conversation.waId,
                firstSeen = conversation.lastMessageAt,
                lastSeen = conversation.lastMessageAt,
                conversationCount = 1,
            ),
        ),
        lastSeenAt = conversation.lastMessageAt,
        firstSeenAt = conversation.lastMessageAt,
        createdAt = conversation.lastMessageAt,
        countryIso = conversation.countryIso,
        country = conversation.country,
        flagUrl = conversation.flagUrl,
    )

    /**
     * Optimistic PATCH: apply [local] at once, send [body], roll back on failure.
     * [onSaved] runs only after the server accepted it (the name → inbox hook).
     */
    fun patch(body: JsonObject, local: (CustomerProfile) -> CustomerProfile, onSaved: (() -> Unit)? = null) {
        val prev = _profile.value ?: return
        val k = key
        _saving.value = true
        _profile.value = local(prev)
        viewModelScope.launch {
            try {
                crm.patch(k, channel, body)
                dash.toast("Saved")
                onSaved?.invoke()
            } catch (_: Throwable) {
                dash.toast("Failed to save", ToastType.Error)
                _profile.value = prev
            } finally {
                _saving.value = false
            }
        }
    }

    fun saveName(v: String, onNameChange: (String, String) -> Unit) {
        val waId = _profile.value?.waId ?: custId
        patch(buildJsonObject { put("name", v) }, { it.copy(name = v) }) {
            if (v.isNotEmpty()) onNameChange(waId, v)
        }
    }

    fun saveField(field: String, v: String, local: (CustomerProfile) -> CustomerProfile) =
        patch(buildJsonObject { put(field, v) }, local)

    /** `parseInt(v) || null` — leading digits count ("35 yrs" → 35); unparseable or zero is sent as null (the server then leaves it). */
    fun saveAge(v: String) {
        val age = Regex("^\\s*([+-]?\\d+)").find(v)?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it != 0 }
        patch(buildJsonObject { if (age != null) put("age", age) else put("age", JsonNull) }, { it.copy(age = age) })
    }

    fun setStage(stage: String) = patch(
        buildJsonObject { put("lead_stage", stage) },
        // The server locks an operator-set stage as "manual"; mirror it so the AI hint clears.
        { it.copy(leadStage = stage, leadStageSource = "manual") },
    )

    fun addTag(tag: String) {
        val p = _profile.value ?: return
        val t = tag.trim()
        if (t.isEmpty()) return
        val next = p.tags + t
        patch(buildJsonObject { putJsonArray("tags") { next.forEach { add(JsonPrimitive(it)) } } }, { it.copy(tags = next) })
    }

    fun removeTag(tag: String) {
        val p = _profile.value ?: return
        val next = p.tags.filter { it != tag }
        patch(buildJsonObject { putJsonArray("tags") { next.forEach { add(JsonPrimitive(it)) } } }, { it.copy(tags = next) })
    }

    /** notes_base = the snapshot the edit started from, so the server MERGES rather than dropping a concurrent call summary. */
    fun saveNotes(draft: String) {
        val base = _profile.value?.notes ?: ""
        patch(buildJsonObject { put("notes", draft); put("notes_base", base) }, { it.copy(notes = draft) })
    }

    // ── Custom pipeline stages (admin-only on the server) ────────────────────

    fun saveCustomStages(stages: List<String>) {
        viewModelScope.launch {
            try {
                val r = dash.api.settings.putPipelineStages(stages)
                StageCache.stages = r.stages
                _customStages.value = r.stages
            } catch (e: Throwable) {
                val api = e as? ApiException
                dash.toast(
                    when {
                        api?.status == 403 -> "Only an admin can change pipeline stages."
                        // crm.py put_pipeline_stages: "At most 4 custom stages" — worth saying as is.
                        api?.status == 422 && api.detail.startsWith("At most") -> api.detail.trimEnd('.') + "."
                        else -> "Couldn't save pipeline stages."
                    },
                    ToastType.Error,
                )
            }
        }
    }

    // ── Merge / unmerge ──────────────────────────────────────────────────────

    fun toggleMerge(open: Boolean = !_showMerge.value) {
        _showMerge.value = open
        mergeJob?.cancel()
        _mergeSugs.value = null
        if (!open) return
        mergeJob = viewModelScope.launch {
            _mergeSugs.value = runCatching { crm.mergeSuggestions(key, channel) }.getOrElse { emptyList() }
        }
    }

    fun merge(target: String, onDone: () -> Unit = {}) {
        val t = target.trim()
        if (t.isEmpty()) return
        viewModelScope.launch {
            try {
                crm.merge(key, channel, t)
                dash.toast("Profiles merged successfully")
                toggleMerge(false)
                onDone()
                load(showSpinner = false)
            } catch (e: Throwable) {
                dash.toast(mergeError(e as? ApiException), ToastType.Error)
            }
        }
    }

    /**
     * crm.py merge_customers refuses a typed target it can't find (404 "Secondary
     * customer not found") and a profile merged into itself (422). The web says
     * "Failed to merge profiles" to both; the operator can act on the difference.
     */
    private fun mergeError(e: ApiException?): String = when {
        e?.status == 404 && e.detail.contains("Secondary", ignoreCase = true) ->
            "Failed to merge profiles — no customer found for that phone / wa_id"
        e?.status == 422 -> "Failed to merge profiles — that's this same profile"
        else -> "Failed to merge profiles"
    }

    fun unmerge(mergedId: String) {
        viewModelScope.launch {
            try {
                crm.unmerge(key, channel, mergedId)
                dash.toast("Unmerged")
                load(showSpinner = false)
            } catch (_: Throwable) {
                dash.toast("Failed to unmerge", ToastType.Error)
            }
        }
    }

    // ── Made-to-order enquiry ────────────────────────────────────────────────

    private fun loadEnquiry() {
        viewModelScope.launch {
            _enquiry.value = runCatching { crm.enquiry(conversation.id) }.getOrNull()
        }
    }

    fun pushProduction() {
        val e = _enquiry.value ?: return
        _pushing.value = true
        viewModelScope.launch {
            try {
                val r = crm.pushProduction(e.id)
                _enquiry.value = e.copy(status = "pushed", hubOrderNumber = r.hubOrderNumber)
                dash.toast(r.hubOrderNumber?.let { "Sent to production · $it" } ?: "Sent to production")
            } catch (ex: Throwable) {
                val api = ex as? ApiException
                // 422: the enquiry has no linked hub product (crm.py push_production) — its detail
                // tells the operator what to do instead. A hub failure (502) stays generic.
                dash.toast(
                    if (api?.status == 422 && api.detail.isNotBlank() && !api.detail.startsWith("[")) api.detail
                    else "Couldn't send to production",
                    ToastType.Error,
                )
            } finally {
                _pushing.value = false
            }
        }
    }

    fun declineProduction() {
        val e = _enquiry.value ?: return
        _enquiry.value = e.copy(status = "declined")
        viewModelScope.launch {
            try {
                crm.declineProduction(e.id)
            } catch (_: Throwable) {
                _enquiry.value = e
                dash.toast("Couldn't dismiss", ToastType.Error)
            }
        }
    }

    // ── Ask Neema / Answer via Neema ─────────────────────────────────────────

    /** Ask-Neema: read-only lookups (sizes, past orders, call context); nothing reaches the customer. */
    val askAnswer = MutableStateFlow<String?>(null)
    val askBusy = MutableStateFlow(false)

    fun ask(question: String) {
        val q = question.trim()
        if (q.isEmpty() || askBusy.value) return
        askBusy.value = true
        askAnswer.value = null
        viewModelScope.launch {
            askAnswer.value = runCatching { dash.api.askNeema(conversation.id, q).answer }
                .getOrElse { "Couldn't check right now — try again." }
            askBusy.value = false
        }
    }

    /** Answer-via-Neema: the team's confirmed facts, delivered in Neema's voice; the thread stays in AI mode. */
    val answerStatus = MutableStateFlow<String?>(null)
    val answerBusy = MutableStateFlow(false)

    fun answerViaNeema(facts: String, onSent: () -> Unit) {
        val f = facts.trim()
        if (f.isEmpty() || answerBusy.value) return
        answerBusy.value = true
        answerStatus.value = null
        viewModelScope.launch {
            try {
                val r = dash.api.answerViaNeema(conversation.id, f)
                answerStatus.value = "Neema sent: “${r.sent}”"
                onSent()
            } catch (e: Throwable) {
                val api = e as? ApiException
                answerStatus.value =
                    if (api?.status == 409 || api?.detail?.lowercase()?.contains("window") == true)
                        "Outside the messaging window — reply yourself when they next write."
                    else "Couldn't send right now — try again."
            } finally {
                answerBusy.value = false
            }
        }
    }

    // ── Reach-out: invite, template, call ────────────────────────────────────
    // Only ever to a real phone (realPhoneDigits): never a web visitor's hash.

    /** `profile.phone || digits`, as the web sends it — but never a web visitor's key. */
    private fun sendTo(p: CustomerProfile, digits: String): String =
        p.phone?.takeIf { it.isNotEmpty() && realPhoneDigits(it) != null } ?: digits

    /** Send the approved WhatsApp invite; if that fails, hand back a prefilled wa.me link to open instead. */
    fun inviteToWhatsApp(digits: String, openUrl: (String) -> Unit) {
        val p = _profile.value ?: return
        // The web derives these digits from profile.phone; a profile without a real phone has no reach-out.
        if (realPhoneDigits(p.phone) == null) return
        viewModelScope.launch {
            try {
                dash.api.whatsappInvite(sendTo(p, digits), p.name ?: "")
                dash.toast("WhatsApp invite sent ✓")
            } catch (_: Throwable) {
                val first = (p.name ?: "").trim().split(Regex("\\s+")).firstOrNull().orEmpty()
                val invite = "Hello${if (first.isNotEmpty()) " $first" else ""}, this is Bethany House. " +
                    "Continuing our chat here on WhatsApp so we can finalise your order."
                openUrl("https://wa.me/$digits?text=${URLEncoder.encode(invite, "UTF-8").replace("+", "%20")}")
            }
        }
    }

    fun sendTemplate(digits: String) {
        val p = _profile.value ?: return
        // The web derives these digits from profile.phone; a profile without a real phone has no reach-out.
        if (realPhoneDigits(p.phone) == null) return
        _templateBusy.value = true
        viewModelScope.launch {
            try {
                dash.api.whatsappInvite(sendTo(p, digits), p.name ?: "")
                dash.toast("Template sent ✓")
            } catch (_: Throwable) {
                dash.toast("Couldn't send the template", ToastType.Error)
            } finally {
                _templateBusy.value = false
            }
        }
    }

    /** WhatsApp voice call; with no call permission yet, ask the customer for it automatically. */
    fun call(digits: String) {
        val p = _profile.value ?: return
        // The web derives these digits from profile.phone; a profile without a real phone has no reach-out.
        if (realPhoneDigits(p.phone) == null) return
        viewModelScope.launch {
            val r = placeCall(digits, p.name)
            if (r.isSuccess) return@launch
            val err = r.exceptionOrNull()?.message.orEmpty()
            val lower = err.lowercase()
            // "Microphone permission" is the agent's own device, not the customer's consent.
            if ("permission" in lower && "microphone" !in lower) {
                try {
                    dash.api.calls.requestPermission(digits)
                    val first = p.name?.split(" ")?.firstOrNull()?.ifEmpty { null } ?: "them"
                    dash.toast("Asked $first for permission to call — you can call once they tap Allow.")
                } catch (_: Throwable) {
                    dash.toast("Couldn't send the call request", ToastType.Error)
                }
            } else {
                dash.toast(err.ifEmpty { "Couldn't place the call" }, ToastType.Error)
            }
        }
    }
}
