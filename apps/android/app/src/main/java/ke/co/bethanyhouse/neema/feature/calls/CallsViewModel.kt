package ke.co.bethanyhouse.neema.feature.calls

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallTranscript
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ws.str
import ke.co.bethanyhouse.neema.feature.orders.recheckAccess
import ke.co.bethanyhouse.neema.core.util.SingleFlight
import ke.co.bethanyhouse.neema.core.util.SavesUi
import ke.co.bethanyhouse.neema.core.util.str
import ke.co.bethanyhouse.neema.core.util.ScreenLife
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** The expandable transcript + AI summary panel's state for the open call row. */
data class TranscriptUi(
    val callId: String,
    /** null while the first load is in flight (or it failed: see [loadErr]) — the panel reads "Loading…". */
    val data: CallTranscript? = null,
    /** The transcript could not be fetched and there is nothing to show: the panel offers Retry. */
    val loadErr: String? = null,
    val showFull: Boolean = false,
    val busy: Boolean = false,
    val err: String? = null,
)

/**
 * State for the Calls view (components/views/CallsView.tsx, CALLING_UX.md §7):
 * the call log (polled every 60s as a fallback, reloaded 500ms after call WS
 * events — a burst coalesces into one reload — at once when the socket
 * reconnects or the app returns to the foreground, and a `call_update` row
 * merged in place without a read), the All / Follow-ups filter, the selected
 * call's details, and the open transcript panel (lazily fetched, polled every
 * 5s while a transcription job runs). From a row: call back, and mark a
 * follow-up done.
 */
class CallsViewModel(private val dash: DashboardViewModel) : ViewModel(), SavesUi {
    companion object {
        /** The web's fallback interval (the socket frames are the real path). */
        const val POLL_MS = 60_000L
        /** CallsView's `setTimeout(load, 500)` after a call frame. */
        const val FRAME_RELOAD_MS = 500L
        const val TRANSCRIPT_POLL_MS = 5_000L
    }

    private val api = dash.api

    private val _calls = MutableStateFlow<List<Call>?>(null)
    /** null = still loading (the web's `calls === null`). */
    val calls: StateFlow<List<Call>?> = _calls.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _loadError = MutableStateFlow<String?>(null)
    /**
     * Why the last load of the log failed (null once one succeeds). The web
     * shows "No calls yet" when offline; here the log says it couldn't load,
     * keeps what it last had, and offers Retry.
     */
    val loadError: StateFlow<String?> = _loadError.asStateFlow()

    /** The "Follow-ups" filter: only the missed / callback calls nobody has returned yet. */
    val followUpsOnly = MutableStateFlow(false)

    /** The app filter (CallsView.tsx chFilter): "all" | "whatsapp" | "messenger". */
    val channelFilter = MutableStateFlow("all")

    /** Which channels can call now (the softphone's read of GET /calls/channels). */
    val channels = dash.container.calls.channels

    /**
     * A call back goes out on the call's own app — Messenger only while it can
     * call (the server's switch), WhatsApp whenever there is a number.
     */
    fun canCallBack(c: Call): Boolean =
        if (channelOf(c.channel) == MESSENGER) !c.externalId.isNullOrEmpty() && channels.value?.messenger?.outbound == true
        else !c.waId.isNullOrEmpty()

    /** Follow-ups being marked done (their button waits; a second tap sends nothing). */
    private val _doneBusy = MutableStateFlow<Set<String>>(emptySet())
    val doneBusy: StateFlow<Set<String>> = _doneBusy.asStateFlow()

    /** Clicking a call opens the caller's full CRM panel right here. */
    val selected = MutableStateFlow<Call?>(null)

    private val _transcript = MutableStateFlow<TranscriptUi?>(null)
    val transcript: StateFlow<TranscriptUi?> = _transcript.asStateFlow()
    private var transcriptPoll: Job? = null

    /** The reload a burst of call frames coalesces into (the web schedules one per frame). */
    private var frameReload: Job? = null

    /**
     * The log's reads, one on the wire at a time: the 60s tick, a burst of
     * call frames, a reconnect, a return to the app, a pull and a Retry share
     * round trips on a slow network instead of stacking (a read asked for
     * while one is in flight is the next one, so it still sees what prompted it).
     */
    private val reads = SingleFlight(viewModelScope) {
        val r = runCatching { api.calls.list() }
        land(r)
        r.isSuccess
    }

