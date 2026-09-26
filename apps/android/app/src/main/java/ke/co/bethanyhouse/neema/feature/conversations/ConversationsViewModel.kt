package ke.co.bethanyhouse.neema.feature.conversations

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.api.InboxQuery
import ke.co.bethanyhouse.neema.core.model.ActivityEvent
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.ConversationPage
import ke.co.bethanyhouse.neema.core.model.ConversationWindow
import ke.co.bethanyhouse.neema.core.model.InboxSummary
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.Fmt
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import java.io.ByteArrayOutputStream
import java.util.UUID

/** The paged inbox (hooks/useInbox.ts). */
data class InboxUi(
    /** Every row ever loaded — for LOOKUPS (the open thread, identities, deep links). */
    val cache: Map<String, Conversation> = emptyMap(),
    /** Which filter [orderIds] belongs to. */
    val orderKey: String = DEFAULT_KEY,
    /** What the current filter's server pages returned — what the LIST shows. */
    val orderIds: List<String> = emptyList(),
    val filters: InboxQuery = InboxQuery(),
    val summary: InboxSummary? = null,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val hasMore: Boolean = false,
    /** Page one has come from the SERVER this session (not just a snapshot). */
    val freshLoaded: Boolean = false,
    /**
     * The current filter's first page FAILED. The web says "Loading…" forever
     * here; the app keeps that copy while a request is in flight and offers a
     * quiet "Couldn't load — Retry" once one has failed.
     */
    val loadError: Boolean = false,
    /** Why the last page-one load failed, in plain words (no connection, server down…). */
    val errorText: String? = null,
    /**
     * The next page failed. Auto-paging stops (it would retry in a tight loop
     * while offline) until the agent taps Retry or a refresh succeeds.
     */
    val moreError: Boolean = false,
)

/** List chrome: search box text, filter panel, bulk selection. */
data class ListUi(
    val search: String = "",
    val showFilters: Boolean = false,
    val selectMode: Boolean = false,
    val selected: Set<String> = emptySet(),
    val bulkBusy: Boolean = false,
)

data class ThreadUi(
    val activeId: String = "",
    /** Phone layout: the thread is the full screen (web `mobilePanel === "thread"`). */
    val threadOpen: Boolean = false,
    val messages: Map<String, List<ThreadMsg>> = emptyMap(),
    val hasMore: Map<String, Boolean> = emptyMap(),
    val loading: Boolean = false,
    val error: Boolean = false,
    /** Why the open thread failed to load, in plain words. */
    val errorText: String? = null,
    /** The conversation whose older page is being fetched ("" = none). */
    val olderLoading: String = "",
    /** The conversation whose older page failed — offers a tap to retry. */
    val olderError: String = "",
    /** Unread count when each thread was opened — places the "N new" divider. */
    val unreadSnapshot: Map<String, Int> = emptyMap(),
    val window: ConversationWindow? = null,
    val activity: List<ActivityEvent> = emptyList(),
    val activityOpen: Boolean = false,
    /**
     * Per conversation: "intercept" | "release" | "pause" while that control is
     * in flight — exactly-once clicks, and a slow claim on one thread never
     * greys out the controls of the next one opened.
     */
    val busy: Map<String, String> = emptyMap(),
    /** Media re-fetched from Meta this session, by message id. */
    val recovered: Map<String, String> = emptyMap(),
    /**
     * The open person's CRM profile, as far as the thread menu needs it
     * (CustomerSidebar's invite rule): their captured phone and whether a
     * real WhatsApp thread exists. Null until loaded.
     */
    val reach: Reach? = null,
)

/** GET /admin/customers/{key}?channel= (crm.py) — phone + channels, for the invite shortcut. */
data class Reach(val convId: String, val phone: String?, val hasWhatsApp: Boolean)

data class ComposerUi(
    val replyText: String = "",
    /** Per-conversation translate toggle; absent = ON when the thread reads foreign. */
    val txMode: Map<String, Boolean> = emptyMap(),
    val txPreview: TxPreview? = null,
    val txBusy: Boolean = false,
    val quoted: Quoted? = null,
    val draftVisible: Boolean = false,
    val draftExpanded: Boolean = false,
    val draftText: String = "",
    val draftEditing: Boolean = false,
    val generatingDraft: Boolean = false,
    val media: List<PickedMedia> = emptyList(),
    val uploading: Boolean = false,
)

/** The control in flight on [id], or "". */
fun ThreadUi.busyFor(id: String): String = busy[id] ?: ""

/** What a reply / approval / note is, while it is on its way. */
internal enum class OutKind { Reply, Approve, Note }

/**
 * A send that has left the composer and is not yet confirmed. It lives until
 * the server's own row for it turns up (or it is edited away): a timeout
 * never loses the words and never becomes a second send.
 */
internal data class Outgoing(
    val localId: String,
    val convId: String,
    val kind: OutKind,
    /** What goes to the server — in the customer's language when translated. */
    val text: String,
    val replyToId: String? = null,
    val origText: String? = null,
    val origLang: String? = null,
    /** What the agent typed, for Edit. */
    val typed: String = text,
    val quoted: Quoted? = null,
    /** The thread's server rows when it was sent: its own row is a NEW one. */
    val known: Set<String>,
    /** The answer never came (timeout, dropped connection): checking the server. */
    val checking: Boolean = false,
    /** The last check has been made: an answer without its row settles it as failed. */
    val exhausted: Boolean = false,
    val failed: Boolean = false,
    /** Sent again by the agent: a second failure keeps the bubble, never re-opens the box. */
    val retried: Boolean = false,
)

data class DialogUi(
    val transfer: Boolean = false,
    val note: Boolean = false,
    val noteText: String = "",
    val clearConfirm: Boolean = false,
    val clearing: Boolean = false,
)

/**
 * The inbox screen's state: the paged conversation list (a port of
 * hooks/useInbox.ts), the open thread, its composer, and every conversation
 * action of ConversationsView.tsx.
 *
 * useInbox's three rules hold here too: the cache holds every row ever
 * loaded while [InboxUi.orderIds] says what the current filter shows; a
 * refresh MERGES; and the newest request wins (sequence numbers).
 */
class ConversationsViewModel(val dash: DashboardViewModel) : ViewModel() {
    private val api get() = dash.api
    private val inboxApi = InboxApi(dash.api.http)
    private val cr: ContentResolver get() = dash.container.context.contentResolver
    val myId: String? get() = dash.session.value?.agentId

    private val _inbox = MutableStateFlow(InboxUi())
    val inbox: StateFlow<InboxUi> = _inbox.asStateFlow()
    private val _list = MutableStateFlow(ListUi())
    val list: StateFlow<ListUi> = _list.asStateFlow()
    private val _thread = MutableStateFlow(ThreadUi())
    val thread: StateFlow<ThreadUi> = _thread.asStateFlow()
    private val _composer = MutableStateFlow(ComposerUi())
    val composer: StateFlow<ComposerUi> = _composer.asStateFlow()
    private val _dialogs = MutableStateFlow(DialogUi())
    val dialogs: StateFlow<DialogUi> = _dialogs.asStateFlow()

    /**
     * The people the list shows, grouped and sorted (filteredConvs → groupedConvs).
     * Grouping thousands of rows stays off the main thread — except when the
     * container runs I/O synchronously (tests, previews), where it is computed
     * in place so every frame is deterministic. The initial value is computed
     * synchronously either way, so the list never flashes empty on open.
     */
    val rows: StateFlow<List<RowGroup>> = combine(_inbox, dash.session) { s, sess -> buildRows(s, sess?.agentId) }
        .let { if (dash.container.config.io === Dispatchers.Unconfined) it else it.flowOn(Dispatchers.Default) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, buildRows(_inbox.value, dash.session.value?.agentId))

    // useInbox refs
    private var cursor: String? = null
    private var pages = 0
    private var firstSeq = 0
    private var moreSeq = 0
    private var revealed = listOf<String>()
    private var watched: String? = null
    private var seededFor: String? = null
    private var quietJob: Job? = null
    private var searchJob: Job? = null
    private var socketRefreshJob: Job? = null
    private var catchUpJob: Job? = null
    /** Alive for a moment after each refresh() — a catch-up right then needn't repeat it. */
    private var recentRefresh: Job? = null
    private var txJob: Job? = null
    private var draftJob: Job? = null
    private var windowJob: Job? = null
    private var activityJob: Job? = null

    /** Sends on their way, by bubble id (touched on the main thread only). */
    private val outgoing = LinkedHashMap<String, Outgoing>()
    /** Each thread's composer while another thread is open: text, quote, files, draft. */
    private val stash = HashMap<String, ComposerUi>()
    /** The newest load of each thread: an older answer landing last never flips its flags. */
    private val loadSeq = HashMap<String, Int>()
    private var localSeq = 0
    /** Drafts generated for a thread the agent had left: shown when it is opened again. */
    private val heldDrafts = HashMap<String, String>()
    /** A deep link that failed for want of a connection: tried again on reconnect. */
    private var retryOpenKey: String? = null

    private val fg get() = dash.foreground

    init {
        // Seed from this agent's snapshot so the inbox paints instantly, then fetch.
        viewModelScope.launch {
            dash.session.collect { s ->
                val id = s?.agentId ?: return@collect
                if (seededFor == id) return@collect
                seededFor = id
                // The snapshot is a file read: off the main thread (synchronous in tests).
                val snap = withContext(dash.container.config.io) {
                    runCatching { dash.container.snapshots.read(id, SNAP_KEY, ConversationPage.serializer()) }.getOrNull()
                }
                seed(snap)
                refresh()
            }
        }
        // Poll (push events are the primary signal) while foregrounded. A tick
        // that falls while backgrounded waits for the return — where catchUp()
        // has already refetched — and skips, so coming back is one request.
        viewModelScope.launch {
            while (isActive) {
                delay(60_000)
                if (!fg.value) { fg.first { it }; continue }
                refresh()
            }
        }
        // Frames sent while the app was away, or while the socket was down, are
        // gone: returning to the foreground and every reconnect catch up.
        viewModelScope.launch {
            var was = fg.value
            fg.collect { v -> if (v && !was) catchUp(); was = v }
        }
        viewModelScope.launch {
            var was = dash.container.socket.connected.value
            dash.container.socket.connected.collect { v -> if (v && !was) catchUp(); was = v }
        }
        // The open thread: poll as the socket's fallback every 20 s, as the web
        // does (skip while backgrounded).
        viewModelScope.launch {
            while (isActive) {
                delay(20_000)
                val id = _thread.value.activeId
                if (id.isNotEmpty() && fg.value) loadMessages(id, silent = true)
            }
        }
        viewModelScope.launch { dash.inboxRefresh.collect { refresh() } }
        viewModelScope.launch { dash.container.socket.events.collect { onSocket(it) } }
        // Deep links from other views / the hub: consume dash.openConvKey.
        viewModelScope.launch {
            combine(dash.openConvKey, _inbox) { k, s -> k to s }.collect { (k, s) -> if (k != null) tryOpenKey(k, s) }
        }
    }

