package ke.co.bethanyhouse.neema.feature.conversations.customer

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.conversations.isWebVisitor
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.SerializationException
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
 *
 * Built for a flaky network (see CustomerErrors.kt): every action has one
 * request in flight at most, says why it failed in plain words, never calls a
 * request that may have landed (a timeout) a failure — it checks with the
 * server instead — and gives back whatever the agent typed when a save fails.
 */
class CustomerViewModel(
    private val dash: DashboardViewModel,
    private var conversation: Conversation,
    /** GET /admin/customers/{key}; swappable so tests can hold and reorder answers. */
    fetchProfile: (suspend (key: String, channel: String?) -> CustomerProfile)? = null,
    /** Places the WhatsApp voice call (the web's callCtx.initiateCall); swappable for tests. */
    private val placeCall: suspend (to: String, name: String?) -> Result<Unit> =
        { to, name -> dash.container.calls.initiateCall(to, name) },
) : ViewModel() {
    private val crm = CrmApi(dash.api.http)
    private val fetchProfile: suspend (String, String?) -> CustomerProfile = fetchProfile ?: { k, ch -> crm.profile(k, ch) }

    /**
     * wa_id for WhatsApp, else the PSID / IGSID (WhatsApp's wa_id IS its external_id).
     * Read from the live row, as the web's loadProfile deps are: a row that gains a
     * wa_id (a linked identity) reloads against the new key.
     */
    private val custId: String get() = conversation.waId ?: conversation.externalId ?: ""
    private val channel: String? get() = conversation.channel.ifEmpty { null }

    private val _loading = MutableStateFlow(true)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _profile = MutableStateFlow<CustomerProfile?>(null)
    val profile: StateFlow<CustomerProfile?> = _profile.asStateFlow()

    /** Pull-to-refresh: reloading over an already-painted profile. */
    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving.asStateFlow()

    /**
     * Why the last profile GET failed (null once one succeeds). The panel says so
     * over whatever it still shows — the last good profile, or the fallback built
     * from the chat row — with a Retry.
     */
    private val _loadError = MutableStateFlow<String?>(null)
    val loadError: StateFlow<String?> = _loadError.asStateFlow()

    /** A stage move is in flight: the stepper and Quick Actions wait, so a double tap can't skip a stage. */
    private val _stageBusy = MutableStateFlow(false)
    val stageBusy: StateFlow<Boolean> = _stageBusy.asStateFlow()

    /**
     * Input is sacred: the text of a field edit that did not save comes back
     * here, keyed by field ("name", "email", "age"…), for its editor to reopen
     * with. The editor takes it with [takeDraft].
     */
    private val _drafts = MutableStateFlow<Map<String, String>>(emptyMap())
    val drafts: StateFlow<Map<String, String>> = _drafts.asStateFlow()
    fun takeDraft(key: String) { _drafts.value = _drafts.value - key }
    private fun keepDraft(key: String, v: String) { _drafts.value = _drafts.value + (key to v) }

    /** The inputs of the panel, held here so a failure, a tab switch or a reload never loses them. */
    val tagInput = MutableStateFlow("")
    val mergeQuery = MutableStateFlow("")
    val askDraft = MutableStateFlow("")
    val answerDraft = MutableStateFlow("")
    /** The "+ Add stage" input: cleared only once the server kept the stage. */
    val newStage = MutableStateFlow("")

    val tab = MutableStateFlow(CustomerTab.Profile)

    /** The web's stageEditorOpen / editNotes: open sub-editors, kept here so they survive recomposition. */
    val stageEditorOpen = MutableStateFlow(false)
    val editNotes = MutableStateFlow(false)

    /**
     * The notes editor's text and the snapshot it started from. Held here, not in
     * the composable, so a live reload (an AI stage change, an appended call
     * summary) never resets what the agent is typing, and switching tabs keeps it.
     */
    val noteDraft = MutableStateFlow("")
    private val _notesBase = MutableStateFlow<String?>(null)
    /** The notes as they were when the edit began (null when not editing). */
    val notesBase: StateFlow<String?> = _notesBase.asStateFlow()

    private val _customStages = MutableStateFlow(StageCache.stages ?: emptyList())
    val customStages: StateFlow<List<String>> = _customStages.asStateFlow()
    private val _stagesSaving = MutableStateFlow(false)
    val stagesSaving: StateFlow<Boolean> = _stagesSaving.asStateFlow()

    private val _enquiry = MutableStateFlow<ProductionEnquiry?>(null)
    val enquiry: StateFlow<ProductionEnquiry?> = _enquiry.asStateFlow()
    private val _pushing = MutableStateFlow(false)
    val pushing: StateFlow<Boolean> = _pushing.asStateFlow()
    private var declining = false
    /** The last enquiry / stage-list GET failed: the next good profile load tries them again. */
    private var enquiryFailed = false
    private var stagesFailed = false
    private var enquiryJob: Job? = null
    /** Bumped by every push / dismiss; an enquiry GET that left before one is not painted over it. */
    private var enquirySeq = 0

    private val _showMerge = MutableStateFlow(false)
    val showMerge: StateFlow<Boolean> = _showMerge.asStateFlow()
    /** null = still scanning for duplicates. */
    private val _mergeSugs = MutableStateFlow<List<MergeSuggestion>?>(null)
    val mergeSugs: StateFlow<List<MergeSuggestion>?> = _mergeSugs.asStateFlow()
    /** The duplicate scan failed (offline, 5xx): said as such, not as "no duplicates". */
    private val _mergeSugsError = MutableStateFlow<String?>(null)
    val mergeSugsError: StateFlow<String?> = _mergeSugsError.asStateFlow()
    private var mergeJob: Job? = null
    private val _merging = MutableStateFlow(false)
    val merging: StateFlow<Boolean> = _merging.asStateFlow()
    /** Merged ids with an unmerge in flight (their chip waits). */
    private val _unmerging = MutableStateFlow<Set<String>>(emptySet())
    val unmerging: StateFlow<Set<String>> = _unmerging.asStateFlow()

    private val _templateBusy = MutableStateFlow(false)
    val templateBusy: StateFlow<Boolean> = _templateBusy.asStateFlow()
    private val _inviteBusy = MutableStateFlow(false)
    val inviteBusy: StateFlow<Boolean> = _inviteBusy.asStateFlow()
    private val _callBusy = MutableStateFlow(false)
    val callBusy: StateFlow<Boolean> = _callBusy.asStateFlow()

    // Reload bookkeeping — declared before init, whose load() already uses it.
    private var liveJob: Job? = null
    private var shownBefore = false
    /** Off screen (another thread, another view): no "Saved" for a panel that is gone. */
    private var hidden = false
    private var reloadJob: Job? = null
    private var loadJob: Job? = null
    private var stagesJob: Job? = null
    /** Bumped per GET; only the newest GET's answer is ever painted. */
    private var loadSeq = 0
    /** Bumped per local edit; a GET that left before an edit is not painted over it. */
    private var editSeq = 0
    private var patchesInFlight = 0
    /** A reload was held back by an edit in flight; run it once the edits settle. */
    private var reloadAfterEdits = false
    /** The profile last loaded or fallen back to, with every CONFIRMED edit applied. */
    private var confirmed: CustomerProfile? = null
    /** Whether [confirmed] came from the server (not the fallback). */
    private var realLoaded = false

    /** An optimistic edit in flight: rolled back alone, never by restoring a whole snapshot. */
    private class Edit(val body: String, val stage: Boolean, val apply: (CustomerProfile) -> CustomerProfile)
    private val edits = mutableListOf<Edit>()

    /** What to do with the agent's text if a save does not land: did it land, and how to give it back. */
    private class Draft(val landed: (CustomerProfile) -> Boolean, val restore: () -> Unit)
    /** Saves whose answer never came (a timeout): checked against the next profile that loads. */
    private val unconfirmed = mutableListOf<Draft>()

    companion object {
        /** Live triggers landing within this window cost one GET. */
        const val RELOAD_COALESCE_MS = 400L
    }

    init {
        load()
        loadEnquiry()
        loadStagesIfNeeded()
    }

    /**
     * A toast from this panel. Once it has left the screen, confirmations are
     * dropped and a failure names whose profile it was, so an error about Peter
     * never reads as if it were about the thread now open.
     */
    private fun say(msg: String, type: ToastType = ToastType.Success) {
        if (!hidden) { dash.toast(msg, type); return }
        if (type != ToastType.Error) return
        val who = _profile.value?.name?.takeIf { it.isNotBlank() } ?: conversation.name?.takeIf { it.isNotBlank() }
        dash.toast(if (who != null) "$who: $msg" else msg, type)
    }

    /**
     * The operator-added stages, once per process. The web caches a failure as
     * "no customs" for good; offline at first open that would hide a custom stage
     * all day, so a failure stays uncached and the next load tries again.
     */
    private fun loadStagesIfNeeded(force: Boolean = false) {
        if ((!force && StageCache.stages != null) || stagesJob?.isActive == true) return
        stagesJob = viewModelScope.launch {
            try {
                val st = dash.api.settings.getPipelineStages()
                StageCache.stages = st
                _customStages.value = st
                stagesFailed = false
                // A stage whose save timed out did land: its label leaves the input.
                if (newStage.value.isNotBlank() && newStage.value.trim() in st) newStage.value = ""
            } catch (e: CancellationException) {
                throw e
            } catch (_: Throwable) {
                // Keep what is shown; the next good profile load tries again.
                stagesFailed = true
            }
        }
    }

    /**
     * The web re-runs loadProfile whenever the thread's row changes (its deps:
     * wa_id, name, channel, last_message_at), so an AI-set stage or an appended
     * call summary shows up without reopening the panel. Same here, quietly over
     * the painted profile — and also when the row's own lead stage or order count
     * moves (an inbox refetch after the AI advanced the stage). Bursts of row
     * updates coalesce into one request ([requestReload]).
     */
    fun sync(conv: Conversation) {
        val prev = conversation
        conversation = conv
        if (conv.id != prev.id) return
        if (conv.lastMessageAt != prev.lastMessageAt || conv.name != prev.name ||
            conv.waId != prev.waId || conv.externalId != prev.externalId || conv.channel != prev.channel ||
            conv.leadStage != prev.leadStage || conv.ordersCount != prev.ordersCount
        ) requestReload()
    }

    // ── Staying live while the panel is on screen ────────────────────────────

    /**
     * The panel is on screen. The web remounts CustomerSidebar (and so refetches)
     * every time it opens; a re-shown panel here refetches quietly over what it
     * painted last. While shown, it also catches up on what the socket could not
     * tell it: coming back to the foreground, the socket reconnecting (frames were
     * lost meanwhile — and a reconnect is the offline agent's automatic retry),
     * and this customer's orders changing (`order_update` → dash.orders refetch).
     * All of it goes through [requestReload], so a foreground return that also
     * reconnects the socket costs one request.
     */
    fun onShown() {
        hidden = false
        if (shownBefore) requestReload()
        shownBefore = true
        liveJob?.cancel()
        liveJob = viewModelScope.launch {
            launch {
                var was = dash.foreground.value
                dash.foreground.collect { v -> if (v && !was) requestReload(); was = v }
            }
            launch {
                val socket = dash.container.socket
                var was = socket.connected.value
                socket.connected.collect { v -> if (v && !was) requestReload(); was = v }
            }
            launch {
                dash.orders
                    .map { all ->
                        val w = conversation.waId
                        if (w.isNullOrEmpty()) emptyList() else all.filter { it.waId == w || it.contactPhone == w }
                    }
                    .distinctUntilChanged()
                    .drop(1)
                    .collect { requestReload() }
            }
        }
    }

    /** The panel left the screen: nothing it would show is worth a request. */
    fun onHidden() {
        hidden = true
        liveJob?.cancel()
        liveJob = null
        reloadJob?.cancel()
    }

    /** The key edits persist against: the profile's own wa_id (a shim for non-WhatsApp contacts), else the handle. */
    private val key: String get() = _profile.value?.waId?.ifEmpty { null } ?: custId

    /**
     * A live trigger (row change, reconnect, foreground, orders): reload quietly,
     * coalescing everything that lands within [RELOAD_COALESCE_MS] into one GET.
     */
    fun requestReload() {
        reloadJob?.cancel()
        reloadJob = viewModelScope.launch {
            delay(RELOAD_COALESCE_MS)
            reloadJob = null
            load(showSpinner = false)
        }
    }

    /** Pull-to-refresh / Retry: the profile, and whatever else failed to load before. */
    fun refresh() {
        load(showSpinner = false)
        loadEnquiry()
        loadStagesIfNeeded()
    }

    /**
     * GET the profile. The newest request wins: an older one still in flight is
     * cancelled and, should its answer land anyway, dropped. An answer that raced
     * a local edit (an optimistic PATCH not yet settled, or one made after the GET
     * left) is not painted over the edit; the reload runs again once edits settle.
     *
     * A failure keeps what is painted (the last good profile, else a fallback from
     * the chat row, as the web does) and says why in [loadError].
     */
    fun load(showSpinner: Boolean = _profile.value == null) {
        reloadJob?.cancel()
        if (patchesInFlight > 0) { reloadAfterEdits = true; return }
        loadJob?.cancel()
        val seq = ++loadSeq
        val editsAtStart = editSeq
        if (showSpinner) _loading.value = true else _refreshing.value = true
        loadJob = viewModelScope.launch {
            try {
                val fresh = fetchProfile(custId, channel)
                // An empty 2xx body decodes to an all-defaults profile: that is no answer.
                if (fresh.id.isEmpty() && fresh.waId.isNullOrEmpty()) throw SerializationException("empty profile")
                if (seq != loadSeq) return@launch
                if (editSeq != editsAtStart || patchesInFlight > 0) { reloadAfterEdits = true; return@launch }
                confirmed = fresh
                realLoaded = true
                _profile.value = fresh
                _loadError.value = null
                settleUnconfirmed(fresh)
                if (enquiryFailed) loadEnquiry()
                if (stagesFailed) loadStagesIfNeeded()
            } catch (e: CancellationException) {
                throw e
            } catch (t: Throwable) {
                if (seq == loadSeq) {
                    // Fallback: a minimal profile from the conversation row, so the panel still works.
                    if (_profile.value == null) { confirmed = fallbackProfile(); _profile.value = confirmed }
                    _loadError.value = loadErrorText(t)
                }
            } finally {
                if (seq == loadSeq) {
                    _loading.value = false
                    _refreshing.value = false
                    if (reloadAfterEdits && patchesInFlight == 0) { reloadAfterEdits = false; requestReload() }
                }
            }
        }
    }

    private fun loadErrorText(t: Throwable): String = when {
        t.failure() == Failure.NotFound ->
            "No saved profile for this customer — it may have been merged into another. Showing what this chat knows."
        realLoaded -> "Couldn't refresh — ${t.reason()} Showing the profile as last loaded."
        else -> "Couldn't load the full profile — ${t.reason()} Showing what this chat knows."
    }

    /** Saves that timed out, checked against the profile the server now serves. */
    private fun settleUnconfirmed(fresh: CustomerProfile) {
        if (unconfirmed.isEmpty()) return
        val checks = unconfirmed.toList()
        unconfirmed.clear()
        val lost = checks.filterNot { it.landed(fresh) }
        lost.forEach { it.restore() }
        if (lost.isEmpty()) say("Saved")
        else say("That change didn't reach the server — it's back in the editor to try again.", ToastType.Error)
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

    private fun repaint() {
        val base = confirmed ?: return
        _profile.value = edits.fold(base) { p, e -> e.apply(p) }
    }

    /**
     * Optimistic PATCH: apply [local] at once, send [body]. [onSaved] runs only
     * after the server accepted it (the name → inbox hook).
     *
     * - A second identical save while the first is in flight is a double tap: dropped.
     * - A refusal rolls back THIS edit only (another edit in flight keeps its
     *   change) and hands the typed text back through [draft].
     * - A timeout may have saved: the edit stays, the profile is refetched once
     *   edits settle, and the text comes back only if the server doesn't have it.
     * - 404 (the record was merged away / removed) and 409 refetch the truth.
     */
    private fun patch(
        body: JsonObject,
        local: (CustomerProfile) -> CustomerProfile,
        draft: Draft? = null,
        onSaved: (() -> Unit)? = null,
    ) {
        val cur = _profile.value ?: return
        val sig = body.toString()
        if (edits.any { it.body == sig }) return
        if (confirmed == null) confirmed = cur
        val k = key
        val edit = Edit(sig, "lead_stage" in body, local)
        edits += edit
        _saving.value = true
        if (edit.stage) _stageBusy.value = true
        repaint()
        editSeq++
        patchesInFlight++
        viewModelScope.launch {
            try {
                crm.patch(k, channel, body)
                confirmed = confirmed?.let(local)
                edits.remove(edit)
                repaint()
                say("Saved")
                onSaved?.invoke()
            } catch (e: CancellationException) {
                throw e
            } catch (t: Throwable) {
                edits.remove(edit)
                if (t.mayHaveLanded) {
                    confirmed = confirmed?.let(local)
                    repaint()
                    if (draft != null) unconfirmed += draft
                    reloadAfterEdits = true
                    say("Couldn't confirm the save — checking with the server…", ToastType.Info)
                } else {
                    repaint()
                    draft?.restore?.invoke()
                    val f = t.failure()
                    if (f == Failure.NotFound || f == Failure.Conflict) reloadAfterEdits = true
                    say(
                        when (f) {
                            Failure.NotFound -> "Failed to save — this customer's profile is gone (it may have been merged into another). Refreshing."
                            Failure.Conflict -> "Failed to save — it changed meanwhile. Refreshing to show the latest."
                            else -> "Failed to save — ${t.reason()}"
                        },
                        ToastType.Error,
                    )
                }
            } finally {
                patchesInFlight--
                _stageBusy.value = edits.any { it.stage }
                if (patchesInFlight == 0) {
                    _saving.value = false
                    // A live update arrived mid-save (or a save needs checking): fetch it now.
                    if (reloadAfterEdits) { reloadAfterEdits = false; requestReload() }
                }
            }
        }
    }

    /** A text field's draft: landed when the server has exactly it; else back into that field's editor. */
    private fun fieldDraft(field: String, v: String, read: (CustomerProfile) -> String?) =
        Draft(landed = { (read(it) ?: "") == v }, restore = { keepDraft(field, v) })

    fun saveName(v: String, onNameChange: (String, String) -> Unit) {
        val waId = _profile.value?.waId ?: custId
        patch(buildJsonObject { put("name", v) }, { it.copy(name = v) }, fieldDraft("name", v) { it.name }) {
            if (v.isNotEmpty()) onNameChange(waId, v)
        }
    }

    fun saveField(field: String, v: String, local: (CustomerProfile) -> CustomerProfile) =
        patch(buildJsonObject { put(field, v) }, local, fieldDraft(field, v) { readField(it, field) })

    private fun readField(p: CustomerProfile, field: String): String? = when (field) {
        "name" -> p.name
        "role" -> p.role
        "organization" -> p.organization
        "email" -> p.email
        "phone" -> p.phone
        "country" -> p.country
        "location" -> p.location
        else -> null
    }

    /** `parseInt(v) || null` — leading digits count ("35 yrs" → 35); unparseable or zero is sent as null (the server then leaves it). */
    fun saveAge(v: String) {
        val age = Regex("^\\s*([+-]?\\d+)").find(v)?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it != 0 }
        patch(
            buildJsonObject { if (age != null) put("age", age) else put("age", JsonNull) },
            { it.copy(age = age) },
            Draft(landed = { age == null || it.age == age }, restore = { keepDraft("age", v) }),
        )
    }

    /** Ignored while another stage move is in flight: an impatient double tap on "Advance" must not skip a stage. */
    fun setStage(stage: String) {
        if (_stageBusy.value) return
        patch(
            buildJsonObject { put("lead_stage", stage) },
            // The server locks an operator-set stage as "manual"; mirror it so the AI hint clears.
            { it.copy(leadStage = stage, leadStageSource = "manual") },
        )
    }

    /** Add the tag in the input ([tagInput]); a refused save puts it back there. */
    fun addTag(tag: String = tagInput.value) {
        val p = _profile.value ?: return
        val t = tag.trim()
        if (t.isEmpty()) return
        if (tagInput.value.trim() == t) tagInput.value = ""
        val next = p.tags + t
        patch(
            buildJsonObject { putJsonArray("tags") { next.forEach { add(JsonPrimitive(it)) } } },
            { it.copy(tags = next) },
            Draft(landed = { t in it.tags }, restore = { if (tagInput.value.isBlank()) tagInput.value = t }),
        )
    }

    fun removeTag(tag: String) {
        val p = _profile.value ?: return
        val next = p.tags.filter { it != tag }
        patch(buildJsonObject { putJsonArray("tags") { next.forEach { add(JsonPrimitive(it)) } } }, { it.copy(tags = next) })
    }

    /** Open the notes editor on the notes as they are now; that text is the edit's base. */
    fun startEditNotes() {
        val n = _profile.value?.notes ?: ""
        noteDraft.value = n
        _notesBase.value = n
        editNotes.value = true
    }

    fun cancelEditNotes() {
        editNotes.value = false
        _notesBase.value = null
    }

    /**
     * notes_base = the snapshot the edit STARTED from (the web's own comment), so
     * the server MERGES rather than dropping a call summary appended while the
     * agent typed. The web reads it at save time, after a reload may already have
     * replaced the snapshot; this keeps the real one. When something did arrive
     * meanwhile, the merged text is fetched back so the panel shows what the
     * server kept. A save that fails reopens the editor on the same draft and base.
     */
    fun saveNotes(draft: String = noteDraft.value) {
        val current = _profile.value?.notes ?: ""
        val base = _notesBase.value ?: current
        editNotes.value = false
        _notesBase.value = null
        val merged = base != current
        patch(
            buildJsonObject { put("notes", draft); put("notes_base", base) },
            { it.copy(notes = draft) },
            Draft(
                landed = { (it.notes ?: "") == draft || (it.notes ?: "").contains(draft.trim()) },
                restore = {
                    if (!editNotes.value) {
                        noteDraft.value = draft
                        _notesBase.value = base
                        editNotes.value = true
                    }
                },
            ),
        ) {
            if (merged) requestReload()
        }
    }

    // ── Custom pipeline stages (admin-only on the server) ────────────────────

    /** Add the label typed in [newStage]; the input clears once the server kept it. */
    fun addCustomStage() {
        val label = newStage.value.trim()
        if (label.isEmpty()) return
        saveCustomStages(_customStages.value + label)
    }

    fun saveCustomStages(stages: List<String>) {
        if (_stagesSaving.value) return
        _stagesSaving.value = true
        viewModelScope.launch {
            try {
                val r = dash.api.settings.putPipelineStages(stages)
                StageCache.stages = r.stages
                _customStages.value = r.stages
                if (newStage.value.isNotBlank() && newStage.value.trim() in r.stages) newStage.value = ""
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                val api = e as? ApiException
                if (e.mayHaveLanded) {
                    say("Couldn't confirm the stage change — refreshing the stages.", ToastType.Info)
                    loadStagesIfNeeded(force = true)
                } else {
                    say(
                        when {
                            api?.status == 403 -> "Only an admin can change pipeline stages."
                            // crm.py put_pipeline_stages: "At most 4 custom stages" — worth saying as is.
                            api?.status == 422 && api.detail.startsWith("At most") -> api.detail.trimEnd('.') + "."
                            else -> "Couldn't save pipeline stages — ${e.reason()}"
                        },
                        ToastType.Error,
                    )
                }
            } finally {
                _stagesSaving.value = false
            }
        }
    }

    // ── Merge / unmerge ──────────────────────────────────────────────────────

    fun toggleMerge(open: Boolean = !_showMerge.value) {
        _showMerge.value = open
        mergeJob?.cancel()
        _mergeSugs.value = null
        _mergeSugsError.value = null
        if (!open) return
        scanForDuplicates()
    }

    /** Retry a duplicate scan that failed. */
    fun retryMergeScan() {
        if (!_showMerge.value) return
        mergeJob?.cancel()
        _mergeSugs.value = null
        _mergeSugsError.value = null
        scanForDuplicates()
    }

    private fun scanForDuplicates() {
        mergeJob = viewModelScope.launch {
            try {
                _mergeSugs.value = crm.mergeSuggestions(key, channel)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                // Never a spinner that never dies; and never "no duplicates" when we couldn't look.
                _mergeSugs.value = emptyList()
                _mergeSugsError.value = "Couldn't scan for duplicates — ${e.reason()}"
            }
        }
    }

    fun merge(target: String = mergeQuery.value, onDone: () -> Unit = {}) {
        val t = target.trim()
        if (t.isEmpty() || _merging.value) return
        _merging.value = true
        viewModelScope.launch {
            try {
                crm.merge(key, channel, t)
                say("Profiles merged successfully")
                toggleMerge(false)
                if (mergeQuery.value.trim() == t) mergeQuery.value = ""
                onDone()
                load(showSpinner = false)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                if (e.mayHaveLanded) {
                    // It may well have merged: show where it stands; the typed target stays.
                    say("Couldn't confirm the merge — refreshing to show where it stands.", ToastType.Info)
                    load(showSpinner = false)
                    retryMergeScan()
                } else {
                    val api = e as? ApiException
                    val primaryGone = api?.status == 404 && !api.detail.contains("Secondary", ignoreCase = true)
                    say(mergeError(e), ToastType.Error)
                    if (primaryGone || api?.status == 409) load(showSpinner = false)
                }
            } finally {
                _merging.value = false
            }
        }
    }

    /**
     * crm.py merge_customers refuses a typed target it can't find (404 "Secondary
     * customer not found") and a profile merged into itself (422). The web says
     * "Failed to merge profiles" to both; the operator can act on the difference.
     */
    private fun mergeError(t: Throwable): String {
        val e = t as? ApiException
        return when {
            e?.status == 404 && e.detail.contains("Secondary", ignoreCase = true) ->
                "Failed to merge profiles — no customer found for that phone / wa_id"
            e?.status == 404 ->
                "Failed to merge profiles — this profile is gone (it may already have been merged into another). Refreshing."
            e?.status == 422 -> "Failed to merge profiles — that's this same profile"
            e?.status == 409 -> "Failed to merge profiles — ${t.reason()} Refreshing."
            else -> "Failed to merge profiles — ${t.reason()}"
        }
    }

    fun unmerge(mergedId: String) {
        if (mergedId in _unmerging.value) return
        _unmerging.value = _unmerging.value + mergedId
        viewModelScope.launch {
            try {
                crm.unmerge(key, channel, mergedId)
                say("Unmerged")
                load(showSpinner = false)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                when (e.failure()) {
                    // crm.py: "No active merge to undo for this pair" — someone else already undid it.
                    Failure.NotFound -> {
                        say("Already unmerged — refreshed to show where it stands.", ToastType.Info)
                        load(showSpinner = false)
                    }
                    Failure.Uncertain -> {
                        say("Couldn't confirm the unmerge — refreshing to show where it stands.", ToastType.Info)
                        load(showSpinner = false)
                    }
                    Failure.Conflict -> {
                        say("Failed to unmerge — ${e.reason()} Refreshing.", ToastType.Error)
                        load(showSpinner = false)
                    }
                    else -> say("Failed to unmerge — ${e.reason()}", ToastType.Error)
                }
            } finally {
                _unmerging.value = _unmerging.value - mergedId
            }
        }
    }

    // ── Made-to-order enquiry ────────────────────────────────────────────────

    /** GET the conversation's enquiry. A failure keeps what is shown; the next reload tries again. */
    private fun loadEnquiry() {
        if (enquiryJob?.isActive == true) return
        val seq = enquirySeq
        enquiryJob = viewModelScope.launch {
            try {
                val e = crm.enquiry(conversation.id)
                enquiryFailed = false
                if (seq == enquirySeq && !_pushing.value && !declining) _enquiry.value = e
            } catch (e: CancellationException) {
                throw e
            } catch (_: Throwable) {
                // The web shows no card; a later reload (reconnect, pull) fills it in.
                enquiryFailed = true
            }
        }
    }

    private fun refetchEnquiry() {
        enquiryJob?.cancel()
        enquirySeq++
        loadEnquiry()
    }

    fun pushProduction() {
        val e = _enquiry.value ?: return
        if (_pushing.value || declining || e.status != "new") return
        _pushing.value = true
        enquirySeq++
        viewModelScope.launch {
            try {
                val r = crm.pushProduction(e.id)
                val n = r.hubOrderNumber ?: e.hubOrderNumber
                _enquiry.value = e.copy(status = "pushed", hubOrderNumber = n)
                say(
                    if (r.already) n?.let { "Already in production · $it" } ?: "Already in production"
                    else r.hubOrderNumber?.let { "Sent to production · $it" } ?: "Sent to production",
                )
            } catch (ex: CancellationException) {
                throw ex
            } catch (ex: Throwable) {
                _pushing.value = false
                when (ex.failure()) {
                    // crm.py push_production is idempotent, so a second tap can never double the order.
                    Failure.Uncertain -> {
                        say("Couldn't confirm it reached production — checking. Pushing again is safe: it never makes a second order.", ToastType.Info)
                        refetchEnquiry()
                    }
                    Failure.NotFound -> {
                        _enquiry.value = null
                        say("This made-to-order request no longer exists — someone may have removed it.", ToastType.Error)
                    }
                    Failure.Conflict -> {
                        say("This request was already handled — showing where it stands.", ToastType.Info)
                        refetchEnquiry()
                    }
                    // 422: the enquiry has no linked hub product (crm.py push_production) — its detail
                    // tells the operator what to do instead.
                    Failure.Invalid -> say(ex.humanDetail() ?: "Couldn't send to production — ${ex.reason()}", ToastType.Error)
                    // 502: the hub refused; its detail is an exception string, not for people.
                    Failure.Server -> say(
                        if ((ex as? ApiException)?.status == 502) "Couldn't send to production — the hub didn't accept it. Try again in a moment."
                        else "Couldn't send to production — ${ex.reason()}",
                        ToastType.Error,
                    )
                    else -> say("Couldn't send to production — ${ex.reason()}", ToastType.Error)
                }
            } finally {
                _pushing.value = false
            }
        }
    }

    fun declineProduction() {
        val e = _enquiry.value ?: return
        if (declining || _pushing.value || e.status != "new") return
        declining = true
        enquirySeq++
        _enquiry.value = e.copy(status = "declined")
        viewModelScope.launch {
            try {
                crm.declineProduction(e.id)
            } catch (ex: CancellationException) {
                throw ex
            } catch (ex: Throwable) {
                when (ex.failure()) {
                    Failure.Uncertain -> { declining = false; refetchEnquiry() }   // it may have: ask
                    Failure.NotFound -> _enquiry.value = null                         // gone either way
                    else -> {
                        _enquiry.value = e
                        say("Couldn't dismiss — ${ex.reason()}", ToastType.Error)
                    }
                }
            } finally {
                declining = false
            }
        }
    }

    // ── Ask Neema / Answer via Neema ─────────────────────────────────────────

    /** Ask-Neema: read-only lookups (sizes, past orders, call context); nothing reaches the customer. */
    val askAnswer = MutableStateFlow<String?>(null)
    val askBusy = MutableStateFlow(false)

    /** The web keeps the question in the box after asking (to refine it); so does this. */
    fun ask(question: String = askDraft.value) {
        val q = question.trim()
        if (q.isEmpty() || askBusy.value) return
        askBusy.value = true
        askAnswer.value = null
        viewModelScope.launch {
            try {
                askAnswer.value = dash.api.askNeema(conversation.id, q).answer
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                askAnswer.value = when (e.failure()) {
                    Failure.Offline -> "You're offline — ask again once you're connected."
                    Failure.Uncertain -> "Neema took too long to answer — try again."
                    Failure.SessionExpired -> "Your session expired — sign in again, then ask again."
                    Failure.RateLimited -> "Neema is busy — wait a moment, then ask again."
                    Failure.NotFound -> "This conversation no longer exists."
                    else -> "Couldn't check right now — try again."
                }
            } finally {
                askBusy.value = false
            }
        }
    }

    /** Answer-via-Neema: the team's confirmed facts, delivered in Neema's voice; the thread stays in AI mode. */
    val answerStatus = MutableStateFlow<String?>(null)
    val answerBusy = MutableStateFlow(false)

    /** Clears the box only once Neema sent it; any failure keeps the facts to send again. */
    fun answerViaNeema(facts: String = answerDraft.value, onSent: () -> Unit = {}) {
        val f = facts.trim()
        if (f.isEmpty() || answerBusy.value) return
        answerBusy.value = true
        answerStatus.value = null
        viewModelScope.launch {
            try {
                val r = dash.api.answerViaNeema(conversation.id, f)
                answerStatus.value = "Neema sent: “${r.sent}”"
                if (answerDraft.value.trim() == f) answerDraft.value = ""
                onSent()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                val api = e as? ApiException
                answerStatus.value = when {
                    // Never "couldn't send" for a turn that may have gone out to the customer.
                    e.mayHaveLanded -> "Couldn't confirm Neema sent it — check the thread before sending again."
                    api?.status == 409 || api?.detail?.lowercase()?.contains("window") == true ->
                        "Outside the messaging window — reply yourself when they next write."
                    e.failure() == Failure.Offline -> "You're offline — your answer is kept; send it once you're connected."
                    e.failure() == Failure.SessionExpired -> "Your session expired — sign in again, then send. Your answer is kept."
                    e.failure() == Failure.RateLimited -> "Too many requests — wait a moment, then send again."
                    e.failure() == Failure.NotFound -> "This conversation no longer exists."
                    else -> "Couldn't send right now — try again."
                }
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

    /**
     * Send the approved WhatsApp invite; if that is refused, hand back a
     * prefilled wa.me link to open instead (the web's fallback). A timeout may
     * have delivered it: no second message then — the agent checks the thread.
     */
    fun inviteToWhatsApp(digits: String, openUrl: (String) -> Unit) {
        val p = _profile.value ?: return
        // The web derives these digits from profile.phone; a profile without a real phone has no reach-out.
        if (realPhoneDigits(p.phone) == null || _inviteBusy.value) return
        _inviteBusy.value = true
        viewModelScope.launch {
            try {
                dash.api.whatsappInvite(sendTo(p, digits), p.name ?: "")
                say("WhatsApp invite sent ✓")
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                when {
                    e.mayHaveLanded ->
                        say("Couldn't confirm the invite went out — check the WhatsApp thread before sending again.", ToastType.Info)
                    // Signed out, or the panel is gone: never throw WhatsApp open out of nowhere.
                    e.failure() == Failure.SessionExpired || hidden ->
                        say("Couldn't send the WhatsApp invite — ${e.reason()}", ToastType.Error)
                    else -> {
                        val first = (p.name ?: "").trim().split(Regex("\\s+")).firstOrNull().orEmpty()
                        val invite = "Hello${if (first.isNotEmpty()) " $first" else ""}, this is Bethany House. " +
                            "Continuing our chat here on WhatsApp so we can finalise your order."
                        openUrl("https://wa.me/$digits?text=${URLEncoder.encode(invite, "UTF-8").replace("+", "%20")}")
                    }
                }
            } finally {
                _inviteBusy.value = false
            }
        }
    }

    fun sendTemplate(digits: String) {
        val p = _profile.value ?: return
        // The web derives these digits from profile.phone; a profile without a real phone has no reach-out.
        if (realPhoneDigits(p.phone) == null || _templateBusy.value) return
        _templateBusy.value = true
        viewModelScope.launch {
            try {
                dash.api.whatsappInvite(sendTo(p, digits), p.name ?: "")
                say("Template sent ✓")
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                if (e.mayHaveLanded) {
                    say("Couldn't confirm the template went out — check the WhatsApp thread before sending again.", ToastType.Info)
                } else {
                    say("Couldn't send the template — ${e.humanDetail()?.takeIf { (e as? ApiException)?.status == 400 } ?: e.reason()}", ToastType.Error)
                }
            } finally {
                _templateBusy.value = false
            }
        }
    }

    /** WhatsApp voice call; with no call permission yet, ask the customer for it automatically. One at a time. */
    fun call(digits: String) {
        val p = _profile.value ?: return
        // The web derives these digits from profile.phone; a profile without a real phone has no reach-out.
        if (realPhoneDigits(p.phone) == null || _callBusy.value) return
        _callBusy.value = true
        viewModelScope.launch {
            try {
                val r = placeCall(digits, p.name)
                if (r.isSuccess) return@launch
                val err = r.exceptionOrNull()?.message.orEmpty()
                val lower = err.lowercase()
                // "Microphone permission" is the agent's own device, not the customer's consent.
                if ("permission" in lower && "microphone" !in lower) {
                    try {
                        dash.api.calls.requestPermission(digits)
                        val first = p.name?.split(" ")?.firstOrNull()?.ifEmpty { null } ?: "them"
                        say("Asked $first for permission to call — you can call once they tap Allow.")
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Throwable) {
                        if (e.mayHaveLanded) {
                            say("Couldn't confirm the call request went out — check the thread before asking again.", ToastType.Info)
                        } else {
                            say("Couldn't send the call request — ${e.reason()}", ToastType.Error)
                        }
                    }
                } else {
                    say(err.ifEmpty { "Couldn't place the call" }, ToastType.Error)
                }
            } finally {
                _callBusy.value = false
            }
        }
    }
}
