package ke.co.bethanyhouse.neema.feature.leads

import androidx.compose.ui.graphics.Color
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.reports.ScreenLife
import ke.co.bethanyhouse.neema.feature.orders.FailKind
import ke.co.bethanyhouse.neema.feature.orders.lowerFirst
import ke.co.bethanyhouse.neema.feature.orders.salesFailure
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/** A pipeline column: its colours are the web's Tailwind text/bg/border/dot quartet. */
data class LeadStage(
    val id: String,
    val label: String,
    val text: Color,
    val bg: Color,
    val border: Color,
    val dot: Color,
) {
    /** The server lower-cases stages on read (normalise_stage); match the same way. */
    fun matches(stage: String?): Boolean = id.equals(stage?.trim(), ignoreCase = true)
}

/** The canonical columns (LeadsView STAGES). */
val BASE_STAGES = listOf(
    LeadStage("new", "New", Color(0xFF57534E), Color(0xFFFAFAF9), Color(0xFFE7E5E4), Color(0xFFA8A29E)),
    LeadStage("contacted", "Contacted", Color(0xFF1D4ED8), Color(0xFFEFF6FF), Color(0xFFBFDBFE), Color(0xFF3B82F6)),
    LeadStage("qualified", "Qualified", Color(0xFF6D28D9), Color(0xFFF5F3FF), Color(0xFFDDD6FE), Color(0xFF8B5CF6)),
    LeadStage("proposal", "Proposal", Color(0xFFB45309), Color(0xFFFFFBEB), Color(0xFFFDE68A), Color(0xFFF59E0B)),
    LeadStage("negotiation", "Negotiating", Color(0xFFC2410C), Color(0xFFFFF7ED), Color(0xFFFED7AA), Color(0xFFF97316)),
    LeadStage("won", "Won", Color(0xFF047857), Color(0xFFECFDF5), Color(0xFFA7F3D0), Color(0xFF10B981)),
    LeadStage("lost", "Lost", Color(0xFFDC2626), Color(0xFFFEF2F2), Color(0xFFFECACA), Color(0xFFF87171)),
)

/** Canonical columns plus the operator-added stages, which sit between Negotiating and Won. */
fun buildStages(customs: List<String>): List<LeadStage> {
    val defs = customs.filter { it.isNotBlank() }.map {
        LeadStage(it, it, Color(0xFFA16207), Color(0xFFFEFCE8), Color(0xFFFEF08A), Color(0xFFEAB308))
    }
    val won = BASE_STAGES.indexOfFirst { it.id == "won" }
    return BASE_STAGES.take(won) + defs + BASE_STAGES.drop(won)
}

/** LeadsView's `filteredLeads`: the stage filter, then name / handle / email / location. */
fun filterLeads(leads: List<Lead>, filterStage: String, search: String): List<Lead> {
    val q = search.lowercase()
    return leads.filter { l ->
        if (filterStage != "all" && !filterStage.equals(l.leadStage, ignoreCase = true)) return@filter false
        if (q.isNotEmpty()) {
            l.name.orEmpty().lowercase().contains(q) ||
                l.handle.contains(q) ||
                l.email.orEmpty().lowercase().contains(q) ||
                l.location.orEmpty().lowercase().contains(q)
        } else true
    }
}

/** A detail-sheet save: only the fields that changed are set (null = untouched). */
data class LeadEdit(
    val stage: String? = null,
    val tags: List<String>? = null,
    val notes: String? = null,
    /** The notes text the edit started from — the server's three-way merge base. */
    val notesBase: String = "",
) {
    val isEmpty: Boolean get() = stage == null && tags == null && notes == null
}

/** The web's `tags.split(",").map(trim).filter(Boolean)`. */
fun parseTags(text: String): List<String> = text.split(",").map { it.trim() }.filter { it.isNotEmpty() }

/**
 * What changed between [base] (the lead as the sheet opened) and the sheet's
 * fields. The web PATCHes all three every time, which re-locks an untouched
 * AI-set stage as "manual" and clobbers notes appended meanwhile; only real
 * changes are sent here, and notes carry their base for the server's merge.
 */
fun diffLead(base: Lead, stage: String, tagsText: String, notes: String): LeadEdit {
    val tags = parseTags(tagsText)
    val baseNotes = base.notes.orEmpty()
    return LeadEdit(
        stage = stage.takeIf { !it.equals(base.leadStage, ignoreCase = true) },
        tags = tags.takeIf { it != base.tags },
        notes = notes.takeIf { it != baseNotes },
        notesBase = baseNotes,
    )
}

/** Paragraphs as crm.py `merge_notes` splits them. */
private fun paras(s: String?): List<String> = s.orEmpty().split("\n\n").map { it.trim() }.filter { it.isNotEmpty() }

/**
 * Whether [edit] is what the server now holds for [stored] — used when a
 * save's answer was lost. Notes are merged server-side (the operator's
 * paragraphs plus any appended meanwhile), so they landed when every typed
 * paragraph is there.
 */
