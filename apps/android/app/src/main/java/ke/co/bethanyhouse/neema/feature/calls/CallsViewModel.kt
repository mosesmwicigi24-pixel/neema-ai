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
    /** null while the first load is in flight (or it failed) — the panel reads "Loading…". */
    val data: CallTranscript? = null,
    val showFull: Boolean = false,
    val busy: Boolean = false,
    val err: String? = null,
)

/**
 * State for the Calls console (components/views/CallsView.tsx): the call log
 * (polled every 60s as a fallback, reloaded 500ms after any call WS event),
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

    /** Clicking the "N missed" badge filters to missed calls only. */
    val missedOnly = MutableStateFlow(false)

    /** Clicking a call opens the caller's full CRM panel right here. */
    val selected = MutableStateFlow<Call?>(null)

    private val _transcript = MutableStateFlow<TranscriptUi?>(null)
    val transcript: StateFlow<TranscriptUi?> = _transcript.asStateFlow()
    private var transcriptPoll: Job? = null

    init {
        load()
        // The WS handler below reloads on call events; this is only the
        // missed-event fallback, so a slow cadence is enough.
        viewModelScope.launch {
            val fg = NeemaApplication.instance.foreground
            while (isActive) {
                delay(60_000)
                if (!fg.value) fg.first { it }
                load()
            }
        }
        viewModelScope.launch {
            dash.container.socket.events.collect { e ->
                val t = e.str("type")
                if (t == "incoming_call" || t == "call_ended") launch { delay(500); load() }
            }
        }
    }

    fun load() {
        viewModelScope.launch {
            _calls.value = runCatching { api.calls.list() }.getOrElse { if (_calls.value == null) emptyList() else _calls.value }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            runCatching { api.calls.list() }
                .onSuccess { _calls.value = it }
                .onFailure { dash.toast(dash.errorText(it), ToastType.Error) }
            _refreshing.value = false
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
            val fg = NeemaApplication.instance.foreground
            while (isActive) {
                delay(5_000)
                val cur = _transcript.value ?: break
                if (cur.callId != callId) break
                val st = cur.data?.status
                if ((st == "pending" || st == "processing") && fg.value) loadTranscript(callId)
            }
        }
    }

    private suspend fun fetchTranscript(callId: String) {
        val d = runCatching { api.calls.transcript(callId) }.getOrNull()
        _transcript.value = _transcript.value?.takeIf { it.callId == callId }?.copy(data = d)
    }

    private fun loadTranscript(callId: String) { viewModelScope.launch { fetchTranscript(callId) } }

    fun toggleFull() { _transcript.value = _transcript.value?.let { it.copy(showFull = !it.showFull) } }

    fun runTranscribe() {
        val cur = _transcript.value ?: return
        val id = cur.callId
        viewModelScope.launch {
            _transcript.value = cur.copy(busy = true, err = null)
            try {
                api.calls.transcribe(id)
                fetchTranscript(id)
            } catch (e: Exception) {
                val msg = if (e is ApiException && e.status == 409) "Turn on transcription on the server first (WHISPER_ENABLED)."
                else "Couldn't start transcription."
                _transcript.value = _transcript.value?.takeIf { it.callId == id }?.copy(err = msg)
            } finally {
                _transcript.value = _transcript.value?.takeIf { it.callId == id }?.copy(busy = false)
            }
        }
    }

    // ── Call back (the caller strip) ─────────────────────────────────────────
    /**
     * Places a WhatsApp call to this caller; with no call permission yet it
     * asks the customer for it automatically, like the web's customer panel.
     */
    fun callBack(c: Call) {
        val wa = c.waId ?: return
        viewModelScope.launch {
            val r = dash.container.calls.initiateCall(wa, c.name)
            if (r.isSuccess) return@launch
            val msg = r.exceptionOrNull()?.message ?: "Couldn't place the call"
            if (msg.contains("permission", ignoreCase = true)) {
                dash.container.calls.requestPermission(wa)
                    .onSuccess {
                        val first = c.name?.split(" ")?.firstOrNull()?.takeIf { it.isNotBlank() } ?: "them"
                        dash.toast("Asked $first for permission to call — you can call once they tap Allow.")
                    }
                    .onFailure { dash.toast("Couldn't send the call request", ToastType.Error) }
            } else dash.toast(msg, ToastType.Error)
        }
    }

    /** Relative time, recomputed on each recomposition. */
    fun ago(iso: String?): String = if (iso == null) "" else Fmt.timeAgo(iso)
}
