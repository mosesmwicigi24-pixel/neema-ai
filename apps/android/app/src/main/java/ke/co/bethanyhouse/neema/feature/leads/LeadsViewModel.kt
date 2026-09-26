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
import ke.co.bethanyhouse.neema.feature.orders.SalesInk
import ke.co.bethanyhouse.neema.feature.orders.SingleFlight
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import kotlinx.coroutines.CancellationException
import java.util.Locale
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
    LeadStage("new", "New", Palette.Stone600, Palette.Stone50, Palette.Stone200, Palette.Stone400),
    LeadStage("contacted", "Contacted", Palette.Blue700, Palette.Blue50, Palette.Blue200, Palette.Blue500),
    LeadStage("qualified", "Qualified", SalesInk.Violet700, Palette.Violet50, Palette.Violet200, SalesInk.Violet500),
    LeadStage("proposal", "Proposal", Palette.Amber700, Palette.Amber50, Palette.Amber200, Palette.Amber500),
    LeadStage("negotiation", "Negotiating", SalesInk.Orange700, SalesInk.Orange50, SalesInk.Orange200, SalesInk.Orange500),
    LeadStage("won", "Won", Palette.Emerald700, Palette.Emerald50, Palette.Emerald200, Palette.Emerald500),
    LeadStage("lost", "Lost", Palette.Red600, Palette.Red50, Palette.Red200, Palette.Red400),
)