internal fun editLanded(edit: LeadEdit, stored: Lead): Boolean {
    if (edit.stage != null && !edit.stage.equals(stored.leadStage, ignoreCase = true)) return false
    if (edit.tags != null && edit.tags != stored.tags) return false
    if (edit.notes != null) {
        val mine = paras(edit.notes)
        val now = paras(stored.notes)
        if (!now.containsAll(mine)) return false
        // Paragraphs deleted on purpose must be gone too.
        if (paras(edit.notesBase).any { it !in mine && it in now }) return false
    }
    return true
}

/** LeadsView's state: the leads, the pipeline's columns, filter/search and the open lead. */
class LeadsViewModel(private val dash: DashboardViewModel) : ViewModel() {
    private val api = LeadsApi(dash.api.http)

    private val _leads = MutableStateFlow<List<Lead>>(emptyList())
    val leads: StateFlow<List<Lead>> = _leads.asStateFlow()

    private val _loading = MutableStateFlow(true)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    /**
     * Why the last read of the leads failed (null when it worked). The web
     * empties the board on any failure; here what was read stays on screen
     * under a banner, and a board that was never read shows the reason and a
     * Retry instead of seven empty columns.
     */
    private val _loadError = MutableStateFlow<String?>(null)
    val loadError: StateFlow<String?> = _loadError.asStateFlow()

    private val _stages = MutableStateFlow(BASE_STAGES)
    val stages: StateFlow<List<LeadStage>> = _stages.asStateFlow()

    /** "all" or a stage id. */
    val filterStage = MutableStateFlow("all")
    val search = MutableStateFlow("")

    private val _selectedId = MutableStateFlow<String?>(null)
    val selectedId: StateFlow<String?> = _selectedId.asStateFlow()

    /** Leads with a save in flight: their move buttons wait, and a second save can't overtake the first. */
    private val _saving = MutableStateFlow<Set<String>>(emptySet())
    val saving: StateFlow<Set<String>> = _saving.asStateFlow()

    /** Why the open sheet's save failed — shown in the sheet, over the fields as typed. */
    private val _sheetError = MutableStateFlow<String?>(null)
    val sheetError: StateFlow<String?> = _sheetError.asStateFlow()

    /**
     * LeadsView loads its stages and leads on mount, so every visit reads them
     * fresh; this ViewModel outlives the screen, so each return to it — and
     * each return to the app, as Neema moves leads along the pipeline while the
     * phone is in a pocket — re-reads both quietly (no spinner; a failure keeps
     * the board). An open lead's sheet keeps what the operator typed: it edits
     * against the lead as it was when opened.
     */
    val life = ScreenLife(viewModelScope, dash.foreground, catchUp = ::reread)

    init {
        viewModelScope.launch {
            runCatching { dash.api.settings.getPipelineStages() }.onSuccess { _stages.value = buildStages(it) }
        }
        load()
    }

    private suspend fun reread() {
        runCatching { dash.api.settings.getPipelineStages() }.onSuccess { _stages.value = buildStages(it) }
        fetch()
    }

