package ke.co.bethanyhouse.neema.feature.reports

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.ConversationPage
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.app.AppContainer
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.util.AppClock
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

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
 * Where CPU-heavy derivation runs: [Dispatchers.Default] in the app, inline
 * when the container's I/O is synchronous (tests), so a screenshot or a
 * behaviour test sees the result in the same frame.
 */
internal val AppContainer.cpu: CoroutineDispatcher
    get() = if (config.io === Dispatchers.Unconfined) Dispatchers.Unconfined else Dispatchers.Default

/** The app's "now" as a [Clock] (pinned in tests through AppClock), in the phone's zone. */
internal object AppClockClock : Clock() {
    override fun getZone(): ZoneId = ZoneId.systemDefault()
    override fun withZone(zone: ZoneId?): Clock = fixed(instant(), zone)
    override fun instant(): Instant = AppClock.instant()
    override fun millis(): Long = AppClock.now()
}

/**
 * Reports aggregate a date range over EVERY conversation, so — like the web —
 * this screen fetches the full (un-paged) list itself, only while it is open.
 * Computing from the inbox's loaded rows would report on one page.
 *
 * The list runs to ~14,000 rows, so nothing is aggregated in composition:
 * each row's timestamp is parsed once when the list lands, and the report for
 * the chosen range is built on a background thread ([report]); changing the
 * range keeps the last report on screen until the new one is ready.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ReportsViewModel(
    private val dash: DashboardViewModel,
    /** "Now" for the date range, the per-day charts and "3h ago" (fixed in tests). */
    val clock: Clock = AppClockClock,
) : ViewModel(), KeepsUiState {
    private val cpu = dash.container.cpu

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

    /** Every conversation with its date parsed once (not once per range change). */
    private val datedConvs = _allConvs.map { list -> list?.let(::datedConversations) }.flowOn(cpu)

    private val datedOrders = dash.orders.map(::datedOrders).flowOn(cpu)

    private data class Inputs(
        val convs: List<Dated<Conversation>>?, val orders: List<Dated<Order>>, val agents: List<Agent>,
        val range: ReportRange, val from: LocalDate?, val to: LocalDate?,
    )

    /**
     * The report for the chosen range, built off the main thread; null until
     * the first one is ready (the screen shows its loading state, never zeros).
     */
    val report: StateFlow<Report?> =
        combine(
            datedConvs, datedOrders, dash.agents, range,
            combine(customFrom, customTo) { f, t -> f to t },
        ) { convs, orders, agents, r, (f, t) -> Inputs(convs, orders, agents, r, f, t) }
            .mapLatest { i ->
                i.convs?.let { buildReportDated(it, i.orders, i.agents, i.range, i.from, i.to, clock.millis(), clock.zone) }
            }
            .flowOn(cpu)
            .stateIn(viewModelScope, SharingStarted.Eagerly, null)

    private val _exporting = MutableStateFlow(false)
    /** A CSV is being written: a second tap doesn't start another. */
    val exporting: StateFlow<Boolean> = _exporting.asStateFlow()

    /** A written CSV waiting for the share sheet (see [exportCsv]). */
    data class ReadyExport(val file: File, val range: ReportRange)

    private val _readyExport = MutableStateFlow<ReadyExport?>(null)
    /**
     * The CSV the share sheet should open with, until the screen has opened
     * it ([exportShown]). Held here rather than passed to a callback so an
     * export that finishes while the phone rotates, or while the app is in
     * the background, still reaches the share sheet: whichever screen is on
     * display when it is ready (or when the agent comes back) opens it.
     */
    val readyExport: StateFlow<ReadyExport?> = _readyExport.asStateFlow()

    init { load() }

    /**
     * Writes the report's orders as CSV into [dir] on the I/O thread (streamed
     * row by row, never one giant string), then offers it as [readyExport]
     * for the share sheet. A write failure is a toast; a tap while one is
     * being written (or waiting to be shared) is ignored.
     */
    fun exportCsv(dir: File) {
        val r = report.value ?: return
        if (_exporting.value || _readyExport.value != null) return
        val range = range.value
        _exporting.value = true
        viewModelScope.launch {
            try {
                val file = withContext(dash.container.config.io) { writeReportCsv(dir, r.orders, range) }
                _readyExport.value = ReadyExport(file, range)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                dash.toast(exportFailureText(e), ToastType.Error)
            } finally { _exporting.value = false }
        }
    }

    /** The screen opened the share sheet for [ready] (or failed to, and said so). */
    fun exportShown(ready: ReadyExport) { _readyExport.compareAndSet(ready, null) }

    // ── Process death ─────────────────────────────────────────────────────────

    override fun saveUi(): String = kotlinx.serialization.json.buildJsonObject {
        put("tab", kotlinx.serialization.json.JsonPrimitive(tab.value.name))
        put("range", kotlinx.serialization.json.JsonPrimitive(range.value.name))
        customFrom.value?.let { put("from", kotlinx.serialization.json.JsonPrimitive(it.toString())) }
        customTo.value?.let { put("to", kotlinx.serialization.json.JsonPrimitive(it.toString())) }
        // A CSV being written (or not yet shared) is lost with the process: say so on return.
        if (_exporting.value || _readyExport.value != null) put("exporting", kotlinx.serialization.json.JsonPrimitive(true))
    }.toString()

    override fun restoreUi(saved: String) {
        val o = runCatching { NeemaJson.parseToJsonElement(saved) as kotlinx.serialization.json.JsonObject }.getOrNull() ?: return
        fun str(k: String) = (o[k] as? kotlinx.serialization.json.JsonPrimitive)?.takeIf { it.isString }?.content
        str("tab")?.let { n -> ReportTab.entries.find { it.name == n } }?.let { tab.value = it }
        str("range")?.let { n -> ReportRange.entries.find { it.name == n } }?.let { range.value = it }
        str("from")?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.let { customFrom.value = it }
        str("to")?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.let { customTo.value = it }
        if ((o["exporting"] as? kotlinx.serialization.json.JsonPrimitive)?.content == "true") exportInterrupted.value = true
    }

    /**
     * The app was closed by Android while a CSV was being written: nothing
     * reached the share sheet. The screen tells the agent once ([EXPORT_INTERRUPTED]).
     */
    val exportInterrupted = MutableStateFlow(false)

    /** The screen showed the [exportInterrupted] notice. */
    fun interruptionShown() {
        if (exportInterrupted.compareAndSet(true, false)) dash.toast(EXPORT_INTERRUPTED, ToastType.Warning)
    }

    private suspend fun fetch() {
        try {
            _allConvs.value = fetchEveryConversation(dash.api.http)
            _loadError.value = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            stillHere()
            dash.recheckAccessOn(e)
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

/** What the agent is told when the app was closed mid-export. */
internal const val EXPORT_INTERRUPTED = "Android closed Neema while the CSV was being prepared — tap Export CSV again."

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
    // The web's words, and why: the server refused this agent the full list.
    e.httpStatus() == 403 -> (e as ke.co.bethanyhouse.neema.core.net.ApiException).readableDetail()
        ?.takeUnless { it.equals("Not authenticated", true) || it.equals("Forbidden", true) }
        ?: "Could not load conversations for this report — you don't have permission to see them."
    else -> friendlyError(e, fallback = "Could not load conversations for this report.")
}