    /**
     * CallsView's lifecycle. The web's view unmounts when you leave it, which
     * stops its 60s interval and its socket handler; this ViewModel outlives
     * the screen, so it does the same through [ScreenLife]: the fallback tick
     * runs only while the log is on display and the app in front, and coming
     * back to it (or to the app), or the socket reconnecting, reloads at once.
     */
    val life = ScreenLife(
        viewModelScope, dash.foreground, dash.container.socket.connected,
        pollMs = POLL_MS, catchUpWindowMs = 0L,
        poll = { reads.run() }, catchUp = { reads.run() },
    )

    init {
        load()
        // Call frames reload the log 500ms later (a burst is one reload) while
        // it is on display; off-screen, the next visit catches up anyway.
        viewModelScope.launch {
            dash.container.socket.events.collect { e -> ke.co.bethanyhouse.neema.core.crash.contained("calls-frame") {
                val t = e.str("type")
                // A changed row arrives whole: merged in place, no read.
                if (t == "call_update") { (e["call"] as? kotlinx.serialization.json.JsonObject)?.let(::mergeRow); return@collect }
                if ((t == "incoming_call" || t == "call_ended" || t == "call_answered") && life.active && frameReload?.isActive != true) {
                    frameReload = launch { delay(FRAME_RELOAD_MS); reads.run() }
                }
            } }
        }
    }

    fun load() { viewModelScope.launch { reads.run() } }

    /**
     * A `call_update` row: replaces its row where it is; a row the log doesn't
     * hold goes in at its place by time (the log is newest first). An update
     * for a call older than everything shown (a transcript or follow-up on an
     * old call) is left for the next read — heading the log with it broke the
     * day grouping (the same day twice) and crashed the Calls screen.
     */
    internal fun mergeRow(raw: kotlinx.serialization.json.JsonObject) {
        val row = runCatching { ke.co.bethanyhouse.neema.core.net.NeemaJson.decodeFromJsonElement(Call.serializer(), raw) }.getOrNull() ?: return
        if (row.callId.isEmpty()) return
        val cur = _calls.value ?: return
        _calls.value = if (cur.any { it.callId == row.callId }) cur.map { if (it.callId == row.callId) row else it }
            else insertByTime(cur, row) ?: cur
        if (selected.value?.callId == row.callId) selected.value = row
    }