    // ═══════════════════════════ The paged list (useInbox) ═══════════════════════════

    private fun seed(snap: ConversationPage?) {
        if (snap == null || snap.items.isEmpty()) return
        val rows = snap.items.map { it.normalized() }
        upsert(rows)
        _inbox.update { s ->
            if (s.orderIds.isNotEmpty()) s
            else s.copy(orderKey = DEFAULT_KEY, orderIds = rows.map { it.id }, hasMore = snap.nextCursor != null)
        }
        cursor = snap.nextCursor
        pages = 1
    }

    private fun upsert(rows: List<Conversation>) {
        if (rows.isEmpty()) return
        _inbox.update { s -> s.copy(cache = s.cache + rows.associate { it.id to it.normalized() }) }
    }

    /** Page one + badges. */
    fun refresh() {
        if (dash.session.value == null) return
        val seq = ++firstSeq
        recentRefresh?.cancel()
        recentRefresh = viewModelScope.launch { delay(CATCH_UP_WINDOW_MS) }
        val f = _inbox.value.filters
        val key = filterKeyOf(f)
        _inbox.value.let { if (it.orderKey != key || it.orderIds.isEmpty()) _inbox.update { s -> s.copy(loading = true, loadError = false, errorText = null) } }

        viewModelScope.launch {
            runCatching { api.conversations.summary() }.onSuccess { s ->
                if (seq == firstSeq) { _inbox.update { it.copy(summary = s) }; dash.inboxSummary.value = s }
            } // on failure the badges keep their last value
        }
        viewModelScope.launch {
            val res = try {
                inboxApi.page(f, PAGE)
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                // Only the live filter's own failure counts; a superseded one says nothing.
                // The rows already on screen stay; the list says why it couldn't refresh.
                if (seq == firstSeq) _inbox.update {
                    val live = key == filterKeyOf(it.filters)
                    it.copy(loading = false, loadError = live, errorText = if (live) listErrorText(e) else it.errorText)
                }
                return@launch
            }
            // Superseded by a newer refresh, or the filters moved on.
            if (seq != firstSeq || key != filterKeyOf(_inbox.value.filters)) return@launch
            upsert(res.items)
            val fresh = res.items.map { it.id }
            val top = fresh.toSet()
            val o = _inbox.value
            if (o.orderKey != key || pages <= 1) {
                // Only page one was loaded (or a snapshot, maybe days old): REPLACE
                // it and take the fresh cursor. A "load more" in flight was paging
                // from the OLD cursor — cancel it so it can't leave a gap.
                cursor = res.nextCursor
                pages = 1
                moreSeq++
                _inbox.update {
                    it.copy(
                        hasMore = res.nextCursor != null, loadingMore = false,
                        orderKey = key, orderIds = fresh + revealed.filter { id -> id !in top },
                    )
                }
            } else {
                // Scrolled further this session: page one on top, the rest kept below.
                _inbox.update { it.copy(orderKey = key, orderIds = fresh + o.orderIds.filter { id -> id !in top }) }
            }
            _inbox.update { it.copy(freshLoaded = true, loading = false, loadError = false, errorText = null, moreError = false) }
            if (key == DEFAULT_KEY) {
                val id = myId
                withContext(Dispatchers.IO) { dash.container.snapshots.write(id, SNAP_KEY, ConversationPage.serializer(), res) }
            }
            // The open thread stays fresh even when it is not on page one.
            val w = watched
            if (w != null && w !in top) {
                runCatching { inboxApi.get(w) }.onSuccess { one -> if (seq == firstSeq) upsert(listOf(one)) }
            }
        }
    }

    /**
     * The next page of people. Scrolling calls it on its own; after a failure
     * only an explicit Retry ([force]) or a successful refresh pages again —
     * otherwise a dead network would be asked for the same page in a loop.
     */
    fun loadMore(force: Boolean = false) {
        val c = cursor ?: return
        if (_inbox.value.loadingMore || dash.session.value == null) return
        if (_inbox.value.moreError && !force) return
        val seq = ++moreSeq
        val f = _inbox.value.filters
        val key = filterKeyOf(f)
        _inbox.update { it.copy(loadingMore = true, moreError = false) }
        viewModelScope.launch {
            try {
                val res = inboxApi.page(f, PAGE, c)
                if (seq != moreSeq || key != filterKeyOf(_inbox.value.filters)) return@launch
                upsert(res.items)
                val o = _inbox.value
                if (o.orderKey != key) return@launch
                val have = o.orderIds.toSet()
                _inbox.update { it.copy(orderIds = o.orderIds + res.items.map { r -> r.id }.filter { id -> id !in have }, hasMore = res.nextCursor != null) }
                cursor = res.nextCursor
                pages += 1
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                if (seq == moreSeq) _inbox.update { it.copy(moreError = true) }
            } finally {
                if (seq == moreSeq) _inbox.update { it.copy(loadingMore = false) }
            }
        }
    }

    /** New filters start their own list; the cache (and the open thread) stays. */
    private fun setFilters(t: (InboxQuery) -> InboxQuery) {
        val prev = _inbox.value.filters
        val next = t(prev)
        if (next == prev) return
        _inbox.update { it.copy(filters = next) }
        val key = filterKeyOf(next)
        if (_inbox.value.orderKey != key) {
            cursor = null; pages = 0; revealed = emptyList()
            _inbox.update { it.copy(hasMore = false, orderKey = key, orderIds = emptyList(), loadError = false, errorText = null, moreError = false) }
        }
        refresh()
    }

    // Changing what the list shows clears the picks: a selection you can no
    // longer see is one you can't check before releasing it.
    private fun clearPicks() = _list.update { it.copy(selected = emptySet()) }

    fun setTab(tab: String) { clearPicks(); setFilters { it.copy(tab = tab) } }
    fun setChannel(ch: String) { clearPicks(); setFilters { it.copy(channel = ch) } }
    fun setMode(m: String) = setFilters { it.copy(mode = m) }
    fun setTag(tag: String?) { clearPicks(); setFilters { it.copy(tag = tag) } }
    fun toggleFilters() = _list.update { it.copy(showFilters = !it.showFilters) }

