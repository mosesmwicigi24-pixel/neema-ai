package ke.co.bethanyhouse.neema.feature.leads

import androidx.compose.ui.graphics.Color
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
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

/** LeadsView's state: the leads, the pipeline's columns, filter/search and the open lead. */
class LeadsViewModel(private val dash: DashboardViewModel) : ViewModel() {
    private val api = LeadsApi(dash.api.http)

    private val _leads = MutableStateFlow<List<Lead>>(emptyList())
    val leads: StateFlow<List<Lead>> = _leads.asStateFlow()

    private val _loading = MutableStateFlow(true)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _stages = MutableStateFlow(BASE_STAGES)
    val stages: StateFlow<List<LeadStage>> = _stages.asStateFlow()

    /** "all" or a stage id. */
    val filterStage = MutableStateFlow("all")
    val search = MutableStateFlow("")

    private val _selectedId = MutableStateFlow<String?>(null)
    val selectedId: StateFlow<String?> = _selectedId.asStateFlow()

    init {
        viewModelScope.launch {
            runCatching { dash.api.settings.getPipelineStages() }.onSuccess { _stages.value = buildStages(it) }
        }
        load()
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

    /** The web shows an empty board on any failure; the toast says why. */
    private suspend fun fetch() {
        try {
            _leads.value = api.list()
        } catch (e: Exception) {
            _leads.value = emptyList()
            dash.toast(dash.errorText(e), ToastType.Error)
        }
    }

    fun select(id: String?) { _selectedId.value = id }

    fun moveTo(lead: Lead, stage: String) = update(lead, stage = stage)

    /**
     * Optimistic: the board changes at once; a failed save says so and reloads
     * (the rollback). A notes edit carries the text it started from, so notes
     * the server appended meanwhile (call summaries, merges) survive.
     */
    fun update(
        lead: Lead,
        stage: String? = null,
        tags: List<String>? = null,
        notes: String? = null,
        notesBase: String = lead.notes.orEmpty(),
    ) {
        _leads.value = _leads.value.map { l ->
            if (l.id != lead.id) l else l.copy(
                leadStage = stage ?: l.leadStage,
                tags = tags ?: l.tags,
                notes = notes ?: l.notes,
            )
        }
        val body = buildJsonObject {
            if (stage != null) put("lead_stage", stage)
            if (tags != null) putJsonArray("tags") { tags.forEach { add(JsonPrimitive(it)) } }
            if (notes != null) {
                put("notes", notes)
                put("notes_base", notesBase)
            }
        }
        viewModelScope.launch {
            try {
                api.update(lead.id, body)
                dash.toast("Lead updated")
            } catch (e: Exception) {
                dash.toast("Failed to update lead — ${dash.errorText(e)}", ToastType.Error)
                load()
            }
        }
    }
}
