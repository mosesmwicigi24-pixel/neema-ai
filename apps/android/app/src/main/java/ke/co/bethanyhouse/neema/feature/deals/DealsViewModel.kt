package ke.co.bethanyhouse.neema.feature.deals

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Deal
import ke.co.bethanyhouse.neema.core.model.OkResponse
import ke.co.bethanyhouse.neema.core.model.PlannedAction
import ke.co.bethanyhouse.neema.feature.orders.FailKind
import ke.co.bethanyhouse.neema.feature.orders.SalesFailure
import ke.co.bethanyhouse.neema.feature.orders.SingleFlight
import ke.co.bethanyhouse.neema.feature.orders.SavesUi
import ke.co.bethanyhouse.neema.feature.orders.str
import ke.co.bethanyhouse.neema.feature.orders.lowerFirst
import ke.co.bethanyhouse.neema.feature.orders.salesFailure
import ke.co.bethanyhouse.neema.feature.reports.Coalescer
import ke.co.bethanyhouse.neema.feature.reports.ScreenLife
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * DealsView's state: the open deals (the board), how many are won, and
 * Neema's initiative queue. Refreshes every minute while on display, like
 * the web's visibility-gated interval (see [life]).
 */
class DealsViewModel(private val dash: DashboardViewModel) : ViewModel(), SavesUi {
    companion object {
        /** DealsView's interval. */
        const val POLL_MS = 60_000L
        /** Notifications that change the board or the queue. */
        val RELOAD_ON = setOf("planned_action", "hub_event")
        /**
         * After a send whose answer was lost, how often and how many times the
         * queue is re-read to learn whether it went (≈30 s of checking). The
         * row stays locked meanwhile, so a second tap can't race the first.
         */
        const val SETTLE_MS = 10_000L
        const val SETTLE_READS = 4
    }

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

    /**
     * Why the last load failed (null when it worked). The web blanks the board
     * and the queue on any failure ("Nothing queued" — a lie offline); here
     * what was loaded stays, and this says why it is not fresh.
     */
    private val _loadError = MutableStateFlow<String?>(null)
    val loadError: StateFlow<String?> = _loadError.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    /** Ids of queue items with a send/veto in flight (or being settled), so a double tap can't double-send. */
    private val _acting = MutableStateFlow<Set<String>>(emptySet())
    val acting: StateFlow<Set<String>> = _acting.asStateFlow()

    /** Queue items whose send got no answer: the queue is being re-read to learn whether it went. */
    private val _checking = MutableStateFlow<Set<String>>(emptySet())
    val checking: StateFlow<Set<String>> = _checking.asStateFlow()

    /** Deals with a won / lost / guidance save in flight: their buttons wait. */
    private val _patching = MutableStateFlow<Set<String>>(emptySet())
    val patching: StateFlow<Set<String>> = _patching.asStateFlow()

    /** The deal whose guidance is open for editing, and its draft (the web's `editing` / `guidanceDraft`). */
    private val _editing = MutableStateFlow<String?>(null)
    val editing: StateFlow<String?> = _editing.asStateFlow()
    private val _guidanceDraft = MutableStateFlow("")
    val guidanceDraft: StateFlow<String> = _guidanceDraft.asStateFlow()
    /** Why the guidance didn't save — shown under the text, which stays as typed. */
    private val _guidanceError = MutableStateFlow<String?>(null)
    val guidanceError: StateFlow<String?> = _guidanceError.asStateFlow()

    /** The planned action open in the edit-and-send dialog. */
    private val _draftFor = MutableStateFlow<PlannedAction?>(null)
    val draftFor: StateFlow<PlannedAction?> = _draftFor.asStateFlow()
    /**
     * The dialog's text lives here, not in the dialog: a failed send (or a
     * session that expired mid-send) leaves the dialog open with every word.
     */
    private val _draftText = MutableStateFlow("")
    val draftText: StateFlow<String> = _draftText.asStateFlow()
    private var draftTextFor: String? = null
    private val _draftError = MutableStateFlow<String?>(null)
    val draftError: StateFlow<String?> = _draftError.asStateFlow()

    fun startGuidance(d: Deal) {
        _editing.value = d.id; _guidanceDraft.value = d.guidance.orEmpty(); _guidanceError.value = null
    }
    /** The web's `e.target.value.slice(0, 400)`. */
    fun setGuidanceDraft(text: String) { _guidanceDraft.value = text.take(400) }
    fun cancelGuidance() { _editing.value = null; _guidanceError.value = null }