    /** Search waits for a pause in typing so every keystroke is not a query. */
    fun setSearch(q: String) {
        _list.update { it.copy(search = q, selected = emptySet()) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch { delay(300); setFilters { it.copy(q = q) } }
    }

    /** Optimistic local edit to cached rows; a quiet refresh follows. */
    fun patchRows(t: (Conversation) -> Conversation) {
        _inbox.update { s -> s.copy(cache = s.cache.mapValues { (_, c) -> t(c) }) }
        quietJob?.cancel()
        quietJob = viewModelScope.launch { delay(2000); refresh() }
    }

    /** Add rows to the cache AND the visible list — a thread opened by a deep link. */
    private fun reveal(rows: List<Conversation>) {
        upsert(rows)
        revealed = (revealed + rows.map { it.id }).distinct()
        _inbox.update { s ->
            val have = s.orderIds.toSet()
            s.copy(orderIds = s.orderIds + rows.map { it.id }.filter { it !in have })
        }
    }

    fun renameCustomer(waId: String, newName: String) = patchRows { c -> if (c.waId == waId) c.copy(name = newName) else c }

    private fun buildRows(s: InboxUi, me: String?): List<RowGroup> {
        val f = s.filters
        val visible = if (s.orderKey == filterKeyOf(f)) s.orderIds.toHashSet() else hashSetOf()
        // The current filters' server pages decide WHO is listed; these checks then
        // show each person's qualifying threads, exactly as over the full list.
        val filtered = s.cache.values.filter { c ->
            c.id in visible &&
                (f.channel == "all" || c.channel == f.channel) &&
                (f.tag == null || f.tag in c.tags) &&
                (f.mode == "all" || c.interceptMode == f.mode) &&
                when (f.tab) {
                    "unread" -> c.unread > 0
                    "read" -> c.unread <= 0
                    "human" -> c.interceptMode == "human"
                    // "Yours" — held by a human AND that human is me.
                    "yours" -> c.interceptMode == "human" && c.assignedAgentId == me
                    else -> true
                }
        }.map { it to (Fmt.millis(it.lastMessageAt ?: it.createdAt) ?: 0L) }
            .sortedByDescending { it.second }.map { it.first }

        // Conversations sharing a person_id are the SAME customer across channels:
        // the newest is the row, the rest become channel chips on it.
        val repByPerson = HashMap<String, Conversation>()
        val siblings = LinkedHashMap<String, MutableList<Conversation>>()
        val order = mutableListOf<Conversation>()
        for (c in filtered) {
            val pid = c.personId
            if (pid == null) { order += c; siblings[c.id] = mutableListOf(c); continue }
            val rep = repByPerson[pid]
            if (rep == null) { repByPerson[pid] = c; order += c; siblings[c.id] = mutableListOf(c) }
            else siblings.getValue(rep.id) += c
        }
        return order.map { rep ->
            val sibs = (siblings[rep.id] ?: listOf(rep)).sortedBy { CHAN_ORDER.indexOf(it.channel).let { i -> if (i < 0) 99 else i } }
            RowGroup(
                key = rep.personId ?: rep.id,
                rep = rep,
                siblings = sibs,
                unread = sibs.sumOf { it.unread },
                lastAt = sibs.mapNotNull { it.lastMessageAt }.maxByOrNull { Fmt.millis(it) ?: 0L },
            )
        }
    }

    // ═══════════════════════════ Bulk selection ═══════════════════════════

    fun enterSelect(key: String? = null) = _list.update { it.copy(selectMode = true, selected = key?.let { k -> setOf(k) } ?: emptySet()) }
    fun exitSelect() = _list.update { it.copy(selectMode = false, selected = emptySet()) }
    fun toggleRow(key: String) = _list.update { s -> s.copy(selected = if (key in s.selected) s.selected - key else s.selected + key) }
    fun selectAllOrClear() {
        val all = rows.value.map { it.key }.toSet()
        _list.update { s -> s.copy(selected = if (s.selected.size == all.size && all.isNotEmpty()) emptySet() else all) }
    }

    /** How many conversations Release would act on — rows with Neema already cost nothing. */
    fun selectedHeldIds(): List<String> {
        val sel = _list.value.selected
        return rows.value.filter { it.key in sel }.flatMap { g -> g.siblings.filter { it.interceptMode == "human" }.map { it.id } }
    }

    fun releaseSelected() {
        val ids = selectedHeldIds()
        if (ids.isEmpty()) { dash.toast("None of those are held by a human", ToastType.Warning); return }
        if (_list.value.bulkBusy) return
        _list.update { it.copy(bulkBusy = true) }
        viewModelScope.launch {
            // Each release says whether it happened; one that got no answer is
            // asked about (a release is idempotent, and the row tells the truth).
            val errors = ids.map { id ->
                async {
                    try { inboxApi.release(id); null } catch (e: Exception) {
                        if (e is CancellationException) throw e
                        when {
                            conversationGone(e) -> { dropGone(id); null }
                            fateOf(e) == Fate.Unknown -> {
                                val row = runCatching { inboxApi.get(id) }.getOrNull()
                                if (row?.interceptMode == "ai") { upsert(listOf(row)); null } else e
                            }
                            else -> e
                        }
                    }
                }
            }.awaitAll()
            val failed = errors.filterNotNull()
            val ok = ids.size - failed.size
            _list.update { it.copy(bulkBusy = false) }
            exitSelect()
            refresh()
            if (failed.isNotEmpty()) dash.toast("Released $ok — ${failed.size} failed. ${whyFailed(failed.first(), "Try again.")}", ToastType.Error)
            else dash.toast("$ok conversation${if (ok == 1) "" else "s"} released back to Neema")
        }
    }

    // ═══════════════════════════ Opening threads ═══════════════════════════

    fun activeConv(): Conversation? = _inbox.value.cache[_thread.value.activeId]

    fun select(id: String, openThread: Boolean = true) {
        val conv = _inbox.value.cache[id]
        if (conv != null && conv.unread > 0) {
            // Snapshot before clearing so the "N new" divider can be placed.
            _thread.update { it.copy(unreadSnapshot = it.unreadSnapshot + (id to conv.unread)) }
            patchRows { c -> if (c.id == id) c.copy(unread = 0) else c }
        }
        val prev = _thread.value.activeId
        val changed = prev != id
        // Each customer keeps their own composer: what was typed for one person
        // must never be sent to the next one opened. The same person's other
        // channels share it — a quote grabbed on WhatsApp can be answered on
        // their Facebook thread (as a text prefix), as on the web.
        if (changed) {
            val txMode = _composer.value.txMode
            val samePerson = prev.isNotEmpty() && composerKey(prev) == composerKey(id)
            val next = if (samePerson) _composer.value else {
                if (prev.isNotEmpty()) stash[composerKey(prev)] = _composer.value
                stash.remove(composerKey(id)) ?: ComposerUi()
            }
            // A draft belongs to one thread, and one left behind may be stale (a
            // newer one may have been written meanwhile): only a draft the agent
            // opened or edited comes back with its own thread.
            val keepDraft = !samePerson && next.draftVisible && (next.draftExpanded || next.draftEditing)
            _composer.value = next.copy(
                txMode = txMode, txPreview = null, txBusy = false,
                draftVisible = keepDraft, draftExpanded = keepDraft && next.draftExpanded,
                draftEditing = keepDraft && next.draftEditing, draftText = if (keepDraft) next.draftText else "",
            )
            heldDrafts.remove(id)?.let { d -> _composer.update { it.copy(draftText = d, draftVisible = true, draftExpanded = true, draftEditing = false) } }
        }
        _thread.update { it.copy(activeId = id, threadOpen = openThread || it.threadOpen, window = if (changed) null else it.window, activity = if (changed) emptyList() else it.activity) }
        watched = id
        loadMessages(id)
        if (changed) onActiveChanged(id)
    }

    fun closeThread() = _thread.update { it.copy(threadOpen = false) }

    private fun onActiveChanged(id: String) {
        // A human-held thread fetches the latest AI draft (pill only) unless the
        // agent's own open draft came back with the thread.
        draftJob?.cancel()
        if (!_composer.value.draftVisible) fetchLatestDraft(id)
        refreshWindow()
        loadActivity()
        scheduleTranslate()
        loadReach(id)
    }

    private var reachJob: Job? = null

    /**
     * The customer's captured phone and channels (the profile CustomerSidebar
     * reads). A person already on WhatsApp needs no invite, so no fetch; a
     * failure leaves the shortcut hidden rather than guessing.
     */
    private fun loadReach(id: String) {
        reachJob?.cancel()
        _thread.update { it.copy(reach = null) }
        val conv = _inbox.value.cache[id] ?: return
        val onWa = realWhatsApp(conv) || (conv.personId != null && _inbox.value.cache.values.any { it.personId == conv.personId && realWhatsApp(it) })
        if (onWa) { _thread.update { it.copy(reach = Reach(id, phoneDigits(conv), hasWhatsApp = true)) }; return }
        val key = conv.waId ?: conv.externalId ?: return
        reachJob = viewModelScope.launch {
            val p = try {
                ke.co.bethanyhouse.neema.feature.conversations.customer.CrmApi(dash.api.http).profile(key, conv.channel.ifEmpty { null })
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                return@launch
            }
            if (_thread.value.activeId != id) return@launch
            val hasWa = p.channels.any { it.channel == "whatsapp" && !isWebVisitor(it.identifier) }
            _thread.update { it.copy(reach = Reach(id, p.phone, hasWa)) }
        }
    }

    /** Open a conversation another view requested (Calls → "message in Neema", the hub). */
    private fun tryOpenKey(openKey: String, s: InboxUi) {
        // A pair combine() computed before the key was consumed is stale.
        if (dash.openConvKey.value != openKey) return
        // A deep link can land before the inbox has loaded — don't consume it against an empty list.
        if (s.cache.isEmpty()) return
        val parts = openKey.split("|")
        val rawKey = parts[0]
        val refPart = parts.getOrNull(1)?.takeIf { it.isNotBlank() }
        val key = rawKey.removePrefix("+")
        val matches = s.cache.values.filter { it.waId == key || it.externalId == key || it.waId == rawKey || it.id == rawKey }
        val conv = matches.find { it.channel == "whatsapp" } ?: matches.firstOrNull()
        if (conv != null) {
            select(conv.id)
        } else {
            // A cached snapshot may not contain a brand-new conversation — wait for the fresh list.
            if (!s.freshLoaded) return
            // Not directly keyed — the server walks order -> person -> identities.
            viewModelScope.launch {
                val id = try {
                    api.conversations.resolve(key, refPart)
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                    // No connection: the link is kept and opened once we're back.
                    if (statusOf(e) == 0) {
                        retryOpenKey = openKey
                        dash.toast("Couldn't open that chat — no connection. It will open when you're back online.", ToastType.Error)
                    } else dash.toast("Could not look up that chat.", ToastType.Error)
                    return@launch
                }
                if (id == null) {
                    dash.toast("No conversation yet — they haven't messaged. Use Invite to WhatsApp.", ToastType.Warning)
                    return@launch
                }
                if (id !in _inbox.value.cache) {
                    // Revealed, not just cached: the paged list would drop it on the next refresh.
                    runCatching { inboxApi.get(id) }.onSuccess { reveal(listOf(it)) }
                }
                select(id)
            }
        }
        dash.openConvKey.value = null
    }

    /** Jump to the same person's conversation on another channel. */
    fun openIdentity(channel: String, externalId: String) {
        fun matches(c: Conversation) = c.channel == channel && (c.externalId == externalId || c.waId == externalId)
        _inbox.value.cache.values.find(::matches)?.let { select(it.id); return }
        // Paged: absence here is not absence. Ask for THAT channel and THAT id.
        viewModelScope.launch {
            val items = try {
                inboxApi.page(InboxQuery(channel = channel, q = externalId), 5).items
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                // A failed lookup is not an answer: never claim there is no conversation.
                dash.toast("Couldn't open that conversation. ${whyFailed(e, "Try again.")}", ToastType.Error)
                return@launch
            }
            val hit = items.map { it.normalized() }.find(::matches)
            if (hit != null) { reveal(listOf(hit)); select(hit.id) }
            else dash.toast("No conversation on that channel yet.", ToastType.Warning)
        }
    }

    // ═══════════════════════════ The thread ═══════════════════════════

    private fun setMsgs(convId: String, t: (List<ThreadMsg>) -> List<ThreadMsg>) {
        val before = _thread.value.messages[convId]?.size ?: 0
        _thread.update { it.copy(messages = it.messages + (convId to t(it.messages[convId] ?: emptyList()))) }
        val after = _thread.value.messages[convId]?.size ?: 0
        // An inbound reopens the messaging window: refresh it on every new message.
        if (convId == _thread.value.activeId && after != before) refreshWindow()
    }

    /**
     * The server's newest page for [convId]: merged in (a fresh open replaces,
     * keeping only this device's own bubbles), then any send still on its way
     * is settled against it.
     */
    private fun applyServer(convId: String, msgs: List<ThreadMsg>, replace: Boolean = false) {
        setMsgs(convId) { cur -> if (replace) mergeServer(cur.filter { it.isLocal }, msgs) else mergeServer(cur, msgs) }
        settle(convId, msgs)
    }

    fun loadMessages(convId: String, silent: Boolean = false) {
        if (convId.isEmpty()) return
        val seq = (loadSeq[convId] ?: 0) + 1
        if (!silent) { loadSeq[convId] = seq; _thread.update { it.copy(loading = true, error = false, errorText = null) } }
        // Only this thread's newest open touches the spinner and error — and only
        // while it is still the thread on screen.
        fun mine() = !silent && loadSeq[convId] == seq && _thread.value.activeId == convId
        viewModelScope.launch {
            try {
                val msgs = inboxApi.messages(convId)
                applyServer(convId, msgs, replace = !silent)
                if (!silent) _thread.update { it.copy(hasMore = it.hasMore + (convId to (msgs.count { m -> !m.isSystem } >= THREAD_PAGE))) }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                if (conversationGone(e)) { dropGone(convId); return@launch }
                // "No messages yet" over a failed fetch would read as an empty conversation.
                if (mine()) {
                    _thread.update { it.copy(error = true, errorText = whyFailed(e, "Couldn't load this conversation.")) }
                    dash.toast("Failed to load messages", ToastType.Error)
                }
            } finally {
                if (!silent && loadSeq[convId] == seq && _thread.value.activeId == convId) _thread.update { it.copy(loading = false) }
            }
        }
    }

    /** Scrolling up past the loaded page fetches the previous page (via `before`). */
    fun loadOlder() {
        val t = _thread.value
        val convId = t.activeId
        if (convId.isEmpty() || t.olderLoading == convId || t.hasMore[convId] != true) return
        val oldest = (t.messages[convId] ?: emptyList()).firstOrNull { !it.isSystem && !it.isLocal } ?: return
        val before = oldest.createdAt ?: return
        _thread.update { it.copy(olderLoading = convId, olderError = if (it.olderError == convId) "" else it.olderError) }
        viewModelScope.launch {
            try {
                val older = inboxApi.messages(convId, before = before)
                _thread.update { it.copy(hasMore = it.hasMore + (convId to (older.count { m -> !m.isSystem } >= THREAD_PAGE))) }
                if (older.isNotEmpty()) setMsgs(convId) { mergeThread(it, older) }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                // Scrolling at the very top changes nothing that would ask again: offer a tap.
                _thread.update { it.copy(olderError = convId) }
            } finally {
                _thread.update { if (it.olderLoading == convId) it.copy(olderLoading = "") else it }
            }
        }
    }

    private fun refreshWindow() {
        val id = _thread.value.activeId.ifEmpty { return }
        windowJob?.cancel()
        windowJob = viewModelScope.launch {
            val w = runCatching { api.conversations.window(id) }.getOrNull()
            if (_thread.value.activeId == id) _thread.update { it.copy(window = w) }
        }
    }

    /** The person-scoped journey ledger; refreshed each minute while the panel is open. */
    private fun loadActivity() {
        val id = _thread.value.activeId.ifEmpty { return }
        activityJob?.cancel()
        activityJob = viewModelScope.launch {
            while (isActive) {
                val ev = runCatching { inboxApi.activity(id) }.getOrDefault(emptyList())
                if (_thread.value.activeId != id) return@launch
                _thread.update { it.copy(activity = ev) }
                if (!_thread.value.activityOpen) return@launch
                delay(60_000)
                if (!fg.value) fg.first { it }
            }
        }
    }

    fun setActivityOpen(open: Boolean) {
        _thread.update { it.copy(activityOpen = open) }
        if (open) loadActivity()
    }

    /**
     * Fetch an expired attachment back from Meta. Only the server's 404 means
     * Meta no longer has it; a dropped connection or a busy server is "try
     * again", never "gone for good".
     */
    fun recoverMedia(messageId: String, onDone: (Recovery) -> Unit) {
        val convId = _thread.value.activeId
        viewModelScope.launch {
            val out = try {
                val url = api.conversations.recoverMedia(messageId).mediaUrl?.takeIf { it.isNotBlank() }
                if (url != null) Recovery.Found(url) else Recovery.Gone
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                if (statusOf(e) == 404 || statusOf(e) == 422) Recovery.Gone
                else Recovery.Failed(whyFailed(e, "Couldn't fetch it — try again."))
            }
            if (out is Recovery.Found) {
                _thread.update { it.copy(recovered = it.recovered + (messageId to out.url)) }
                if (convId.isNotEmpty()) loadMessages(convId, silent = true)
            }
            onDone(out)
        }
    }

    // ═══════════════════════════ Live events ═══════════════════════════

    /**
     * Catch up on what the socket could not deliver: the list and badges, the
     * open thread, and — for a human-held thread — a draft that may have been
     * written meanwhile. The app returning to the foreground usually also
     * reopens the socket a moment later; both land in one catch-up, and a list
     * refresh that has only just run is not repeated.
     */
    private fun catchUp() {
        if (dash.session.value == null || catchUpJob?.isActive == true) return
        // A deep link that failed offline opens now.
        retryOpenKey?.let { k -> retryOpenKey = null; if (dash.openConvKey.value == null) dash.openConvKey.value = k }
        catchUpJob = viewModelScope.launch {
            if (recentRefresh?.isActive != true) refresh()
            val id = _thread.value.activeId
            if (id.isNotEmpty()) {
                loadMessages(id, silent = true)
                if (!_composer.value.draftVisible) fetchLatestDraft(id)
            }
            delay(CATCH_UP_WINDOW_MS)
        }
    }

    /** The latest AI draft of a human-held thread, as a pill (never auto-expanded). */
    private fun fetchLatestDraft(id: String) {
        if (_inbox.value.cache[id]?.interceptMode != "human") return
        draftJob?.cancel()
        draftJob = viewModelScope.launch {
            runCatching { api.conversations.latestDraft(id) }.getOrNull()?.takeIf { it.isNotBlank() }?.let { d ->
                if (_thread.value.activeId == id && !_composer.value.draftVisible) _composer.update { it.copy(draftText = d, draftVisible = true) }
            }
        }
    }

    /** Change [convId]'s composer — the live one when it is open, else the one it left behind. */
    private fun editComposer(convId: String, t: (ComposerUi) -> ComposerUi) {
        if (convId.isEmpty()) return
        val active = _thread.value.activeId
        val key = composerKey(convId)
        if (active.isNotEmpty() && composerKey(active) == key) _composer.update(t)
        else stash[key] = t(stash[key] ?: ComposerUi())
    }

    /** Whose composer a thread uses: the person's (all their channels share one), else the thread's own. */
    private fun composerKey(convId: String): String = _inbox.value.cache[convId]?.personId?.let { "p:$it" } ?: convId

    /**
     * Someone deleted the conversation (the server's 404): take it off the
     * list, close it if open, and say so once.
     */
    private fun dropGone(convId: String) {
        val had = _inbox.value.cache[convId] ?: return
        _inbox.update { it.copy(cache = it.cache - convId, orderIds = it.orderIds - convId) }
        revealed = revealed - convId
        if (had.personId == null) stash.remove(convId)
        outgoing.values.removeAll { it.convId == convId }
        if (watched == convId) watched = null
        _thread.update {
            val open = it.activeId == convId
            it.copy(
                messages = it.messages - convId,
                activeId = if (open) "" else it.activeId, threadOpen = if (open) false else it.threadOpen,
                error = if (open) false else it.error, loading = if (open) false else it.loading,
                window = if (open) null else it.window, activity = if (open) emptyList() else it.activity,
            )
        }
        if (_thread.value.activeId.isEmpty()) _composer.update { ComposerUi(txMode = it.txMode) }
        dash.toast("${inboxName(had)}'s conversation was deleted — it has been removed from your inbox.", ToastType.Warning)
    }

    /**
     * One refetch per burst: the first frame schedules it, frames arriving
     * before it runs ride along (a busy minute is never postponed forever the
     * way restarting the timer on each frame would).
     */
    private fun scheduleSocketRefresh() {
        if (socketRefreshJob?.isActive == true) return
        socketRefreshJob = viewModelScope.launch { delay(SOCKET_REFRESH_MS); refresh() }
    }

    private fun onSocket(e: JsonObject) {
        val type = e.s("type")
        val convId = e.s("conversationId") ?: e.s("conversation_id")
        // Agent-level pings (`event: "notification"`) share type names with thread
        // events but carry a title/body, not a message — never paint them. The
        // shell refetches the inbox for the kinds that move it (page.tsx); an
        // SMS arrival (`new_message`) is the one it doesn't, so it counts here.
        if (e.s("event") == "notification") {
            if (type == "new_message") scheduleSocketRefresh()
            return
        }
        // Any thread moving means rows / badges moved: refetch shortly (coalesced).
        if (type in MOVING_FRAMES) scheduleSocketRefresh()
        if (convId == null) return
        // The row moves NOW; the refetch then confirms it (same values, no flicker).
        patchLive(convId, type, e)
        val active = _thread.value.activeId
        if (convId != active) {
            // A cached thread that isn't open would reappear uncleared for a moment.
            if (type == "history_cleared" && convId in _thread.value.messages) setMsgs(convId) { emptyList() }
            return
        }
        when (type) {
            "ai_draft_ready" -> _composer.update {
                it.copy(draftText = e.s("draft") ?: "", draftVisible = true, draftExpanded = false, draftEditing = false)
            }
            // `message` is the older frame (web chat, ManyChat, TikTok, the Tier-2
            // agent's WhatsApp replies, channel sends). The web drops it and waits
            // for its 20 s poll; here it paints like `new_message`.
            "new_message", "message" -> {
                val msg = wsMessageOf(e) ?: return
                setMsgs(active) { existing -> appendWs(existing, msg) }
            }
            "translations" -> {
                val items = (e["items"] as? JsonArray)?.mapNotNull { it as? JsonObject } ?: return
                val byId = items.associateBy { it.s("id") ?: "" }
                val cur = _thread.value.messages[active].orEmpty()
                if (cur.none { x -> x.translation == null && x.id in byId }) return // nothing to change: no re-render
                setMsgs(active) { existing ->
                    existing.map { x ->
                        val t = byId[x.id]
                        if (t == null || x.translation != null) x else x.copy(translation = t.s("text"), translatedFrom = t.s("lang"))
                    }
                }
            }
            "intercept_changed" -> {
                val evt = systemEventFromWs(e) ?: return
                // One live pill per kind: a repeat fire is skipped.
                if (_thread.value.messages[active].orEmpty().any { it.id.startsWith("live-evt-") && it.eventKind == evt.eventKind }) return
                setMsgs(active) { existing -> existing + evt }
            }
            "history_cleared" -> {
                setMsgs(active) { emptyList() }
                dash.toast("History cleared by ${e.s("clearedBy") ?: "an agent"}")
            }
        }
    }

    /**
     * Move the conversation's row the moment its frame lands, with the values
     * the refetch will bring (admin.py _conversation_rows): a message sets the
     * preview and time; an inbound one adds to `unread` (inbound since our
     * last reply), an outbound reply zeroes it; a mode change sets the mode
     * and owner, so the thread's banner and controls follow at once. A frame
     * for a conversation not loaded yet leaves it to the refetch.
     */
    /** Two frames in the same millisecond must still sort by arrival: stamps only ever increase. */
    private var lastLiveStamp = 0L
    private fun liveStamp(): String {
        lastLiveStamp = maxOf(AppClock.now(), lastLiveStamp + 1)
        return java.time.Instant.ofEpochMilli(lastLiveStamp).toString()
    }

    private fun patchLive(convId: String, type: String?, e: JsonObject) {
        val cur = _inbox.value.cache[convId] ?: return
        val next = when (type) {
            "new_message", "message" -> {
                val msg = wsMessageOf(e) ?: return
                val text = msg.body.trim()
                cur.copy(
                    lastMessageAt = liveStamp(),
                    lastMessagePreview = if (text.isNotEmpty()) text.take(100) else cur.lastMessagePreview,
                    unread = if (msg.inbound) cur.unread + 1 else 0,
                )
            }
            "intercept_changed" -> {
                val mode = e.s("mode") ?: return // an AI escalation carries no mode: the refetch says
                val released = mode == "ai"
                cur.copy(
                    interceptMode = mode,
                    assignedAgentId = if (released) null else if ("assignedAgentId" in e) e.s("assignedAgentId") else cur.assignedAgentId,
                    assignedAgentName = if (released) null else e.s("assignedAgentName") ?: cur.assignedAgentName,
                )
            }
            "history_cleared" -> cur.copy(lastMessagePreview = null, unread = 0)
            else -> return
        }
        if (next == cur) return
        _inbox.update { s ->
            // A thread just written to is on page one of an unsearched list; a
            // search waits for the server to say whether it still matches.
            val show = type != "intercept_changed" && type != "history_cleared" &&
                s.orderKey == filterKeyOf(s.filters) && s.filters.q.isBlank() && convId !in s.orderIds
            s.copy(cache = s.cache + (convId to next), orderIds = if (show) listOf(convId) + s.orderIds else s.orderIds)
        }
    }

    // ═══════════════════════════ Conversation actions ═══════════════════════════

    /** One control at a time per conversation; another thread's controls stay live. */
    private fun busy(id: String, kind: String, block: suspend () -> Unit) {
        if (id.isEmpty() || _thread.value.busyFor(id).isNotEmpty()) return
        _thread.update { it.copy(busy = it.busy + (id to kind)) }
        viewModelScope.launch {
            try { block() } finally { _thread.update { it.copy(busy = it.busy - id) } }
        }
    }

    private fun status(e: Throwable) = (e as? ApiException)?.status ?: 0

    // A 403 anywhere re-reads /admin/me and the team list on its own (NeemaHttp →
    // dash.onForbidden()), so the inbox's role-based controls correct themselves.

    /** "Failed to pause. No connection — check your internet and try again." — the web's words, then why. */
    private fun failMsg(fail: String, e: Throwable, useDetail: Boolean = false): String {
        val why = whyFailed(e, "", useDetail)
        return if (why.isEmpty()) fail else "$fail. $why"
    }

    /**
     * An ownership change that got no answer: the server may have made it.
     * These calls are idempotent, so the row is the truth — read it, show it,
     * and report what actually happened.
     */
    private suspend fun truthOf(id: String): Conversation? =
        try { inboxApi.get(id).also { upsert(listOf(it)) } } catch (e: Exception) { if (e is CancellationException) throw e; null }

    /**
     * Run one ownership control: success says [ok]; a conflict shows the
     * current truth and [conflict]; no answer asks the server whether [done]
     * holds before saying anything; a deleted conversation is removed.
     */
    private suspend fun control(id: String, ok: String, fail: String, conflict: String?, done: (Conversation) -> Boolean, call: suspend () -> Unit): Boolean {
        try {
            call()
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            when {
                conversationGone(e) -> { dropGone(id); return false }
                status(e) == 409 && conflict != null -> {
                    truthOf(id); refresh()
                    dash.toast(conflict, ToastType.Error); return false
                }
                fateOf(e) != Fate.NotSent -> {
                    val row = truthOf(id)
                    if (row == null) {
                        // Couldn't ask either: never call it failed when it may not have.
                        dash.toast("Couldn't confirm that went through — no answer from the server. The inbox shows the latest as soon as you're back online.", ToastType.Warning)
                        return false
                    }
                    if (!done(row)) { refresh(); dash.toast(failMsg(fail, e), ToastType.Error); return false }
                    // It happened after all.
                }
                else -> {
                    // A state conflict: show the current truth along with the reason.
                    if (status(e) == 409) { truthOf(id); refresh() }
                    dash.toast(failMsg(fail, e, useDetail = status(e) in setOf(400, 403, 409, 422)), ToastType.Error); return false
                }
            }
        }
        refresh()
        dash.toast(ok)
        return true
    }

    fun intercept(id: String) = busy(id, "intercept") {
        val me = myId
        control(
            id, "Conversation claimed — you now control replies", "Failed to claim conversation", "Already claimed by another agent",
            done = { it.interceptMode == "human" && it.assignedAgentId == me },
        ) { inboxApi.intercept(id) }
    }

    fun release(id: String) = busy(id, "release") {
        control(id, "Conversation released back to AI", "Failed to release", null, done = { it.interceptMode == "ai" }) { inboxApi.release(id) }
    }

    fun pause(id: String) = busy(id, "pause") {
        control(
            id, "Paused — Neema holds all replies until you resume", "Failed to pause", "Handled by another agent — they must pause it",
            done = { it.interceptMode == "paused" },
        ) { inboxApi.pause(id) }
    }

    fun transfer(agentId: String, agentName: String?) {
        val id = _thread.value.activeId.ifEmpty { return }
        busy(id, "release") {
            val ok = control(
                id, "Transferred to ${agentName ?: "agent"}", "Failed to transfer", null,
                done = { it.assignedAgentId == agentId },
            ) { inboxApi.transfer(id, agentId) }
            if (ok) _dialogs.update { it.copy(transfer = false) }
        }
    }

    fun showTransfer(v: Boolean) = _dialogs.update { it.copy(transfer = v) }
    fun showNote(v: Boolean) = _dialogs.update { it.copy(note = v) }
    fun setNoteText(v: String) = _dialogs.update { it.copy(noteText = v) }
    fun showClear(v: Boolean) = _dialogs.update { it.copy(clearConfirm = v) }

    /** An internal note: the bubble shows at once and is confirmed like a reply. */
    fun saveNote() {
        val convId = _thread.value.activeId
        val text = _dialogs.value.noteText.trim()
        if (text.isEmpty() || convId.isEmpty()) return
        val o = Outgoing(localId = "optimistic-note-${AppClock.now()}-${++localSeq}", convId = convId, kind = OutKind.Note, text = text, known = knownIds(convId))
        outgoing[o.localId] = o
        setMsgs(convId) {
            it + ThreadMsg(id = o.localId, direction = "outbound", sender = "human_agent", text = text, isNote = true, createdAt = nowIso(), sendState = "sending")
        }
        _dialogs.update { it.copy(note = false, noteText = "") }
        viewModelScope.launch { deliver(o.localId) }
    }

    fun clearHistory() {
        val convId = _thread.value.activeId.ifEmpty { return }
        if (_dialogs.value.clearing) return
        _dialogs.update { it.copy(clearing = true) }
        viewModelScope.launch {
            try {
                try {
                    api.conversations.clearHistory(convId)
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                    // No answer: a clear is idempotent — an empty thread says it happened.
                    if (fateOf(e) == Fate.NotSent || runCatching { inboxApi.messages(convId) }.getOrNull()?.none { !it.isSystem } != true) throw e
                }
                setMsgs(convId) { emptyList() }
                _dialogs.update { it.copy(clearConfirm = false) }
                refresh()
                dash.toast("Chat history cleared")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                if (conversationGone(e)) { _dialogs.update { it.copy(clearConfirm = false) }; dropGone(convId); return@launch }
                // Refused: the 🗑️ was stale (this agent is no longer an admin) — close
                // the dialog; the core's 403 refetch then takes the button away too.
                if (status(e) == 403) _dialogs.update { it.copy(clearConfirm = false) }
                dash.toast(
                    if (status(e) == 403) "You don't have permission to clear chat history"
                    else failMsg("Failed to clear history", e),
                    ToastType.Error,
                )
            } finally {
                _dialogs.update { it.copy(clearing = false) }
            }
        }
    }

    // ═══════════════════════════ Composer ═══════════════════════════

    /** The customer's detected language — free, from translations cached on inbound rows. */
    fun threadLang(): String? = threadLangOf(_thread.value)

    fun txOn(): Boolean = txOnOf(_thread.value, _composer.value)

    fun toggleTx() {
        val id = _thread.value.activeId.ifEmpty { return }
        val on = txOn()
        _composer.update { it.copy(txMode = it.txMode + (id to !on)) }
        scheduleTranslate()
    }

    fun setReplyText(v: String) {
        _composer.update { it.copy(replyText = v) }
        scheduleTranslate()
    }

    /**
     * Live preview: pause typing → see what will be sent in the customer's
     * language. Debounced; the send path reuses a matching preview so nothing
     * is translated twice.
     */
    private fun scheduleTranslate() {
        txJob?.cancel()
        val id = _thread.value.activeId
        val t = _composer.value.replyText.trim()
        if (!txOn() || id.isEmpty() || t.length < 2) { _composer.update { it.copy(txPreview = null, txBusy = false) }; return }
        txJob = viewModelScope.launch {
            delay(700)
            _composer.update { it.copy(txBusy = true) }
            try {
                val res = api.conversations.translateReply(id, t)
                _composer.update { c ->
                    c.copy(txPreview = if (res.text.isNotBlank() && res.text.trim() != t) TxPreview(t, res.text, res.lang) else null)
                }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                _composer.update { it.copy(txPreview = null) } // fail open — English still sends
            } finally {
                _composer.update { it.copy(txBusy = false) }
            }
        }
    }

    /** Start replying to a specific message (the Reply button or a swipe). */
    fun beginReplyTo(msg: ThreadMsg) {
        if (msg.body.isBlank() && msg.mediaUrl == null) return
        _composer.update {
            it.copy(
                quoted = Quoted(
                    msgId = msg.id, sender = msg.sender,
                    text = msg.body.replace(Regex("^\\[comment]\\s*"), "").take(300),
                    channel = activeConv()?.channel ?: "whatsapp",
                    mediaUrl = if (msg.mediaType == "image") msg.mediaUrl else null,
                    mediaType = msg.mediaType,
                ),
            )
        }
    }

    fun clearQuote() = _composer.update { it.copy(quoted = null) }

    /**
     * Send the reply. The bubble shows at once ("sending…") and the box
     * clears; the words are never lost after that:
     *  - delivered → the server's row replaces the bubble;
     *  - refused (the channel said no, a 4xx, no connection at all) → the
     *    text goes back in the box, or — if the agent has moved on — the
     *    bubble turns "Not sent" with Retry / Edit;
     *  - no answer (a timeout, a dropped connection, a gateway error) → it
     *    may have reached the customer: the bubble stays "sending…" while the
     *    thread is re-read, and only a server that shows no such row turns it
     *    "Not sent". A retry checks once more before sending again.
     */
    fun sendReply() {
        val c = _composer.value
        val convId = _thread.value.activeId
        if (c.replyText.isBlank() || convId.isEmpty()) return
        val conv = activeConv()
        // Same channel → a native threaded reply. A quote from ANOTHER channel
        // can't be threaded, so it rides as a text prefix.
        val quoted = c.quoted
        val sameChannel = quoted != null && quoted.channel == (conv?.channel ?: "whatsapp")
        val replyToId = if (sameChannel) quoted?.msgId else null
        val prefix = if (quoted != null && !sameChannel)
            "↩ Re (${channelLabel(quoted.channel)}): \"${quoted.text.take(180)}\"\n\n" else ""
        val text = prefix + c.replyText
        val wantTx = txOn()
        val preview = c.txPreview
        val o = Outgoing(
            localId = "optimistic-${AppClock.now()}-${++localSeq}", convId = convId, kind = OutKind.Reply,
            text = text, replyToId = replyToId, typed = c.replyText, quoted = quoted, known = knownIds(convId),
        )
        outgoing[o.localId] = o
        setMsgs(convId) {
            it + ThreadMsg(
                id = o.localId, direction = "outbound", sender = "human_agent", text = text, createdAt = nowIso(),
                replyTo = if (replyToId != null && quoted != null)
                    QuotedRef(replyToId, quoted.text, quoted.sender, quoted.mediaType, quoted.mediaUrl) else null,
                sendState = "sending",
            )
        }
        // The box is free at once: a second tap has nothing to send twice.
        txJob?.cancel()
        _composer.update { it.copy(replyText = "", quoted = null, txPreview = null, txBusy = false) }
        viewModelScope.launch {
            if (wantTx) {
                // Toggle ON → the customer receives their language; the English rides
                // along as the gray line. Any failure falls open to sending English.
                try {
                    val src = text.trim()
                    val tx = if (preview != null && preview.src == src) preview.text to preview.lang
                    else api.conversations.translateReply(convId, src).let { it.text to it.lang }
                    if (tx.first.isNotBlank() && tx.first.trim() != src) {
                        outgoing[o.localId]?.let { cur -> outgoing[o.localId] = cur.copy(text = tx.first, origText = src, origLang = tx.second) }
                        setMsgs(convId) { l -> l.map { m -> if (m.id == o.localId) m.copy(text = tx.first, translation = src, translatedFrom = tx.second) else m } }
                    }
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                }
            }
            deliver(o.localId)
        }
    }

    /** The server rows a thread already shows: a send's own row is a NEW one. */
    private fun knownIds(convId: String): Set<String> =
        _thread.value.messages[convId].orEmpty().filterNot { it.isLocal }.mapTo(HashSet()) { it.id }

    private fun bubble(convId: String, localId: String, state: String?, error: String? = null) =
        setMsgs(convId) { l -> l.map { if (it.id == localId) it.copy(sendState = state, sendError = error) else it } }

    private fun dropBubble(convId: String, localId: String) = setMsgs(convId) { l -> l.filterNot { it.id == localId } }

    private fun whoOf(convId: String): String = _inbox.value.cache[convId]?.let(::inboxName) ?: "this customer"

    private fun noun(k: OutKind) = when (k) { OutKind.Reply -> "Reply"; OutKind.Approve -> "AI draft"; OutKind.Note -> "Note" }

    /** Post one send and decide what its answer means. */
    private suspend fun deliver(localId: String) {
        val o = outgoing[localId] ?: return
        val err: Exception? = try {
            when (o.kind) {
                OutKind.Reply -> inboxApi.reply(o.convId, o.text, o.replyToId, o.origText, o.origLang)
                OutKind.Approve -> api.conversations.approveDraft(o.convId, o.text.ifEmpty { null })
                OutKind.Note -> api.conversations.addNote(o.convId, o.text)
            }
            null
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            e
        }
        when {
            err == null || fateOf(err) == Fate.Done -> sent(o)
            conversationGone(err) -> dropGone(o.convId)
            fateOf(err) == Fate.Unknown -> reconcile(localId, err)
            else -> notSent(localId, err)
        }
    }

    /** Delivered: the server's row replaces the bubble. A failed refetch is still a success. */
    private suspend fun sent(o: Outgoing) {
        outgoing.remove(o.localId)
        bubble(o.convId, o.localId, null)
        when (o.kind) {
            OutKind.Approve -> dash.toast("AI draft approved & sent")
            OutKind.Note -> dash.toast("Note saved")
            OutKind.Reply -> {}
        }
        try { applyServer(o.convId, inboxApi.messages(o.convId)) } catch (e: Exception) { if (e is CancellationException) throw e }
        if (o.kind != OutKind.Note) refresh()
    }

    /**
     * The server refused it (or it never left the phone): nothing went out.
     * The words go back where they were typed when that is safe — the thread
     * is open and that box is empty — else the bubble says "Not sent".
     */
    private fun notSent(localId: String, e: Throwable) {
        val o = outgoing[localId] ?: return
        val active = _thread.value.activeId == o.convId
        if (statusOf(e) == 409) viewModelScope.launch { truthOf(o.convId); refresh() }
        val why = when (o.kind) {
            OutKind.Reply -> whyFailed(e, "Failed to send message", useDetail = true)
            OutKind.Approve -> failMsg("Failed to approve draft", e)
            OutKind.Note -> failMsg("Failed to save note", e)
        }
        val back = active && !o.retried && when (o.kind) {
            OutKind.Reply -> _composer.value.replyText.isBlank()
            OutKind.Approve -> !_composer.value.draftVisible
            OutKind.Note -> !_dialogs.value.note
        }
        if (back) {
            outgoing.remove(localId)
            dropBubble(o.convId, localId)
            restore(o)
        } else markFailed(o, why)
        dash.toast(if (active) why else "${noun(o.kind)} to ${whoOf(o.convId)} not sent — $why", ToastType.Error)
    }

    /** Put a send's words back where they were written. */
    private fun restore(o: Outgoing) = when (o.kind) {
        OutKind.Reply -> editComposer(o.convId) { c ->
            c.copy(replyText = if (c.replyText.isBlank()) o.typed else o.typed + "\n" + c.replyText, quoted = c.quoted ?: o.quoted)
        }
        OutKind.Approve -> editComposer(o.convId) { it.copy(draftVisible = true, draftExpanded = true, draftEditing = false, draftText = o.text) }
        OutKind.Note -> _dialogs.update { it.copy(note = true, noteText = if (it.noteText.isBlank()) o.text else it.noteText) }
    }

    private fun markFailed(o: Outgoing, why: String) {
        outgoing[o.localId] = o.copy(failed = true)
        bubble(o.convId, o.localId, "failed", why)
    }

    /**
     * No answer: re-read the thread a few times (the server may still be
     * delivering) before deciding. Offline, the check waits for the next
     * successful read (a poll, the catch-up on reconnect).
     */
    private suspend fun reconcile(localId: String, e: Throwable) {
        outgoing[localId]?.let { outgoing[localId] = it.copy(checking = true, exhausted = false, failed = false) } ?: return
        val convId = outgoing[localId]!!.convId
        for ((i, wait) in RECONCILE_DELAYS_MS.withIndex()) {
            delay(wait)
            val cur = outgoing[localId] ?: return
            if (i == RECONCILE_DELAYS_MS.lastIndex) outgoing[localId] = cur.copy(exhausted = true)
            val msgs = try { inboxApi.messages(convId) } catch (x: Exception) { if (x is CancellationException) throw x; null } ?: continue
            applyServer(convId, msgs)
            if (outgoing[localId] == null) return
        }
    }

    /**
     * Match sends still on their way against the server's rows: a NEW row
     * with the same words (a note, a reply, a draft sent) confirms it; a
     * checked send the server still hasn't got is "Not sent".
     */
    private fun settle(convId: String, msgs: List<ThreadMsg>) {
        val mine = outgoing.values.filter { it.convId == convId }
        if (mine.isEmpty()) return
        val claimed = HashSet<String>()
        for (o in mine) {
            val hit = msgs.firstOrNull { s -> s.id !in o.known && s.id !in claimed && matches(o, s) }
            if (hit != null) {
                claimed += hit.id
                outgoing.remove(o.localId)
                dropBubble(convId, o.localId)
                // Checked and found: the same outcome a prompt answer would have had.
                if (o.checking && !o.failed) {
                    when (o.kind) {
                        OutKind.Approve -> dash.toast("AI draft approved & sent")
                        OutKind.Note -> dash.toast("Note saved")
                        OutKind.Reply -> {}
                    }
                    if (o.kind != OutKind.Note) refresh()
                }
            } else if (o.checking && o.exhausted && !o.failed) {
                markFailed(o, "Not delivered — the server never got it.")
                dash.toast("${noun(o.kind)} to ${whoOf(convId)} didn't go through — tap Retry on it to send again.", ToastType.Error)
            }
        }
    }

    private fun matches(o: Outgoing, s: ThreadMsg): Boolean {
        if (s.isSystem || s.inbound || s.isLocal) return false
        val same = s.body.trim() == o.text.trim()
        return when (o.kind) {
            OutKind.Reply -> !s.isNote && s.sender == "human_agent" && same
            OutKind.Approve -> !s.isNote && s.sender == "ai" && (o.text.isBlank() || same)
            OutKind.Note -> s.isNote && same
        }
    }

    /**
     * Retry a "Not sent" bubble. One whose first attempt got no answer is
     * looked for on the server first — it may have gone after all — and is
     * not sent again while the server can't be asked.
     */
    fun retrySend(localId: String) {
        val o = outgoing[localId] ?: return
        if (!o.failed) return
        outgoing[localId] = o.copy(failed = false, retried = true)
        bubble(o.convId, localId, "sending")
        viewModelScope.launch {
            if (o.checking) {
                val msgs = try { inboxApi.messages(o.convId) } catch (e: Exception) { if (e is CancellationException) throw e; null }
                if (msgs == null) {
                    outgoing[localId]?.let { markFailed(it, "Still no connection — try again in a moment.") }
                    dash.toast("Still can't reach the server — nothing was sent twice.", ToastType.Error)
                    return@launch
                }
                applyServer(o.convId, msgs)
                val cur = outgoing[localId] ?: run { dash.toast("It had already gone through — not sent twice."); return@launch }
                outgoing[localId] = cur.copy(checking = false, exhausted = false, known = cur.known + msgs.map { it.id })
            }
            deliver(localId)
        }
    }

    /** "Edit" on a "Not sent" bubble: the words go back to the box (or the note / draft) and the bubble goes. */
    fun editFailed(localId: String) {
        val o = outgoing[localId] ?: return
        if (!o.failed) return
        outgoing.remove(localId)
        dropBubble(o.convId, localId)
        restore(o)
    }

    // ── AI drafts ──
    fun expandDraft(v: Boolean) = _composer.update { it.copy(draftExpanded = v) }
    fun toggleDraftEditing() = _composer.update { it.copy(draftEditing = !it.draftEditing) }
    fun setDraftText(v: String) = _composer.update { it.copy(draftText = v) }
    fun dismissDraft() = _composer.update { it.copy(draftVisible = false, draftExpanded = false, draftText = "", draftEditing = false) }
    fun draftToComposer() = _composer.update {
        it.copy(replyText = it.draftText, draftVisible = false, draftExpanded = false, draftText = "", draftEditing = false)
    }.also { scheduleTranslate() }

    /** Send the AI draft (as edited). Confirmed exactly like a typed reply. */
    fun approveDraft() {
        val convId = _thread.value.activeId.ifEmpty { return }
        // One approval in flight per thread: a double tap never sends the draft twice.
        if (outgoing.values.any { it.convId == convId && it.kind == OutKind.Approve && !it.failed }) return
        val textToSend = _composer.value.draftText
        val o = Outgoing(
            localId = "optimistic-${AppClock.now()}-${++localSeq}", convId = convId, kind = OutKind.Approve,
            text = textToSend, known = knownIds(convId),
        )
        outgoing[o.localId] = o
        setMsgs(convId) { it + ThreadMsg(id = o.localId, direction = "outbound", sender = "ai", text = textToSend, createdAt = nowIso(), sendState = "sending") }
        dismissDraft()
        viewModelScope.launch { deliver(o.localId) }
    }

    /**
     * A fresh AI draft (a whole AI turn, on the long client). It lands on the
     * thread that asked for it, even if the agent has moved on meanwhile.
     */
    fun generateDraft() {
        val convId = _thread.value.activeId.ifEmpty { return }
        if (_composer.value.generatingDraft) return
        editComposer(convId) { it.copy(generatingDraft = true) }
        viewModelScope.launch {
            try {
                val d = api.conversations.generateDraft(convId)
                if (!d.isNullOrBlank()) {
                    if (_thread.value.activeId == convId) {
                        // The agent asked for it — open immediately.
                        _composer.update { it.copy(draftText = d, draftVisible = true, draftExpanded = true, draftEditing = false) }
                        dash.toast("Draft generated")
                    } else {
                        // A draft belongs to its thread: it waits there, never in another's box.
                        heldDrafts[convId] = d
                        dash.toast("Draft ready for ${whoOf(convId)} — open their chat to review it.")
                    }
                }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                if (conversationGone(e)) { dropGone(convId); return@launch }
                // A draft is read-only (nothing is sent or saved), so a lost answer
                // loses nothing: a timeout just means ask again.
                val slow = timedOut(e)
                dash.toast(
                    when {
                        // 502 here is the model failing, not the network.
                        statusOf(e) == 502 -> "Failed to generate draft. Neema couldn't write one just now — try again."
                        slow -> "Neema took too long to write a draft — nothing was sent. Try again."
                        else -> failMsg("Failed to generate draft", e)
                    },
                    if (slow) ToastType.Warning else ToastType.Error,
                )
            } finally {
                editComposer(convId) { it.copy(generatingDraft = false) }
            }
        }
    }

    // ── Attachments ──

    /**
     * Per-type ceilings BEFORE upload (the server's own): images 5 MB — an
     * oversized photo is downscaled and re-encoded like WhatsApp does, never
     * rejected — videos 150 MB (transcoded server-side), audio 16 MB, documents 18 MB.
     */
    fun addMedia(uris: List<Uri>) {
        if (uris.isEmpty()) return
        viewModelScope.launch {
            val accepted = withContext(Dispatchers.IO) {
                uris.mapNotNull { uri ->
                    val (name0, size) = queryMeta(uri)
                    var mime = cr.getType(uri) ?: guessMime(name0)
                    var name = name0
                    val isVideo = mime.startsWith("video/") || Regex("\\.(mov|hevc|mp4|m4v|3gp)$", RegexOption.IGNORE_CASE).containsMatchIn(name)
                    if (isVideo && !mime.startsWith("video/")) mime = guessMime(name)
                    val (limit, label) = when {
                        mime.startsWith("image/") -> MAX_IMAGE to "5 MB"
                        isVideo -> MAX_VIDEO to "150 MB"
                        mime.startsWith("audio/") -> MAX_AUDIO to "16 MB"
                        else -> MAX_DOC to "18 MB"
                    }
                    var bytes: ByteArray? = null
                    // HEIC and other formats WhatsApp won't take become JPEG too.
                    val needsJpeg = mime.startsWith("image/") && mime !in SENDABLE_IMAGES
                    if ((size > limit || needsJpeg) && mime.startsWith("image/") && mime != "image/gif") {
                        bytes = compressImage(uri)
                        if (bytes != null) { mime = "image/jpeg"; name = name.substringBeforeLast('.') + ".jpg" }
                    }
                    // upload-media refuses anything outside its ALLOWED_MIME with a 415;
                    // the web's file picker never offers such a file — say so up front.
                    if (!uploadable(mime, name)) {
                        withContext(Dispatchers.Main) { dash.toast("$name can't be sent — unsupported file type", ToastType.Error) }
                        return@mapNotNull null
                    }
                    if (bytes == null && size > limit) {
                        withContext(Dispatchers.Main) { dash.toast("$name is too large (max $label)", ToastType.Error) }
                        return@mapNotNull null
                    }
                    PickedMedia(
                        id = "$name-$size-${UUID.randomUUID().toString().take(6)}",
                        uri = uri, name = name, mime = mime, size = bytes?.size?.toLong() ?: size, bytes = bytes,
                    )
                }
            }
            if (accepted.isNotEmpty()) _composer.update { it.copy(media = it.media + accepted) }
        }
    }

    fun setMediaCaption(id: String, caption: String) =
        _composer.update { c -> c.copy(media = c.media.map { if (it.id == id) it.copy(caption = caption) else it }) }

    fun removeMedia(id: String) = _composer.update { c -> c.copy(media = c.media.filterNot { it.id == id }) }
    fun clearMedia() = _composer.update { it.copy(media = emptyList()) }

    /**
     * Send sequentially; each file carries its OWN caption (or none). A file
     * that fails stays in the tray with its caption and the reason; one whose
     * upload got no answer (a 150 MB video timing out, a connection dropping
     * halfway) is looked for in the thread before it is called failed — and
     * again before a retry uploads it a second time.
     */
    fun sendMedia() {
        val convId = _thread.value.activeId
        val items = _composer.value.media
        if (items.isEmpty() || convId.isEmpty() || _composer.value.uploading) return
        editComposer(convId) { it.copy(uploading = true, media = it.media.map { m -> m.copy(error = null) }) }
        viewModelScope.launch {
            val sent = mutableListOf<ThreadMsg>()
            val sentIds = HashSet<String>()
            val known = HashSet(knownIds(convId))
            var failed = 0
            try {
                for (item in items) {
                    // A file whose last attempt ended without an answer may be there already.
                    if (item.unconfirmed) {
                        findUpload(convId, item, known)?.let { hit -> sent += hit; sentIds += item.id; known += hit.id; continue }
                    }
                    try {
                        val m = inboxApi.upload(cr, convId, item)
                        sent += m; sentIds += item.id; known += m.id
                    } catch (e: Exception) {
                        if (e is CancellationException) throw e
                        if (conversationGone(e)) { dropGone(convId); return@launch }
                        val unknown = fateOf(e) == Fate.Unknown
                        if (unknown) {
                            findUpload(convId, item, known)?.let { hit -> sent += hit; sentIds += item.id; known += hit.id; continue }
                        }
                        failed++
                        val why = if (statusOf(e) == 401) "your session expired — sign in again, then tap Send" else uploadErrorOf(e)
                        editComposer(convId) { c -> c.copy(media = c.media.map { if (it.id == item.id) it.copy(error = why, unconfirmed = unknown) else it }) }
                        dash.toast("${item.name}: $why", ToastType.Error)
                    }
                }
                if (sent.isNotEmpty()) {
                    setMsgs(convId) { mergeThread(it, sent) }
                    // Only what went out leaves the tray; a failed file waits for a retry.
                    editComposer(convId) { c -> c.copy(media = c.media.filterNot { it.id in sentIds }) }
                    refresh()
                    dash.toast(
                        when {
                            failed > 0 -> "Sent ${sent.size}, $failed failed"
                            sent.size > 1 -> "${sent.size} files sent"
                            else -> "Media sent"
                        },
                        if (failed > 0) ToastType.Error else ToastType.Success,
                    )
                }
            } finally {
                editComposer(convId) { it.copy(uploading = false) }
            }
        }
    }

    /** The thread's new outbound file matching [item] (its kind and caption), if the server has it. */
    private suspend fun findUpload(convId: String, item: PickedMedia, known: Set<String>): ThreadMsg? {
        val msgs = try { inboxApi.messages(convId) } catch (e: Exception) { if (e is CancellationException) throw e; return null }
        val kind = when {
            item.mime.startsWith("image/") -> "image"
            item.mime.startsWith("video/") || item.name.substringAfterLast('.', "").lowercase() in setOf("mov", "hevc", "mp4", "m4v") -> "video"
            item.mime.startsWith("audio/") -> "audio"
            else -> null
        }
        val cap = item.caption.trim()
        return msgs.firstOrNull { s ->
            s.id !in known && !s.inbound && !s.isSystem && !s.isNote && s.sender == "human_agent" && s.mediaType != null &&
                (kind == null || s.mediaType == kind || s.mediaType.startsWith("$kind/")) &&
                (cap.isEmpty() || s.body.trim() == cap || s.mediaCaption?.trim() == cap)
        }
    }

    private fun queryMeta(uri: Uri): Pair<String, Long> {
        var name = uri.lastPathSegment?.substringAfterLast('/') ?: "file"
        var size = -1L
        runCatching {
            cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    c.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 }?.let { i -> c.getString(i)?.let { name = it } }
                    c.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 }?.let { i -> if (!c.isNull(i)) size = c.getLong(i) }
                }
            }
        }
        if (size < 0) size = runCatching { cr.openAssetFileDescriptor(uri, "r")?.use { it.length } }.getOrNull() ?: 0L
        return name to size
    }

    /** Max 2048px on the long side, JPEG, stepping quality down until it fits 5 MB. */
    private fun compressImage(uri: Uri): ByteArray? = runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        val longSide = maxOf(bounds.outWidth, bounds.outHeight).coerceAtLeast(1)
        var sample = 1
        while (longSide / (sample * 2) >= 2048) sample *= 2
        val decoded = cr.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: return null
        val scale = minOf(1f, 2048f / maxOf(decoded.width, decoded.height))
        val bmp = if (scale < 1f) Bitmap.createScaledBitmap(decoded, (decoded.width * scale).toInt().coerceAtLeast(1), (decoded.height * scale).toInt().coerceAtLeast(1), true) else decoded
        for (q in listOf(85, 70, 55, 40)) {
            val out = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, q, out)
            if (out.size() <= MAX_IMAGE) return out.toByteArray()
        }
        null
    }.getOrNull()

    private fun guessMime(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
        "jpg", "jpeg" -> "image/jpeg"; "png" -> "image/png"; "webp" -> "image/webp"; "gif" -> "image/gif"
        "heic", "heif" -> "image/heic"
        "pdf" -> "application/pdf"; "doc" -> "application/msword"
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "xls" -> "application/vnd.ms-excel"
        "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        "mp4" -> "video/mp4"; "3gp" -> "video/3gpp"; "mov" -> "video/quicktime"; "hevc" -> "video/hevc"; "m4v" -> "video/x-m4v"
        "ogg", "opus" -> "audio/ogg"; "aac" -> "audio/aac"; "mp3" -> "audio/mpeg"
        else -> "application/octet-stream"
    }

    // ═══════════════════════════ Reach-out (Ask Neema, invite, call) ═══════════════════════════

    /** Read-only: a failure just says why, and the question stays in the box. */
    suspend fun askNeema(question: String): String = try {
        api.askNeema(_thread.value.activeId, question).answer
    } catch (e: Exception) {
        if (e is CancellationException) throw e
        when {
            conversationGone(e) -> "This conversation no longer exists."
            statusOf(e) == 0 && timedOut(e) -> "Neema took too long to answer — try again."
            statusOf(e) == 0 || statusOf(e) == 401 || statusOf(e) == 429 -> whyFailed(e, "")
            else -> "Couldn't check right now — try again."
        }
    }

    /**
     * Neema delivers the confirmed FACTS in her own voice; the thread stays in
     * AI mode. This one reaches the customer, so a lost answer is checked: a
     * NEW message from Neema in the thread means it went; otherwise the agent
     * is told it may still be on its way — never "failed", which invites a
     * second send.
     */
    suspend fun answerViaNeema(facts: String): Pair<Boolean, String> {
        val convId = _thread.value.activeId
        val known = knownIds(convId)
        return try {
            true to "Neema sent: “${api.answerViaNeema(convId, facts).sent}”"
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            // Only to classify (the web tests its error message for "window"); never shown.
            val body = (e as? ApiException)?.body.orEmpty().lowercase()
            when {
                fateOf(e) == Fate.Unknown -> {
                    val hit = try { inboxApi.messages(convId) } catch (x: Exception) { if (x is CancellationException) throw x; null }
                        ?.lastOrNull { it.id !in known && !it.inbound && !it.isSystem && !it.isNote && it.sender == "ai" }
                    if (hit != null) {
                        loadMessages(convId, silent = true)
                        true to "Neema sent: “${hit.body}”"
                    } else false to "No answer from the server — Neema may still be sending it. Watch the thread before sending it again."
                }
                conversationGone(e) -> false to "This conversation no longer exists."
                status(e) == 409 || "window" in body ->
                    false to "Outside the messaging window — reply yourself when they next write."
                statusOf(e) == 0 || statusOf(e) == 401 || statusOf(e) == 429 -> false to whyFailed(e, "")
                else -> false to "Couldn't send right now — try again."
            }
        }
    }

    /** How a WhatsApp invite went. */
    sealed interface InviteResult {
        data object Sent : InviteResult
        /** Refused (not configured, a bad number, Meta said no) — open WhatsApp by hand instead. */
        data object Refused : InviteResult
        /** No answer: the template may have gone — don't send it twice. */
        data class Unknown(val message: String) : InviteResult
    }

    suspend fun invite(phone: String, name: String?): InviteResult = try {
        api.whatsappInvite(phone, name); InviteResult.Sent
    } catch (e: Exception) {
        if (e is CancellationException) throw e
        if (fateOf(e) == Fate.Unknown) InviteResult.Unknown("No answer from the server — the invite may still go through. Check with the customer before sending another.")
        else InviteResult.Refused
    }

    /**
     * Business-initiated WhatsApp call; no permission yet → ask for it automatically.
     * Only ever a real number: a web-chat visitor's `web_<hash>` key (or a Meta
     * PSID) is not dialable, whatever digits it happens to contain.
     */
    fun call(waId: String, name: String?) {
        if (isWebVisitor(waId) || waId.any { !it.isDigit() } || waId.length !in 7..15) return
        viewModelScope.launch {
            val r = dash.container.calls.initiateCall(waId, name)
            val err = r.exceptionOrNull() ?: return@launch
            val msg = err.message ?: ""
            if (msg.lowercase().contains("permission")) {
                try {
                    api.calls.requestPermission(waId)
                    dash.toast("Asked ${name?.trim()?.split(" ")?.firstOrNull()?.ifBlank { null } ?: "them"} for permission to call — you can call once they tap Allow.")
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                    dash.toast("Couldn't send the call request", ToastType.Error)
                }
            } else dash.toast(msg.ifBlank { "Couldn't place the call" }, ToastType.Error)
        }
    }

    companion object {
        const val MB = 1024L * 1024L
        /**
         * After a send got no answer: re-read the thread at these intervals
         * (the server may still be delivering it) before calling it failed.
         */
        val RECONCILE_DELAYS_MS = listOf(2_000L, 8_000L, 20_000L)
        /** A burst of frames becomes one list refetch this long after the first. */
        const val SOCKET_REFRESH_MS = 1_500L
        const val CATCH_UP_WINDOW_MS = 2_000L
        /** Conversation frames that move a row or a badge. */
        val MOVING_FRAMES = setOf("new_message", "message", "intercept_changed", "history_cleared")
        const val MAX_IMAGE = 5 * MB
        const val MAX_VIDEO = 150 * MB
        const val MAX_AUDIO = 16 * MB
        const val MAX_DOC = 18 * MB
        val SENDABLE_IMAGES = setOf("image/jpeg", "image/png", "image/webp", "image/gif")
        /** WhatsApp first (it can transact), then the social channels. */
        val CHAN_ORDER = listOf("whatsapp", "messenger", "facebook", "instagram", "tiktok", "email", "sms")
    }
}

