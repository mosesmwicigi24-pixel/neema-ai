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
 * State for the Calls console (components/views/CallsView.tsx): the call log
 * (polled every 60s as a fallback, reloaded 500ms after call WS events —
 * a burst coalesces into one reload — and at once when the socket
 * reconnects or the app returns to the foreground),
 * the missed-only filter, the selected caller, and the open transcript panel
 * (lazily fetched, polled every 5s while a transcription job runs).
 */
class CallsViewModel(private val dash: DashboardViewModel) : ViewModel() {
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

    /** Clicking the "N missed" badge filters to missed calls only. */
    val missedOnly = MutableStateFlow(false)

    /** Clicking a call opens the caller's full CRM panel right here. */
    val selected = MutableStateFlow<Call?>(null)

    private val _transcript = MutableStateFlow<TranscriptUi?>(null)
    val transcript: StateFlow<TranscriptUi?> = _transcript.asStateFlow()
    private var transcriptPoll: Job? = null

    /** The reload a burst of call frames coalesces into (the web schedules one per frame). */
    private var frameReload: Job? = null
    /** Bumped per load: only the newest request's answer lands, so a slow older one can't roll the log back. */
    private var loadSeq = 0
    /** The request whose log is on screen. */
    private var shownSeq = 0

    init {
        load()
        // The WS handler below reloads on call events; this is only the
        // missed-event fallback, so a slow cadence is enough.
        viewModelScope.launch {
            val fg = dash.foreground
            while (isActive) {
                delay(60_000)
                // Backgrounded: no ticks. Coming back reloads (below), then the clock restarts.
                if (!fg.value) { fg.first { it }; continue }
                load()
            }
        }
        val socket = dash.container.socket
        viewModelScope.launch {
            socket.events.collect { e ->
                val t = e.str("type")
                if ((t == "incoming_call" || t == "call_ended") && frameReload?.isActive != true) {
                    frameReload = launch { delay(500); load() }
                }
            }
        }
        // Frames sent while the socket was down are lost: catch up the moment
        // it reconnects, and when the app comes back on screen (the web waits
        // for its next 60s tick).
        viewModelScope.launch {
            var was = socket.connected.value
            socket.connected.collect { c -> if (c && !was) load(); was = c }
        }
        viewModelScope.launch {
            var was = dash.foreground.value
            dash.foreground.collect { fg -> if (fg && !was) load(); was = fg }
        }
    }

    fun load() {
        val seq = ++loadSeq
        viewModelScope.launch { land(seq, runCatching { api.calls.list() }) }
    }

    /** Pull-to-refresh / Retry: the spinner shows until the answer (or the failure) is in. */
    fun refresh() {
        if (_refreshing.value) return
        _refreshing.value = true
        val seq = ++loadSeq
        viewModelScope.launch {
            try { land(seq, runCatching { api.calls.list() }) } finally { _refreshing.value = false }
        }
    }

    /**
     * One answer lands. A log newer than the one shown replaces it (an older
     * one arriving late can't roll it back). A failure is reported only if it
     * was the newest request, and never clears the rows already on screen; a
     * first load that fails leaves an empty log with the reason and a Retry.
     */
    private fun land(seq: Int, r: Result<List<Call>>) {
        r.exceptionOrNull()?.let { if (it is kotlinx.coroutines.CancellationException) throw it }
        r.onSuccess {
            if (seq > shownSeq) { shownSeq = seq; _calls.value = it }
            if (seq == loadSeq) _loadError.value = null
        }.onFailure { e ->
            if (seq != loadSeq) return
            if (_calls.value == null) _calls.value = emptyList()
            _loadError.value = callsErrorText(e)
        }
    }

    /**
     * Deep-link focus: once the log has loaded, open the caller panel for the
     * customer the link named. Waits for the list so a cold navigation doesn't
     * consume the key against an empty log.
     */
    fun consumeFocus(key: String) {
        val list = _calls.value ?: return
        val wa = key.removePrefix("+")
        val match = list.sortedByDescending { it.startedAt ?: "" }.find { it.waId == wa }
        if (match != null) selected.value = match
        else dash.toast("No calls with this customer yet — showing the full call log.", ToastType.Warning)
        dash.callsFocusKey.value = null
    }

    fun select(c: Call?) { selected.value = c }

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
            // a backgrounded app shouldn't keep polling for it.
            val fg = dash.foreground
            while (isActive) {
                delay(5_000)
                val cur = _transcript.value ?: break
                if (cur.callId != callId) break
                val st = cur.data?.status
                if ((st == "pending" || st == "processing") && fg.value) loadTranscript(callId)
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