/** Canonical columns plus the operator-added stages, which sit between Negotiating and Won. */
fun buildStages(customs: List<String>): List<LeadStage> {
    val defs = customs.filter { it.isNotBlank() }.map {
        LeadStage(it, it, SalesInk.Yellow700, SalesInk.Yellow50, SalesInk.Yellow200, SalesInk.Yellow500)
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

/**
 * A fresh read of the board, except the leads in [keepLocal] (changed here
 * after the read began, or mid-save): they keep the row on screen — or stay
 * gone, when this phone saw them deleted. One pass, whatever the board's size.
 */
internal fun overlayLocal(server: List<Lead>, onScreen: List<Lead>, keepLocal: Set<String>): List<Lead> {
    if (keepLocal.isEmpty()) return server
    val local = HashMap<String, Lead>(keepLocal.size * 2)
    for (l in onScreen) if (l.id in keepLocal) local[l.id] = l
    return server.mapNotNull { l -> if (l.id in keepLocal) local[l.id] else l }
}

/** The kanban as the screen draws it: every figure from one pass over the leads. */
@androidx.compose.runtime.Immutable
data class LeadBoard(
    /** Leads per stage id, unfiltered (the stage pills' counts). */
    val counts: Map<String, Int>,
    /** The filtered leads per stage id, in the server's (score) order. */
    val columns: Map<String, List<Lead>>,
    /** `total_spent` over each column's filtered leads (the column header's money). */
    val columnValue: Map<String, Double>,
    /** The header's "Pipeline": everything neither won nor lost. */
    val pipelineValue: Double,
    /** The header's "Won". */
    val wonValue: Double,
)

private fun stageKey(s: String?): String = s.orEmpty().trim().lowercase(Locale.ROOT)

/**
 * LeadsView's per-render work — `leads.filter(stage)` once per column and once
 * per pill, the pipeline and won sums — done once per change of the board:
 * O(leads + stages) instead of O(leads × stages) on every recomposition.
 * A lead matches a column as [LeadStage.matches] does (trimmed, any case).
 */
fun buildBoard(leads: List<Lead>, filtered: List<Lead>, stages: List<LeadStage>): LeadBoard {
    val count = HashMap<String, Int>()
    var pipeline = 0.0
    var won = 0.0
    for (l in leads) {
        val k = stageKey(l.leadStage)
        count[k] = (count[k] ?: 0) + 1
        val raw = l.leadStage.lowercase()
        if (raw != "lost" && raw != "won") pipeline += l.totalSpent
        if (l.leadStage.equals("won", ignoreCase = true)) won += l.totalSpent
    }
    val byStage = HashMap<String, MutableList<Lead>>()
    for (l in filtered) byStage.getOrPut(stageKey(l.leadStage)) { ArrayList() }.add(l)
    val columns = stages.associate { s -> s.id to (byStage[stageKey(s.id)] ?: emptyList<Lead>()) }
    return LeadBoard(
        counts = stages.associate { s -> s.id to (count[stageKey(s.id)] ?: 0) },
        columns = columns,
        columnValue = columns.mapValues { (_, col) -> col.sumOf { it.totalSpent } },
        pipelineValue = pipeline,
        wonValue = won,
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

    /** Local changes by lead id, stamped with [gen]: a read that began before one must not undo it. */
    private val touchedAt = HashMap<String, Long>()
    private var gen = 0L
    /** Leads with an optimistic move on the wire: every read keeps their local row until it settles. */
    private val moving = HashSet<String>()
    /** Leads whose next read must be the server's row (a save being settled). */
    private val truth = HashSet<String>()

    /**
     * The board's reads, one on the wire at a time: a visit, a return to the
     * app, a pull and the re-reads after saves share round trips instead of
     * stacking up on a slow network (a read asked for mid-flight is the next one).
     */
    private val reads = SingleFlight(viewModelScope) { fetchNow() }

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

    /**
     * Read the board. A failure keeps what is on screen and says why; true
     * when the board now shows the server's truth.
     *
     * [truthFor]: a lead whose save is being settled — its row is taken from
     * the server even though a local change to it is pending, so the answer
     * says whether the save landed.
     */
    private suspend fun fetch(truthFor: String? = null): Boolean {
        truthFor?.let { truth += it }
        return reads.run()
    }

    private suspend fun fetchNow(): Boolean {
        val startGen = gen
        val trusted = HashSet(truth).also { truth.clear() }
        return try {
            val list = api.list()
            _leads.value = overlayLocal(list, _leads.value, protectedSince(startGen) - trusted)
            touchedAt.values.removeAll { it <= startGen }
            _loadError.value = null
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _loadError.value = dash.salesFailure(e).message()
            false
        }
    }

    /** Leads changed here after a read began, or with a move still on the wire: that read predates them. */
    private fun protectedSince(startGen: Long): Set<String> =
        if (touchedAt.isEmpty() && moving.isEmpty()) emptySet()
        else touchedAt.filterValues { it > startGen }.keys + moving

    /** Marks [id] as changed here, now. */
    private fun touch(id: String) { touchedAt[id] = ++gen }

    fun select(id: String?) {
        if (id != _selectedId.value) _sheetError.value = null
        _selectedId.value = id
    }

    fun moveTo(lead: Lead, stage: String) = update(lead, stage = stage)

    private fun apply(id: String, edit: LeadEdit) {
        touch(id)
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
        moving += lead.id
        apply(lead.id, edit)
        viewModelScope.launch {
            try {
                api.update(lead.id, bodyOf(edit))
                dash.toast("Lead updated")
                // crm.py update_lead stores merge_notes(base, mine, current): the
                // saved notes are the operator's paragraphs PLUS any the server
                // appended since, and the reply is only {"ok": true}. Re-read
                // quietly so the board shows what was actually stored.
                if (notes != null) fetch(truthFor = lead.id)
            } catch (e: Exception) {
                val f = dash.salesFailure(e)
                val rollback = {
                    touch(lead.id)
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
                        if (fetch(truthFor = lead.id)) {
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
                        if (f.kind == FailKind.Conflict) fetch(truthFor = lead.id)
                    }
                }
            } finally {
                moving -= lead.id
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
                        val read = fetch(truthFor = lead.id)
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
        touch(id)
        _leads.value = _leads.value.filterNot { it.id == id }
        if (_selectedId.value == id) { _selectedId.value = null; _sheetError.value = null }
        dash.toast("This lead no longer exists — someone may have deleted or merged it", ToastType.Error)
    }
}