    fun load() {
        viewModelScope.launch {
            _loading.value = true
            fetch()
            _loading.value = false
        }
    }

    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            runCatching { dash.api.settings.getPipelineStages() }.onSuccess { _stages.value = buildStages(it) }
            fetch()
            _refreshing.value = false
        }
    }

    /** Reads overlap (a visit, a pull, a reconcile after a save): only the newest lands. */
    private var fetchSeq = 0

    /**
     * Read the board. A failure keeps what is on screen and says why; true
     * when the board now shows the server's truth.
     */
    private suspend fun fetch(): Boolean {
        val seq = ++fetchSeq
        return try {
            val list = api.list()
            if (seq == fetchSeq) { _leads.value = list; _loadError.value = null }
            true
        } catch (e: Exception) {
            val f = dash.salesFailure(e)
            if (seq == fetchSeq) _loadError.value = f.message()
            false
        }
    }

    fun select(id: String?) {
        if (id != _selectedId.value) _sheetError.value = null
        _selectedId.value = id
    }

    fun moveTo(lead: Lead, stage: String) = update(lead, stage = stage)

    private fun apply(id: String, edit: LeadEdit) {
        _leads.value = _leads.value.map { l ->
            if (l.id != id) l else l.copy(
                leadStage = edit.stage ?: l.leadStage,
                tags = edit.tags ?: l.tags,
                notes = edit.notes ?: l.notes,
            )
        }
    }

    private fun bodyOf(edit: LeadEdit) = buildJsonObject {
        if (edit.stage != null) put("lead_stage", edit.stage)
        if (edit.tags != null) putJsonArray("tags") { edit.tags.forEach { add(JsonPrimitive(it)) } }
        if (edit.notes != null) {
            put("notes", edit.notes)
            put("notes_base", edit.notesBase)
        }
    }

    /**
     * A card's stage move (or any direct edit): optimistic — the board changes
     * at once. A failed save puts the lead back as it was (only that lead; the
     * web reloads the whole board, which offline empties it) and says why; a
     * deleted lead (404) leaves the board; a save whose answer was lost is
     * settled by re-reading the board, whose truth decides what is said.
     */
    fun update(
        lead: Lead,
        stage: String? = null,
        tags: List<String>? = null,
        notes: String? = null,
        notesBase: String = lead.notes.orEmpty(),
    ) {
        if (lead.id in _saving.value) return
        val edit = LeadEdit(stage, tags, notes, notesBase)
        val before = _leads.value.find { it.id == lead.id } ?: lead
        _saving.value = _saving.value + lead.id
        apply(lead.id, edit)
        viewModelScope.launch {
            try {
                api.update(lead.id, bodyOf(edit))
                dash.toast("Lead updated")
                // crm.py update_lead stores merge_notes(base, mine, current): the
                // saved notes are the operator's paragraphs PLUS any the server
                // appended since, and the reply is only {"ok": true}. Re-read
                // quietly so the board shows what was actually stored.
                if (notes != null) fetch()
            } catch (e: Exception) {
                val f = dash.salesFailure(e)
                val rollback = {
                    _leads.value = _leads.value.map { l ->
                        if (l.id != lead.id) l else l.copy(
                            leadStage = if (stage != null) before.leadStage else l.leadStage,
                            tags = if (tags != null) before.tags else l.tags,
                            notes = if (notes != null) before.notes else l.notes,
                        )
                    }
                }
                when {
                    f.kind == FailKind.NotFound -> gone(lead.id)
                    f.mayHaveHappened -> {
                        if (fetch()) {
                            val now = _leads.value.find { it.id == lead.id }
                            when {
                                now == null -> dash.toast("This lead no longer exists — someone may have deleted or merged it", ToastType.Error)
                                editLanded(edit, now) -> dash.toast("Lead updated")
                                else -> dash.toast("Lead not updated — ${f.message().lowerFirst()}", ToastType.Error)
                            }
                        } else {
                            rollback()
                            dash.toast("No answer from the server — the lead may not have changed. Pull down to check.", ToastType.Error)
                        }
                    }
                    f.kind == FailKind.SessionExpired -> rollback() // the session dialog says why
                    else -> {
                        rollback()
                        dash.toast("Failed to update lead — ${f.message().lowerFirst()}", ToastType.Error)
                        if (f.kind == FailKind.Conflict) fetch()
                    }
                }
            } finally {
                _saving.value = _saving.value - lead.id
            }
        }
    }

    /**
     * The detail sheet's Save. The web closes the sheet and saves behind it,
     * so a failed save throws away what was typed; here the sheet stays open
     * (fields as typed, Save showing progress) until the server has the
     * change, and a failure is explained inside it. Nothing typed is ever lost.
     */
    fun save(lead: Lead, edit: LeadEdit) {
        if (edit.isEmpty) { select(null); return }
        if (lead.id in _saving.value) return
        _saving.value = _saving.value + lead.id
        _sheetError.value = null
        viewModelScope.launch {
            try {
                api.update(lead.id, bodyOf(edit))
                saved(lead.id, edit)
            } catch (e: Exception) {
                val f = dash.salesFailure(e)
                when {
                    f.kind == FailKind.NotFound -> gone(lead.id)
                    f.mayHaveHappened -> {
                        val read = fetch()
                        val now = _leads.value.find { it.id == lead.id }
                        when {
                            read && now == null -> gone(lead.id)
                            // The board was just re-read: it already shows what was stored.
                            read && editLanded(edit, now!!) -> saved(lead.id, edit, fresh = true)
                            read -> sheetFailed(lead.id, "Not saved — ${f.message().lowerFirst()}")
                            else -> sheetFailed(lead.id, "No answer from the server — your changes may not have saved. Save again to be sure.")
                        }
                    }
                    f.kind == FailKind.SessionExpired -> sheetFailed(lead.id, "Your session expired — sign in again, then save.")
                    else -> sheetFailed(lead.id, "Couldn't save — ${f.message().lowerFirst()}")
                }
            } finally {
                _saving.value = _saving.value - lead.id
            }
        }
    }

    /** [fresh]: the board was re-read after the save, so it is already the server's truth. */
    private suspend fun saved(id: String, edit: LeadEdit, fresh: Boolean = false) {
        if (!fresh) apply(id, edit)
        if (_selectedId.value == id) { _selectedId.value = null; _sheetError.value = null }
        dash.toast("Lead updated")
        // The notes stored are merged server-side: re-read so the board shows them.
        if (!fresh && edit.notes != null) fetch()
    }

    private fun sheetFailed(id: String, message: String) {
        if (_selectedId.value == id) _sheetError.value = message
        else dash.toast(message, ToastType.Error)
    }

    /** 404: someone deleted (or merged) this lead. It leaves the board, and its sheet closes. */
    private fun gone(id: String) {
        _leads.value = _leads.value.filterNot { it.id == id }
        if (_selectedId.value == id) { _selectedId.value = null; _sheetError.value = null }
        dash.toast("This lead no longer exists — someone may have deleted or merged it", ToastType.Error)
    }
}