    /**
     * "Mark follow-up done": off the Follow-ups list at once; put back, with the
     * reason, if the server says no (a timeout may have landed — the next read
     * shows the truth).
     */
    fun markFollowUpDone(call: Call) {
        // The row as it is now (the caller may hold one from before an earlier tap).
        val c = _calls.value?.find { it.callId == call.callId } ?: call
        if (!c.followUpOpen || c.callId in _doneBusy.value) return
        _doneBusy.value = _doneBusy.value + c.callId
        fun set(open: Boolean) {
            _calls.value = _calls.value?.map { if (it.callId == c.callId) it.copy(followUpOpen = open) else it }
            selected.value?.takeIf { it.callId == c.callId }?.let { selected.value = it.copy(followUpOpen = open) }
        }
        set(false)
        viewModelScope.launch {
            try {
                api.calls.followUpDone(c.callId)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.status == 0 && e.body.startsWith("timed out")) reads.run()
                else {
                    set(true)
                    dash.toast(actionErrorText(e, "mark the follow-up done"), ToastType.Error)
                }
            } finally {
                _doneBusy.value = _doneBusy.value - c.callId
            }
        }
    }

    /** The row's call button / "Call back": a call to them now on the call's own app (the call screen says the rest). */
    fun callBack(c: Call) {
        if (!canCallBack(c)) return
        val handle = callHandle(c).takeIf { it.isNotEmpty() } ?: return
        viewModelScope.launch {
            val err = dash.container.calls.initiateCall(handle, c.name, c.conversationId, channelOf(c.channel)).exceptionOrNull() ?: return@launch
            if ((err as? CallManager.CallError)?.shown == true) return@launch
            dash.toast(err.message?.ifBlank { null } ?: "Couldn't place the call", ToastType.Error)
        }
    }

    /** Pull-to-refresh / Retry: the spinner shows until the answer (or the failure) is in. */
    fun refresh() {
        if (_refreshing.value) return
        _refreshing.value = true
        viewModelScope.launch {
            try { reads.run() } finally { _refreshing.value = false }
        }
    }

    /**
     * One answer lands (reads never overlap, so it is the newest). A failure
     * never clears the rows already on screen; a first load that fails leaves
     * an empty log with the reason and a Retry.
     */
    private fun land(r: Result<List<Call>>) {
        r.exceptionOrNull()?.let { if (it is kotlinx.coroutines.CancellationException) throw it }
        r.onSuccess { list ->
            _calls.value = list
            _loadError.value = null
            // The open caller follows the log: a restored one is found again,
            // an open one shows its row as it is now.
            val want = (pendingSelect ?: selected.value?.id)?.takeIf { it.isNotEmpty() }
            if (want != null) {
                pendingSelect = null
                list.find { it.id == want }?.let { selected.value = it }
            }
        }.onFailure { e ->
            // The server never refuses the log by role today (admin.py `list_calls`
            // only needs a signed-in agent); if it ever does, re-read who we are.
            if ((e as? ApiException)?.status == 403) dash.recheckAccess()
            if (_calls.value == null) _calls.value = emptyList()
            _loadError.value = callsErrorText(e)
        }
    }

    /**
     * Deep-link focus (`?view=calls&caller=<wa_id>`, a missed-call alert):
     * open the caller panel for that customer. The log on hand may be minutes
     * old — the alert is usually about a call it doesn't hold yet — so when
     * it has no call with them it is read again before saying so. A read that
     * fails says nothing false ("no calls yet"): the log's own error shows.
     */
    fun consumeFocus(key: String) {
        if (focusing == key) return
        val wa = key.removePrefix("+")
        fun match(list: List<Call>) = list.sortedByDescending { it.startedAt ?: "" }.find { it.waId == wa || it.externalId == wa }
        _calls.value?.let(::match)?.let { selected.value = it; dash.callsFocusKey.value = null; return }
        focusing = key
        viewModelScope.launch {
            try {
                val read = reads.run()
                if (dash.callsFocusKey.value != key) return@launch   // another link came meanwhile
                val found = _calls.value?.let(::match)
                when {
                    found != null -> selected.value = found
                    read -> dash.toast("No calls with this customer yet — showing the full call log.", ToastType.Warning)
                }
                dash.callsFocusKey.value = null
            } finally {
                if (focusing == key) focusing = null
            }
        }
    }
    private var focusing: String? = null

    fun select(c: Call?) { selected.value = c; pendingSelect = null }

    // ── Process death: the Follow-ups filter and the open call come back ─────
    override var uiAttached = false
    /** A caller restored before the log has loaded: opened once the row is read. */
    private var pendingSelect: String? = null

    override fun saveUi(): Map<String, Any?> = mapOf(
        "followUps" to followUpsOnly.value, "selected" to (selected.value?.id ?: pendingSelect),
        "channel" to channelFilter.value,
    )

    override fun restoreUi(saved: Map<String, Any?>) {
        (saved["followUps"] as? Boolean)?.let { followUpsOnly.value = it }
        (saved["channel"] as? String)?.takeIf { it in setOf("all", WHATSAPP, MESSENGER) }?.let { channelFilter.value = it }
        val id = saved.str("selected") ?: return
        val row = _calls.value?.find { it.id == id }
        if (row != null) selected.value = row else pendingSelect = id
    }

    // ── Transcript panel ─────────────────────────────────────────────────────
    /** The panel's Retry after a failed first load. */
    fun retryTranscript() {
        val cur = _transcript.value ?: return
        _transcript.value = cur.copy(loadErr = null)
        loadTranscript(cur.callId)
    }

    fun toggleTranscript(callId: String) {
        if (_transcript.value?.callId == callId) {
            transcriptPoll?.cancel(); _transcript.value = null
            return
        }
        transcriptPoll?.cancel()
        _transcript.value = TranscriptUi(callId)
        loadTranscript(callId)
        transcriptPoll = viewModelScope.launch {
            // A transcription job takes ~1-2 min — 5s resolution is plenty, and
            // neither a backgrounded app nor another screen keeps polling for it.
            // Each fetch finishes before the next wait starts: on a slow network
            // the polls never stack.
            while (isActive) {
                delay(TRANSCRIPT_POLL_MS)
                val cur = _transcript.value ?: break
                if (cur.callId != callId) break
                val st = cur.data?.status
                if ((st == "pending" || st == "processing") && life.active) fetchTranscript(callId)
            }
        }
    }

    /**
     * One fetch. A failure keeps what the panel already shows (a flaky poll
     * mid-transcription must not wipe the status and stop the polling); with
     * nothing to show yet it says why and offers Retry instead of "Loading…"
     * forever (the web's behaviour).
     */
    private suspend fun fetchTranscript(callId: String) {
        val r = runCatching { api.calls.transcript(callId) }
        r.exceptionOrNull()?.let { if (it is kotlinx.coroutines.CancellationException) throw it }
        val cur = _transcript.value?.takeIf { it.callId == callId } ?: return
        _transcript.value = r.fold(
            onSuccess = { cur.copy(data = it, loadErr = null) },
            onFailure = { e ->
                if (cur.data != null) cur
                else cur.copy(loadErr = if (e is ApiException && e.status == 404) "This call is no longer in the log." else actionErrorText(e, "load the transcript"))
            },
        )
    }

    private fun loadTranscript(callId: String) { viewModelScope.launch { fetchTranscript(callId) } }

    fun toggleFull() { _transcript.value = _transcript.value?.let { it.copy(showFull = !it.showFull) } }

    fun runTranscribe() {
        val cur = _transcript.value ?: return
        if (cur.busy) return   // one request at a time, however fast the taps
        val id = cur.callId
        _transcript.value = cur.copy(busy = true, err = null)
        viewModelScope.launch {
            try {
                api.calls.transcribe(id)
                fetchTranscript(id)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                if (e is ApiException && e.status == 0) {
                    // No answer: the job may have started anyway. Show the truth.
                    fetchTranscript(id)
                    val st = _transcript.value?.takeIf { it.callId == id }?.data?.status
                    if (st == "pending" || st == "processing") return@launch
                }
                // routers/admin.py calls_transcribe raises 409 for two reasons; the
                // web shows the WHISPER copy for both, which misleads when the call
                // simply has no recording.
                val msg = when {
                    e is ApiException && e.status == 409 && e.detail.startsWith("No recording") ->
                        "No recording was captured for this call."
                    e is ApiException && e.status == 409 -> "Turn on transcription on the server first (WHISPER_ENABLED)."
                    e is ApiException && e.status == 0 -> actionErrorText(e, "start transcription")
                    e is ApiException && e.status == 429 -> "Too many requests — wait a moment and try again."
                    else -> "Couldn't start transcription."
                }
                _transcript.value = _transcript.value?.takeIf { it.callId == id }?.copy(err = msg)
            } finally {
                _transcript.value = _transcript.value?.takeIf { it.callId == id }?.copy(busy = false)
            }
        }
    }

    /**
     * Plain words for a failed request: never a raw HTML error page. The
     * server's detail is used only when it is written for people.
     */
    internal fun callsErrorText(e: Throwable, fallback: String = "Couldn't load calls."): String {
        val a = e as? ApiException ?: return fallback
        return when {
            a.status == 0 && a.body.startsWith("timed out") -> "The server took too long to answer — try again."
            a.status == 0 -> "No connection — check your internet and try again."
            a.status == 401 -> "Your session expired — sign in again."
            a.status == 403 -> "You don't have access to calls."
            a.status == 429 -> "Too many requests — wait a moment and try again."
            a.status >= 500 -> "The server had a problem — try again shortly."
            else -> fallback
        }
    }

    /** "No connection — couldn't load the transcript.": the failure, and what it stopped. */
    internal fun actionErrorText(e: Throwable, action: String): String {
        val a = e as? ApiException ?: return "Couldn't $action."
        return when {
            a.status == 0 && a.body.startsWith("timed out") -> "The server took too long — couldn't $action."
            a.status == 0 -> "No connection — couldn't $action."
            a.status == 401 -> "Your session expired — sign in again."
            a.status == 429 -> "Too many requests — wait a moment and try again."
            a.status >= 500 -> "The server had a problem — couldn't $action."
            else -> "Couldn't $action."
        }
    }

    /** Relative time, recomputed on each recomposition. */
    fun ago(iso: String?): String = if (iso == null) "" else Fmt.timeAgo(iso)
}

/**
 * [row] placed among [rows] (newest first) by its start time. Older than every
 * row held: appended while the log is shorter than a page (it holds every
 * call), else null — it belongs to a page not shown and the next read has it.
 */
internal fun insertByTime(rows: List<Call>, row: Call, page: Int = CALL_LOG_PAGE): List<Call>? {
    val t = ke.co.bethanyhouse.neema.core.util.Fmt.millis(row.startedAt)
    val at = if (t == null) -1
        else rows.indexOfFirst { (ke.co.bethanyhouse.neema.core.util.Fmt.millis(it.startedAt) ?: Long.MIN_VALUE) <= t }
    return when {
        at >= 0 -> rows.subList(0, at) + row + rows.subList(at, rows.size)
        rows.size < page -> rows + row
        else -> null
    }
}

/** GET /admin/calls answers the newest 50 by default. */
internal const val CALL_LOG_PAGE = 50