/** Fetching an expired attachment back from Meta. */
sealed interface Recovery {
    data class Found(val url: String) : Recovery
    /** Meta no longer has it. */
    data object Gone : Recovery
    /** Couldn't ask (no connection, server trouble): try again. */
    data class Failed(val why: String) : Recovery
}

/** The customer's detected language — free, from translations cached on inbound rows. */
internal fun threadLangOf(t: ThreadUi): String? =
    t.messages[t.activeId]?.lastOrNull { it.inbound && it.translatedFrom != null }?.translatedFrom

/** Translate toggle: the agent's choice for this thread, else ON when the thread reads foreign. */
internal fun txOnOf(t: ThreadUi, c: ComposerUi): Boolean =
    t.activeId.isNotEmpty() && (c.txMode[t.activeId] ?: (threadLangOf(t) != null))

/** A genuine WhatsApp thread — a web-chat visitor rides the "whatsapp" channel but is not one. */
internal fun realWhatsApp(c: Conversation): Boolean = c.channel == "whatsapp" && !isWebVisitor(c.waId)

/**
 * The thread menu's "Invite to WhatsApp" shortcut follows CustomerSidebar:
 * only for a person with a real 7–15-digit phone on their profile and no
 * WhatsApp thread yet.
 */
internal fun inviteTarget(reach: Reach?, convId: String): String? =
    reach?.takeIf { it.convId == convId && !it.hasWhatsApp }?.phone?.let { p ->
        if (isWebVisitor(p.trim())) null else p.filter { it.isDigit() }.takeIf { it.length in 7..15 }
    }

internal fun channelLabel(ch: String?): String = when (ch) {
    "whatsapp" -> "WhatsApp"; "messenger" -> "Messenger"; "facebook" -> "Facebook"; "instagram" -> "Instagram"
    "tiktok" -> "TikTok"; "email" -> "Email"; "sms" -> "SMS"; null -> ""; else -> ch
}