    /**
     * Open (or close, with null) the edit-and-send dialog. Reopening the same
     * action keeps what was typed; another action starts from its own draft.
     */
    fun openDraft(a: PlannedAction?) {
        if (a != null && a.id != draftTextFor) {
            draftTextFor = a.id
            _draftText.value = a.draft.orEmpty()
        }
        if (a == null || a.id != _draftFor.value?.id) _draftError.value = null
        _draftFor.value = a
    }
    fun setDraftText(text: String) { _draftText.value = text }

    // ── Process death: the guidance being typed and the edit-and-send dialog come back ──
    override var uiAttached = false
    /** The dialog's action, restored before the queue has loaded: it reopens once the action is read. */
    private var pendingDraftFor: String? = null

    override fun saveUi(): Map<String, Any?> = mapOf(
        "editing" to _editing.value, "guidance" to _guidanceDraft.value,
        "draftFor" to (_draftFor.value?.id ?: pendingDraftFor), "draftTextFor" to draftTextFor, "draftText" to _draftText.value,
    )

    override fun restoreUi(saved: Map<String, Any?>) {
        saved.str("editing")?.let { _editing.value = it; _guidanceDraft.value = saved.str("guidance").orEmpty().take(400) }
        saved.str("draftTextFor")?.let { draftTextFor = it; _draftText.value = saved.str("draftText").orEmpty() }
        pendingDraftFor = saved.str("draftFor")
        reopenDraft()
    }

    /** Reopens a restored dialog once its action is in the queue (and forgets it if the action left). */
    private fun reopenDraft() {
        val id = pendingDraftFor ?: return
        val list = _actions.value ?: return
        pendingDraftFor = null
        list.find { it.id == id }?.let { openDraft(it) }
    }

    /**
     * Queue items sent or vetoed here, by the [gen] at which they left: a load
     * that was already on the wire when one left must not bring it back (a
     * sent follow-up reappearing with a live Send button).
     */
    private val left = HashMap<String, Long>()
    private var gen = 0L

    private val loads = SingleFlight(viewModelScope) {
        val startGen = gen
        val deals = viewModelScope.async { runCatching { dash.api.deals.list("open") } }
        val won = viewModelScope.async { runCatching { dash.api.deals.list("won").size } }
        val actions = viewModelScope.async { runCatching { dash.api.actions.list() } }
        val d = deals.await(); val w = won.await(); val a = actions.await()
        (d.exceptionOrNull() ?: w.exceptionOrNull() ?: a.exceptionOrNull())?.let { if (it is CancellationException) throw it }
        d.onSuccess { _deals.value = it }
        w.onSuccess { _wonCount.value = it }
        a.onSuccess { list ->
            _actions.value = if (left.isEmpty()) list else list.filterNot { (left[it.id] ?: -1L) > startGen }
            // What left before this read began is in the server's answer now.
            left.values.removeAll { it <= startGen }
            reopenDraft()
        }
        val failed = d.exceptionOrNull() ?: a.exceptionOrNull() ?: w.exceptionOrNull()
        _loadError.value = failed?.let { dash.salesFailure(it).message() }
        failed == null
    }

    /**
     * DealsView loads on mount and every 60 s while the tab is visible. Here:
     * only while this screen is on display and the app in front, reloading on
     * every return to it and after the live socket reconnects.
     */
    val life = ScreenLife(
        viewModelScope, dash.foreground, dash.container.socket.connected,
        pollMs = POLL_MS, poll = { load() }, catchUp = { load() },
    )

    /**
     * Neema moving a follow-up into the approval queue (actions.py `_notify`,
     * type `planned_action`) and a hub event (which can close a deal as won)
     * arrive as notifications. The web toasts them and lets its 60 s poll pick
     * the change up; here the board reloads at once (800 ms, coalesced) while
     * it is on display — off-screen, the next visit reloads anyway.
     */
    private val onEvent = Coalescer(viewModelScope, ScreenLife.EVENT_WINDOW_MS) { load() }

    init {
        viewModelScope.launch { load() }
        viewModelScope.launch {
            dash.container.notifications.incoming.collect { n ->
                if (n.type in RELOAD_ON && life.active) onEvent.kick()
            }
        }
    }

