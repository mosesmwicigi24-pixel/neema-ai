package ke.co.bethanyhouse.neema.feature.deals

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Deal
import ke.co.bethanyhouse.neema.core.model.PlannedAction
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * DealsView's state: the open deals (the board), how many are won, and
 * Neema's initiative queue. Refreshes every minute while the app is in the
 * foreground, like the web's visibility-gated interval.
 */
class DealsViewModel(private val dash: DashboardViewModel) : ViewModel() {

    /** null = still loading (the web's `deals === null`). */
    private val _deals = MutableStateFlow<List<Deal>?>(null)
    val deals: StateFlow<List<Deal>?> = _deals.asStateFlow()

    /**
     * The web counts "won" among the list it fetched with status=open, which
     * is always zero; the won deals are fetched on their own so the header's
     * count is real.
     */
    private val _wonCount = MutableStateFlow(0)
    val wonCount: StateFlow<Int> = _wonCount.asStateFlow()

    private val _actions = MutableStateFlow<List<PlannedAction>?>(null)
    val actions: StateFlow<List<PlannedAction>?> = _actions.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    /** Ids of queue items with a send/veto in flight, so a double tap can't double-send. */
    private val _acting = MutableStateFlow<Set<String>>(emptySet())
    val acting: StateFlow<Set<String>> = _acting.asStateFlow()

    /** The deal whose guidance is open for editing, and its draft (the web's `editing` / `guidanceDraft`). */
    private val _editing = MutableStateFlow<String?>(null)
    val editing: StateFlow<String?> = _editing.asStateFlow()
    private val _guidanceDraft = MutableStateFlow("")
    val guidanceDraft: StateFlow<String> = _guidanceDraft.asStateFlow()

    /** The planned action open in the edit-and-send dialog. */
    private val _draftFor = MutableStateFlow<PlannedAction?>(null)
    val draftFor: StateFlow<PlannedAction?> = _draftFor.asStateFlow()

    fun startGuidance(d: Deal) { _editing.value = d.id; _guidanceDraft.value = d.guidance.orEmpty() }
    /** The web's `e.target.value.slice(0, 400)`. */
    fun setGuidanceDraft(text: String) { _guidanceDraft.value = text.take(400) }
    fun cancelGuidance() { _editing.value = null }
    fun openDraft(a: PlannedAction?) { _draftFor.value = a }

    init {
        viewModelScope.launch {
            val fg = dash.foreground
            while (isActive) {
                load()
                delay(60_000)
                if (!fg.value) fg.first { it }
            }
        }
    }

    private suspend fun load() {
        val deals = viewModelScope.async { runCatching { dash.api.deals.list("open") }.getOrElse { emptyList() } }
        val won = viewModelScope.async { runCatching { dash.api.deals.list("won").size }.getOrNull() }
        val actions = viewModelScope.async { runCatching { dash.api.actions.list() }.getOrElse { emptyList() } }
        _deals.value = deals.await()
        won.await()?.let { _wonCount.value = it }
        _actions.value = actions.await()
    }

    fun reload() { viewModelScope.launch { load() } }

    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            load()
            _refreshing.value = false
        }
    }

    fun patchDeal(id: String, body: JsonObject, msg: String) {
        viewModelScope.launch {
            try {
                dash.api.deals.patch(id, body)
                dash.toast(msg)
                load()
            } catch (e: Exception) {
                dash.toast("Update failed — ${dash.errorText(e)}", ToastType.Error)
            }
        }
    }

    fun saveGuidance(id: String, guidance: String = _guidanceDraft.value) {
        patchDeal(id, buildJsonObject { put("guidance", guidance) }, "Guidance saved — Neema obeys it now")
        _editing.value = null
    }

    fun markWon(id: String) =
        patchDeal(id, buildJsonObject { put("status", "won"); put("stage", "won") }, "Marked won 🎉")

    fun markLost(id: String) =
        patchDeal(id, buildJsonObject { put("status", "lost"); put("stage", "lost") }, "Marked lost")

    /**
     * Approve (send now) or veto a planned action. [draft] is the operator's
     * edited text; null sends Neema's own draft (or lets her compose one).
     */
    fun act(id: String, verb: String, draft: String? = null) {
        if (id in _acting.value) return
        viewModelScope.launch {
            _acting.value = _acting.value + id
            try {
                if (verb == "approve") dash.api.actions.approve(id, draft?.trim()?.ifEmpty { null })
                else dash.api.actions.veto(id)
                dash.toast(if (verb == "approve") "Sent ✓" else "Vetoed")
                load()
            } catch (e: Exception) {
                dash.toast("$verb failed — ${dash.errorText(e)}", ToastType.Error)
            } finally {
                _acting.value = _acting.value - id
            }
        }
    }
}
