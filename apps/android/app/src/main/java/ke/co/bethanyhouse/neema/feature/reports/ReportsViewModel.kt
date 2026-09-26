package ke.co.bethanyhouse.neema.feature.reports

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.ConversationPage
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer
import java.time.LocalDate

/** The web's `Range`. */
enum class ReportRange(val key: String, val label: String) {
    D7("7d", "Last 7 days"),
    D30("30d", "Last 30 days"),
    D90("90d", "Last 90 days"),
    Custom("custom", "Custom range"),
}

/** The web's `ReportTab`. */
enum class ReportTab(val label: String) {
    Overview("Overview"), Conversations("Conversations"), Orders("Orders"), Agents("Agents"),
}

/**
 * GET /admin/conversations with no `limit`: the legacy full list the API keeps
 * for Reports (admin.py `list_conversations` → `_conversation_rows()`).
 *
 * The server does NOT cap it: every conversation, ~14,000 rows / 13 MB in
 * production. The shared client's 30-second ceiling suits every other call
 * but would cut this download short on a phone link and the report would read
 * zero, so it runs on the long-call client (the one uploads use). Decoded
 * straight from the text, never through a JSON tree, and tolerant of the
 * paged `{items, next_cursor}` envelope should the server ever answer with it.
 */
internal suspend fun fetchEveryConversation(http: NeemaHttp): List<Conversation> {
    val body = http.raw("GET", "/admin/conversations", upload = true).trimStart()
    return when {
        body.startsWith("[") -> NeemaJson.decodeFromString(ListSerializer(Conversation.serializer()), body)
        body.startsWith("{") -> NeemaJson.decodeFromString(ConversationPage.serializer(), body).items
        // An empty 2xx is an empty list; anything else (a captive portal's HTML
        // page answering 200) is not a list of conversations, and reading it
        // as one would report zeros as if they were true.
        body.isEmpty() -> emptyList()
        else -> throw kotlinx.serialization.SerializationException("not a conversation list")
    }
}

/** A background refetch whose failure leaves the screen as it was (the dashboard's poller keeps trying). */
internal suspend fun quietly(block: suspend () -> Unit) {
    try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        // keep what is on screen
    }
}

/**
 * Reports aggregate a date range over EVERY conversation, so — like the web —
 * this screen fetches the full (un-paged) list itself, only while it is open.
 * Computing from the inbox's loaded rows would report on one page.
 */
class ReportsViewModel(private val dash: DashboardViewModel) : ViewModel() {

    private val _allConvs = MutableStateFlow<List<Conversation>?>(null)
    /** null while loading — never show zeros that look like real figures. */
    val allConvs: StateFlow<List<Conversation>?> = _allConvs.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _loadError = MutableStateFlow<String?>(null)
    /**
     * Why the last download failed, in plain words; null once one succeeds.
     * With no list yet the screen shows it with a Retry button instead of a
     * report of zeros (the web falls back to an empty list, so a failed
     * download there reads "0 conversations" as if it were true).
     */
    val loadError: StateFlow<String?> = _loadError.asStateFlow()

    val tab = MutableStateFlow(ReportTab.Overview)
    val range = MutableStateFlow(ReportRange.D30)
    val customFrom = MutableStateFlow<LocalDate?>(null)
    val customTo = MutableStateFlow<LocalDate?>(null)

    /** The download in flight: a pull-to-refresh joins it rather than starting a second full list. */
    private var fetchJob: Job? = null

    /**
     * ReportsView fetches the full list on mount — once per visit, never on a
     * timer (it is ~13 MB). This ViewModel outlives the screen, so each return
     * to it re-reads the list once (joining a download already in flight), the
     * report keeping its figures until the new list lands. No poll, and no
     * reload on returning to the app: the web doesn't either.
     */
    val life = ScreenLife(
        viewModelScope, dash.foreground, catchUpOnForeground = false, catchUp = { load().join() },
    )

    init { load() }

    private suspend fun fetch() {
        try {
            _allConvs.value = fetchEveryConversation(dash.api.http)
            _loadError.value = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            stillHere()
            // A refresh keeps the report already on screen and says so (the
            // web's toast); a first load shows the reason with a Retry button
            // — never a report of zeros.
            _loadError.value = reportLoadError(e)
            if (_allConvs.value != null) dash.toast("Could not load conversations for this report.", ToastType.Error)
        }
    }

    private fun load(): Job =
        (fetchJob?.takeIf { it.isActive } ?: viewModelScope.launch { fetch() }).also { fetchJob = it }

    /** The error panel's Retry: back to the loading state, then download again. */
    fun retry() {
        if (fetchJob?.isActive == true) return
        _loadError.value = null
        load()
    }

    /** Re-read the orders and agents the report is built from, and every conversation; the spinner lasts until all have landed. */
    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            try {
                coroutineScope {
                    launch { quietly { dash.refreshOrders() } }
                    launch { quietly { dash.refreshAgents() } }
                    load().join()
                }
            } finally { _refreshing.value = false }
        }
    }
}

/**
 * Why the full list didn't arrive. It is the largest download in the app, so
 * the two phone-network failures get their own words: the long client gave
 * up waiting, or the connection died mid-download (a truncated body).
 */
internal fun reportLoadError(e: Throwable): String = when {
    e.httpStatus() == 0 && e.isTimeout() ->
        "The download timed out — this report needs every conversation, a large download. Try again on a stronger connection."
    e is java.io.IOException && e !is ke.co.bethanyhouse.neema.core.net.ApiException ->
        "The download was cut off partway — try again on a stronger connection."
    e is kotlinx.serialization.SerializationException ->
        "The download arrived incomplete — try again on a stronger connection."
    else -> friendlyError(e, fallback = "Could not load conversations for this report.")
}