    /**
     * Read the board, the won count and the queue together. Each part that
     * fails keeps what was on screen; true only when all of it was read.
     *
     * Loads never overlap: the poll, a burst of `planned_action` events, a
     * return to the screen and the reload after each send or veto share one
     * round trip ([SingleFlight]) — a load asked for while one is on the wire
     * waits for it and then reads once more, so it still sees the change that
     * prompted it. On a slow network the queue's live updates can't stack up
     * three requests per reason.
     */
    private suspend fun load(): Boolean = loads.run()

    fun reload() { viewModelScope.launch { load() } }

    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            load()
            _refreshing.value = false
        }
    }

    /**
     * PATCH a deal. The web toasts "Update failed" for anything; here the
     * reason is said, a deleted deal (404) leaves the board, and a failure
     * that may have landed (timeout, lost answer) is settled by re-reading the
     * board: [landed] reads the fresh board to say whether the change took.
     */
    private fun patchDeal(id: String, body: JsonObject, msg: String, landed: () -> Boolean, onSaved: () -> Unit = {}, onFailed: (String?) -> Unit = {}) {
        if (id in _patching.value) return
        _patching.value = _patching.value + id
        viewModelScope.launch {
            try {
                dash.api.deals.patch(id, body)
                onSaved()
                dash.toast(msg)
                load()
            } catch (e: Exception) {
                val f = dash.salesFailure(e)
                when {
                    f.kind == FailKind.NotFound -> {
                        onSaved()
                        dash.toast("This deal no longer exists — someone may have deleted it", ToastType.Error)
                        load()
                    }
                    f.mayHaveHappened -> {
                        val read = load()
                        when {
                            read && landed() -> { onSaved(); dash.toast(msg) }
                            read -> { val m = "Not saved — ${f.message().lowerFirst()}"; onFailed(m); dash.toast(m, ToastType.Error) }
                            else -> {
                                val m = "No answer from the server — it may not have saved. Pull down to check."
                                onFailed(m); dash.toast(m, ToastType.Error)
                            }
                        }
                    }
                    f.kind == FailKind.SessionExpired -> onFailed("Your session expired — sign in again, then save.")
                    else -> {
                        val m = "Update failed — ${f.message().lowerFirst()}"
                        onFailed(m); dash.toast(m, ToastType.Error)
                        if (f.kind == FailKind.Conflict) load()
                    }
                }
            } finally {
                _patching.value = _patching.value - id
            }
        }
    }

    /**
     * Save the open guidance. The web closes the editor at once, so a failed
     * save loses what was typed; here it closes when the save lands and stays
     * open, text intact, with the reason under it when it doesn't.
     */
    fun saveGuidance(id: String, guidance: String = _guidanceDraft.value) {
        _guidanceError.value = null
        patchDeal(
            id, buildJsonObject { put("guidance", guidance) }, "Guidance saved — Neema obeys it now",
            landed = { _deals.value?.find { it.id == id }?.guidance.orEmpty() == guidance },
            onSaved = { if (_editing.value == id) { _editing.value = null; _guidanceError.value = null } },
            onFailed = { m -> if (_editing.value == id) _guidanceError.value = m },
        )
    }

    /** Won / lost take the deal off the open board — it being gone is the sign it landed. */
    private fun closedOnBoard(id: String) = _deals.value?.none { it.id == id } == true

    fun markWon(id: String) =
        patchDeal(id, buildJsonObject { put("status", "won"); put("stage", "won") }, "Marked won 🎉", landed = { closedOnBoard(id) })

    fun markLost(id: String) =
        patchDeal(id, buildJsonObject { put("status", "lost"); put("stage", "lost") }, "Marked lost", landed = { closedOnBoard(id) })

    /** POST approve. Composing from the reason is a model turn, so it gets the long client; a ready draft doesn't. */
    private suspend fun approve(id: String, draft: String?) {
        val composes = draft == null && _actions.value?.find { it.id == id }?.draft.isNullOrBlank()
        if (!composes) { dash.api.actions.approve(id, draft); return }
        val http = dash.api.http
        http.decode<OkResponse>(http.raw("POST", "/admin/actions/$id/approve", http.jsonBody(JsonObject(emptyMap())), upload = true))
    }

    /**
     * Approve (send now) or veto a planned action. [draft] is the operator's
     * edited text; null sends Neema's own draft (or lets her compose one).
     *
     * A send puts words in front of a customer, so it must never go twice:
     * the row is locked from the first tap until the outcome is known. When
     * the answer is lost (timeout, dropped connection, a gateway error) the
     * send may well have gone, so it is never reported as failed — the queue
     * is re-read until the action leaves it (sent) or ~30 s pass (not sent).
     */
    fun act(id: String, verb: String, draft: String? = null) {
        if (id in _acting.value) return
        _acting.value = _acting.value + id
        if (_draftFor.value?.id == id) _draftError.value = null
        viewModelScope.launch {
            var settling = false
            try {
                if (verb == "approve") approve(id, draft?.trim()?.ifEmpty { null })
                else dash.api.actions.veto(id)
                resolved(id, verb)
                load()
            } catch (e: Exception) {
                val f = dash.salesFailure(e)
                when {
                    // crm.py approve_action: 409 "Action is sent|vetoed" when the
                    // scheduler (or a colleague) resolved it first. Nothing was sent
                    // twice; the queue reloads to show the truth.
                    f.kind == FailKind.Conflict -> {
                        closeDraft(id)
                        dash.toast(conflictText(verb, f), ToastType.Error)
                        load()
                    }
                    // 404 "Action not found" / "Conversation gone": it can't be sent any more.
                    f.kind == FailKind.NotFound -> {
                        closeDraft(id)
                        val why = if (f.detail == "Conversation gone") "its conversation was deleted" else "someone else removed it"
                        dash.toast("This follow-up is gone — $why", ToastType.Error)
                        load()
                    }
                    f.mayHaveHappened -> { settling = true; settle(id, verb, f) }
                    // The session dialog is up; the dialog keeps the text for a retry after sign-in.
                    f.kind == FailKind.SessionExpired -> failedAct(id, "Your session expired — sign in again, then send.", toast = false)
                    else -> failedAct(id, "${couldnt(verb)} — ${f.message().lowerFirst()}")
                }
            } finally {
                if (!settling) _acting.value = _acting.value - id
            }
        }
    }

    private fun resolved(id: String, verb: String) {
        closeDraft(id, clearText = true)
        left[id] = ++gen
        _actions.value = _actions.value?.filterNot { it.id == id }
        dash.toast(if (verb == "approve") "Sent ✓" else "Vetoed")
    }

    private fun closeDraft(id: String, clearText: Boolean = false) {
        if (_draftFor.value?.id == id) { _draftFor.value = null; _draftError.value = null }
        if (clearText && draftTextFor == id) { draftTextFor = null; _draftText.value = "" }
    }

    /** A failure the operator must see: in the open dialog when it's this action's, else a toast. */
    private fun failedAct(id: String, message: String, toast: Boolean = true) {
        if (_draftFor.value?.id == id) _draftError.value = message
        else if (toast) dash.toast(message, ToastType.Error)
    }

    private fun conflictText(verb: String, f: SalesFailure): String = when (f.detail) {
        "Action is sent" -> "Already sent — nothing was sent twice"
        "Action is vetoed" -> "Already vetoed — nothing was sent"
        else -> "${couldnt(verb)} — ${f.message().lowerFirst()}"
    }

    private fun couldnt(verb: String) = if (verb == "approve") "Couldn't send" else "Couldn't veto"

    /** Learn whether a send/veto whose answer was lost actually happened. The row stays locked throughout. */
    private suspend fun settle(id: String, verb: String, f: SalesFailure) {
        _checking.value = _checking.value + id
        try {
            val went = if (verb == "approve") "sent" else "vetoed"
            if (_draftFor.value?.id == id) _draftError.value = "No answer from the server — checking whether it was $went…"
            else dash.toast("No answer from the server — checking whether it was $went…", ToastType.Info)
            var readOnce = false
            repeat(SETTLE_READS) { i ->
                if (i > 0) delay(SETTLE_MS)
                val list = try { dash.api.actions.list() } catch (e: CancellationException) { throw e } catch (e: Exception) { null }
                if (list != null) {
                    readOnce = true
                    if (list.none { it.id == id }) {
                        resolved(id, verb)
                        load()
                        return
                    }
                    _actions.value = list
                }
            }
            val msg = if (readOnce) {
                if (verb == "approve") "Not sent — the server never confirmed it. You can send it again."
                else "Not vetoed — the server never confirmed it. You can try again."
            } else {
                if (verb == "approve") "Couldn't confirm whether it was sent — the server can't be reached. Open the chat to see whether it went before sending again."
                else "Couldn't confirm the veto — the server can't be reached. Pull down to check before trying again."
            }
            failedAct(id, msg)
        } finally {
            _checking.value = _checking.value - id
            _acting.value = _acting.value - id
        }
    }
}
