package ke.co.bethanyhouse.neema.feature.conversations

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
    val loadingOlder: Boolean = false,
    /** Unread count when each thread was opened — places the "N new" divider. */
    val unreadSnapshot: Map<String, Int> = emptyMap(),
    val window: ConversationWindow? = null,
    val activity: List<ActivityEvent> = emptyList(),
    val activityOpen: Boolean = false,
    /** "" | "intercept" | "release" | "pause" — exactly-once control clicks. */
    val convBusy: String = "",
    /** Media re-fetched from Meta this session, by message id. */
    val recovered: Map<String, String> = emptyMap(),
)

data class ComposerUi(
    val replyText: String = "",
    /** Per-conversation translate toggle; absent = ON when the thread reads foreign. */
    val txMode: Map<String, Boolean> = emptyMap(),
    val txPreview: TxPreview? = null,
    val txBusy: Boolean = false,
    val quoted: Quoted? = null,
    val sending: Boolean = false,
    val draftVisible: Boolean = false,
    val draftExpanded: Boolean = false,
    val draftText: String = "",
    val draftEditing: Boolean = false,
    val generatingDraft: Boolean = false,
    val media: List<PickedMedia> = emptyList(),
    val uploading: Boolean = false,
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

    /** The people the list shows, grouped and sorted (filteredConvs → groupedConvs). */
    val rows: StateFlow<List<RowGroup>> = combine(_inbox, dash.session) { s, sess -> buildRows(s, sess?.agentId) }
        .flowOn(Dispatchers.Default)
        .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

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
    private var txJob: Job? = null
    private var draftJob: Job? = null
    private var windowJob: Job? = null
    private var activityJob: Job? = null

    private val fg get() = NeemaApplication.instance.foreground

    init {
        // Seed from this agent's snapshot so the inbox paints instantly, then fetch.
        viewModelScope.launch {
            dash.session.collect { s ->
                val id = s?.agentId ?: return@collect
                if (seededFor == id) return@collect
                seededFor = id
                seed(id)
                refresh()
            }
        }
        // Poll (push events are the primary signal) while foregrounded; refetch on return.
        viewModelScope.launch {
            while (isActive) {
                delay(60_000)
                if (!fg.value) { fg.first { it }; }
                refresh()
            }
        }
        viewModelScope.launch {
            var was = fg.value
            fg.collect { v -> if (v && !was) { refresh(); _thread.value.activeId.takeIf { it.isNotEmpty() }?.let { loadMessages(it, silent = true) } }; was = v }
        }
        // The open thread: poll as the socket's fallback (skip while backgrounded).
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

    private fun seed(agentId: String) {
        val snap = dash.container.snapshots.read(agentId, SNAP_KEY, ConversationPage.serializer()) ?: return
        if (snap.items.isEmpty()) return
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
        val f = _inbox.value.filters
        val key = filterKeyOf(f)
        _inbox.value.let { if (it.orderKey != key || it.orderIds.isEmpty()) _inbox.update { s -> s.copy(loading = true) } }

        viewModelScope.launch {
            runCatching { api.conversations.summary() }.onSuccess { s ->
                if (seq == firstSeq) { _inbox.update { it.copy(summary = s) }; dash.inboxSummary.value = s }
            } // on failure the badges keep their last value
        }
        viewModelScope.launch {
            val res = try {
                api.conversations.page(f, PAGE)
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                if (seq == firstSeq) _inbox.update { it.copy(loading = false) }
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
            _inbox.update { it.copy(freshLoaded = true, loading = false) }
            if (key == DEFAULT_KEY) {
                val id = myId
                withContext(Dispatchers.IO) { dash.container.snapshots.write(id, SNAP_KEY, ConversationPage.serializer(), res) }
            }
            // The open thread stays fresh even when it is not on page one.
            val w = watched
            if (w != null && w !in top) {
                runCatching { api.conversations.get(w) }.onSuccess { one -> if (seq == firstSeq) upsert(listOf(one)) }
            }
        }
    }

    /** The next page of people. */
    fun loadMore() {
        val c = cursor ?: return
        if (_inbox.value.loadingMore || dash.session.value == null) return
        val seq = ++moreSeq
        val f = _inbox.value.filters
        val key = filterKeyOf(f)
        _inbox.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            try {
                val res = api.conversations.page(f, PAGE, c)
                if (seq != moreSeq || key != filterKeyOf(_inbox.value.filters)) return@launch
                upsert(res.items)
                val o = _inbox.value
                if (o.orderKey != key) return@launch
                val have = o.orderIds.toSet()
                _inbox.update { it.copy(orderIds = o.orderIds + res.items.map { r -> r.id }.filter { id -> id !in have }, hasMore = res.nextCursor != null) }
                cursor = res.nextCursor
                pages += 1
            } catch (e: Exception) {
                if (e is CancellationException) throw e // scrolling again retries
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
            _inbox.update { it.copy(hasMore = false, orderKey = key, orderIds = emptyList()) }
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
        _list.update { it.copy(bulkBusy = true) }
        viewModelScope.launch {
            val results = ids.map { id -> async { runCatching { api.conversations.release(id) }.isSuccess } }.awaitAll()
            val failed = results.count { !it }
            val ok = ids.size - failed
            _list.update { it.copy(bulkBusy = false) }
            exitSelect()
            refresh()
            if (failed > 0) dash.toast("Released $ok — $failed failed", ToastType.Error)
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
        val changed = _thread.value.activeId != id
        _thread.update { it.copy(activeId = id, threadOpen = openThread || it.threadOpen, window = if (changed) null else it.window, activity = if (changed) emptyList() else it.activity) }
        watched = id
        loadMessages(id)
        if (changed) onActiveChanged(id)
    }

    fun closeThread() = _thread.update { it.copy(threadOpen = false) }

    private fun onActiveChanged(id: String) {
        // Reset the draft; a human-held thread fetches the latest AI draft (pill only).
        draftJob?.cancel()
        _composer.update { it.copy(draftVisible = false, draftExpanded = false, draftText = "", draftEditing = false, txPreview = null) }
        if (_inbox.value.cache[id]?.interceptMode == "human") {
            draftJob = viewModelScope.launch {
                runCatching { api.conversations.latestDraft(id) }.getOrNull()?.takeIf { it.isNotBlank() }?.let { d ->
                    if (_thread.value.activeId == id) _composer.update { it.copy(draftText = d, draftVisible = true) }
                }
            }
        }
        refreshWindow()
        loadActivity()
        scheduleTranslate()
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
                    dash.toast("Could not look up that chat.", ToastType.Error); return@launch
                }
                if (id == null) {
                    dash.toast("No conversation yet — they haven't messaged. Use Invite to WhatsApp.", ToastType.Warning)
                    return@launch
                }
                if (id !in _inbox.value.cache) {
                    // Revealed, not just cached: the paged list would drop it on the next refresh.
                    runCatching { api.conversations.get(id) }.onSuccess { reveal(listOf(it)) }
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
            val hit = runCatching { api.conversations.page(InboxQuery(channel = channel, q = externalId), 5).items }
                .getOrNull()?.map { it.normalized() }?.find(::matches)
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

    fun loadMessages(convId: String, silent: Boolean = false) {
        if (convId.isEmpty()) return
        if (!silent) _thread.update { it.copy(loading = true, error = false) }
        viewModelScope.launch {
            try {
                val msgs = inboxApi.messages(convId)
                // A fresh open replaces; a silent refresh merges so older pages survive.
                setMsgs(convId) { cur -> if (silent) mergeServer(cur, msgs) else mergeServer(cur.filter { it.isLocal }, msgs) }
                if (!silent) _thread.update { it.copy(hasMore = it.hasMore + (convId to (msgs.count { m -> !m.isSystem } >= THREAD_PAGE))) }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                // "No messages yet" over a failed fetch would read as an empty conversation.
                if (!silent) { _thread.update { it.copy(error = true) }; dash.toast("Failed to load messages", ToastType.Error) }
            } finally {
                if (!silent) _thread.update { it.copy(loading = false) }
            }
        }
    }

    /** Scrolling up past the loaded page fetches the previous page (via `before`). */
    fun loadOlder() {
        val t = _thread.value
        val convId = t.activeId
        if (convId.isEmpty() || t.loadingOlder || t.hasMore[convId] != true) return
        val oldest = (t.messages[convId] ?: emptyList()).firstOrNull { !it.isSystem && !it.isLocal } ?: return
        val before = oldest.createdAt ?: return
        _thread.update { it.copy(loadingOlder = true) }
        viewModelScope.launch {
            try {
                val older = inboxApi.messages(convId, before = before)
                _thread.update { it.copy(hasMore = it.hasMore + (convId to (older.count { m -> !m.isSystem } >= THREAD_PAGE))) }
                if (older.isNotEmpty()) setMsgs(convId) { mergeThread(it, older) }
            } catch (e: Exception) {
                if (e is CancellationException) throw e // quiet — scrolling again retries
            } finally {
                _thread.update { it.copy(loadingOlder = false) }
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
                val ev = runCatching { api.conversations.activity(id) }.getOrDefault(emptyList())
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

    fun recoverMedia(messageId: String, onDone: (String?) -> Unit) {
        viewModelScope.launch {
            val url = runCatching { api.conversations.recoverMedia(messageId).mediaUrl }.getOrNull()?.takeIf { it.isNotBlank() }
            if (url != null) {
                _thread.update { it.copy(recovered = it.recovered + (messageId to url)) }
                _thread.value.activeId.takeIf { it.isNotEmpty() }?.let { loadMessages(it, silent = true) }
            }
            onDone(url)
        }
    }

    // ═══════════════════════════ Live events ═══════════════════════════

    private fun onSocket(e: JsonObject) {
        val type = e.s("type")
        val convId = e.s("conversationId") ?: e.s("conversation_id")
        val active = _thread.value.activeId
        // Any thread moving means rows / badges moved: refetch shortly (coalesced).
        if (type == "new_message" || type == "intercept_changed" || type == "history_cleared") {
            socketRefreshJob?.cancel()
            socketRefreshJob = viewModelScope.launch { delay(1500); refresh() }
        }
        if (convId == null || convId != active) return
        when (type) {
            "ai_draft_ready" -> _composer.update {
                it.copy(draftText = e.s("draft") ?: "", draftVisible = true, draftExpanded = false, draftEditing = false)
            }
            "new_message" -> {
                val msg = ThreadMsg(
                    id = e.s("id") ?: "ws-${UUID.randomUUID()}",
                    type = "message",
                    direction = e.s("direction") ?: "outbound",
                    sender = e.s("sender") ?: "ai",
                    text = e.s("text"),
                    createdAt = e.s("created_at") ?: nowIso(),
                    mediaType = e.s("mediaType"),
                    mediaId = e.s("mediaId"),
                    mediaUrl = e.s("mediaUrl"),
                    mediaCaption = e.s("mediaCaption"),
                    mimeType = e.s("mimeType"),
                    filename = e.s("filename"),
                    // Sent-in-their-language replies carry the human's English.
                    translation = e.s("translation"),
                    translatedFrom = e.s("translatedFrom"),
                    replyTo = (e["replyTo"] as? JsonObject)?.let { runCatching { NeemaJson.decodeFromJsonElement(QuotedRef.serializer(), it) }.getOrNull() },
                )
                setMsgs(active) { existing ->
                    when {
                        // Primary dedup: exact DB id.
                        existing.any { it.id == msg.id } -> existing
                        // Audio replies broadcast before the DB row commits carry a made-up
                        // id: guard with media_url + direction within 15 seconds.
                        msg.mediaUrl != null && existing.any { x ->
                            x.mediaUrl == msg.mediaUrl && x.direction == msg.direction && kotlin.math.abs(x.millis - msg.millis) < 15_000
                        } -> existing
                        // Our own reply echoing back while its optimistic bubble is still up.
                        msg.sender == "human_agent" && existing.any { x ->
                            x.id.startsWith("optimistic-") && !x.isNote && x.body.trim() == msg.body.trim()
                        } -> existing
                        else -> existing + msg
                    }
                }
            }
            "translations" -> {
                val items = (e["items"] as? JsonArray)?.mapNotNull { it as? JsonObject } ?: return
                val byId = items.associateBy { it.s("id") ?: "" }
                setMsgs(active) { existing ->
                    existing.map { x ->
                        val t = byId[x.id]
                        if (t == null || x.translation != null) x else x.copy(translation = t.s("text"), translatedFrom = t.s("lang"))
                    }
                }
            }
            "intercept_changed" -> {
                val evt = systemEventFromWs(e) ?: return
                setMsgs(active) { existing ->
                    // One live pill per kind: a repeat fire is skipped.
                    if (existing.any { it.id.startsWith("live-evt-") && it.eventKind == evt.eventKind }) existing
                    else existing + evt
                }
            }
            "history_cleared" -> {
                setMsgs(active) { emptyList() }
                dash.toast("History cleared by ${e.s("clearedBy") ?: "an agent"}")
            }
        }
    }

    // ═══════════════════════════ Conversation actions ═══════════════════════════

    private fun busy(kind: String, block: suspend () -> Unit) {
        if (_thread.value.convBusy.isNotEmpty()) return
        _thread.update { it.copy(convBusy = kind) }
        viewModelScope.launch {
            try { block() } finally { _thread.update { it.copy(convBusy = "") } }
        }
    }

    private fun status(e: Throwable) = (e as? ApiException)?.status ?: 0

    fun intercept(id: String) = busy("intercept") {
        try {
            api.conversations.intercept(id)
            refresh()
            dash.toast("Conversation claimed — you now control replies")
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            dash.toast(if (status(e) == 409) "Already claimed by another agent" else "Failed to claim conversation", ToastType.Error)
        }
    }

    fun release(id: String) = busy("release") {
        try {
            api.conversations.release(id)
            refresh()
            dash.toast("Conversation released back to AI")
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            dash.toast("Failed to release", ToastType.Error)
        }
    }

    fun pause(id: String) = busy("pause") {
        try {
            api.conversations.pause(id)
            refresh()
            dash.toast("Paused — Neema holds all replies until you resume")
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            dash.toast(if (status(e) == 409) "Handled by another agent — they must pause it" else "Failed to pause", ToastType.Error)
        }
    }

    fun transfer(agentId: String, agentName: String?) {
        val id = _thread.value.activeId.ifEmpty { return }
        busy("release") {
            try {
                api.conversations.transfer(id, agentId)
                _dialogs.update { it.copy(transfer = false) }
                refresh()
                dash.toast("Transferred to ${agentName ?: "agent"}")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                dash.toast("Failed to transfer", ToastType.Error)
            }
        }
    }

    fun close(id: String) {
        viewModelScope.launch {
            try {
                api.conversations.close(id)
                refresh()
                dash.toast("Conversation closed")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                dash.toast("Failed to close conversation", ToastType.Error)
            }
        }
    }

    fun showTransfer(v: Boolean) = _dialogs.update { it.copy(transfer = v) }
    fun showNote(v: Boolean) = _dialogs.update { it.copy(note = v) }
    fun setNoteText(v: String) = _dialogs.update { it.copy(noteText = v) }
    fun showClear(v: Boolean) = _dialogs.update { it.copy(clearConfirm = v) }

    fun saveNote() {
        val convId = _thread.value.activeId
        val text = _dialogs.value.noteText.trim()
        if (text.isEmpty() || convId.isEmpty()) return
        val optimistic = ThreadMsg(
            id = "optimistic-note-${System.currentTimeMillis()}", direction = "outbound", sender = "human_agent",
            text = text, isNote = true, createdAt = nowIso(),
        )
        setMsgs(convId) { it + optimistic }
        _dialogs.update { it.copy(note = false, noteText = "") }
        dash.toast("Note saved")
        viewModelScope.launch {
            try {
                api.conversations.addNote(convId, text)
                val msgs = inboxApi.messages(convId)
                setMsgs(convId) { mergeServer(it, msgs) }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                setMsgs(convId) { l -> l.filterNot { it.id.startsWith("optimistic-note-") } }
                _dialogs.update { it.copy(note = true, noteText = text) }
                dash.toast("Failed to save note", ToastType.Error)
            }
        }
    }

    fun clearHistory() {
        val convId = _thread.value.activeId.ifEmpty { return }
        _dialogs.update { it.copy(clearing = true) }
        viewModelScope.launch {
            try {
                api.conversations.clearHistory(convId)
                setMsgs(convId) { emptyList() }
                _dialogs.update { it.copy(clearConfirm = false) }
                refresh()
                dash.toast("Chat history cleared")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                dash.toast(
                    if (status(e) == 403) "You don't have permission to clear chat history" else "Failed to clear history",
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

    fun sendReply() {
        val c = _composer.value
        val convId = _thread.value.activeId
        if (c.replyText.isBlank() || convId.isEmpty() || c.sending) return
        val conv = activeConv()
        _composer.update { it.copy(sending = true) }
        viewModelScope.launch {
            // Same channel → a native threaded reply. A quote from ANOTHER channel
            // can't be threaded, so it rides as a text prefix.
            val quoted = c.quoted
            val sameChannel = quoted != null && quoted.channel == (conv?.channel ?: "whatsapp")
            val replyToId = if (sameChannel) quoted?.msgId else null
            val prefix = if (quoted != null && !sameChannel)
                "↩ Re (${channelLabel(quoted.channel)}): \"${quoted.text.take(180)}\"\n\n" else ""
            val text = prefix + c.replyText
            var sendText = text
            var origText: String? = null
            var origLang: String? = null
            if (txOn()) {
                // Toggle ON → the customer receives their language; the English rides
                // along as the gray line. Any failure falls open to sending English.
                try {
                    val src = text.trim()
                    val p = _composer.value.txPreview
                    val tx = if (p != null && p.src == src) p.text to p.lang
                    else api.conversations.translateReply(convId, src).let { it.text to it.lang }
                    if (tx.first.isNotBlank() && tx.first.trim() != src) { sendText = tx.first; origText = src; origLang = tx.second }
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                }
            }
            val optimistic = ThreadMsg(
                id = "optimistic-${System.currentTimeMillis()}", direction = "outbound", sender = "human_agent",
                text = sendText, translation = origText, translatedFrom = origLang, createdAt = nowIso(),
                replyTo = if (replyToId != null && quoted != null)
                    QuotedRef(replyToId, quoted.text, quoted.sender, quoted.mediaType, quoted.mediaUrl) else null,
            )
            setMsgs(convId) { it + optimistic }
            _composer.update { it.copy(replyText = "", quoted = null, txPreview = null) }
            try {
                inboxApi.reply(convId, sendText, replyToId, origText, origLang)
                val msgs = inboxApi.messages(convId)
                // The server's row replaces the optimistic bubble (mergeServer).
                setMsgs(convId) { l -> mergeServer(l, msgs) }
                refresh()
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                setMsgs(convId) { l -> l.filterNot { it.id.startsWith("optimistic-") } }
                _composer.update { it.copy(replyText = text, quoted = quoted) }
                dash.toast(((e as? ApiException)?.detail ?: e.message)?.take(160)?.ifBlank { null } ?: "Failed to send message", ToastType.Error)
            } finally {
                _composer.update { it.copy(sending = false) }
            }
        }
    }

    // ── AI drafts ──
    fun expandDraft(v: Boolean) = _composer.update { it.copy(draftExpanded = v) }
    fun toggleDraftEditing() = _composer.update { it.copy(draftEditing = !it.draftEditing) }
    fun setDraftText(v: String) = _composer.update { it.copy(draftText = v) }
    fun dismissDraft() = _composer.update { it.copy(draftVisible = false, draftExpanded = false, draftText = "", draftEditing = false) }
    fun draftToComposer() = _composer.update {
        it.copy(replyText = it.draftText, draftVisible = false, draftExpanded = false, draftText = "", draftEditing = false)
    }.also { scheduleTranslate() }

    fun approveDraft() {
        val convId = _thread.value.activeId.ifEmpty { return }
        val textToSend = _composer.value.draftText
        val optimistic = ThreadMsg(
            id = "optimistic-${System.currentTimeMillis()}", direction = "outbound", sender = "ai",
            text = textToSend, createdAt = nowIso(),
        )
        setMsgs(convId) { it + optimistic }
        dismissDraft()
        viewModelScope.launch {
            try {
                api.conversations.approveDraft(convId, textToSend.ifEmpty { null })
                val msgs = inboxApi.messages(convId)
                setMsgs(convId) { mergeServer(it, msgs) }
                refresh()
                dash.toast("AI draft approved & sent")
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                setMsgs(convId) { l -> l.filterNot { it.id.startsWith("optimistic-") } }
                _composer.update { it.copy(draftVisible = true, draftExpanded = true, draftText = textToSend) }
                dash.toast("Failed to approve draft", ToastType.Error)
            }
        }
    }

    fun generateDraft() {
        val convId = _thread.value.activeId.ifEmpty { return }
        _composer.update { it.copy(generatingDraft = true) }
        viewModelScope.launch {
            try {
                val d = api.conversations.generateDraft(convId)
                if (!d.isNullOrBlank()) {
                    // The agent asked for it — open immediately.
                    _composer.update { it.copy(draftText = d, draftVisible = true, draftExpanded = true, draftEditing = false) }
                    dash.toast("Draft generated")
                }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                dash.toast("Failed to generate draft", ToastType.Error)
            } finally {
                _composer.update { it.copy(generatingDraft = false) }
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

    /** Send sequentially; each file carries its OWN caption (or none). */
    fun sendMedia() {
        val convId = _thread.value.activeId
        val items = _composer.value.media
        if (items.isEmpty() || convId.isEmpty() || _composer.value.uploading) return
        _composer.update { it.copy(uploading = true) }
        viewModelScope.launch {
            val sent = mutableListOf<ThreadMsg>()
            var failed = 0
            try {
                for (it in items) {
                    try {
                        sent += inboxApi.upload(cr, convId, it)
                    } catch (e: Exception) {
                        if (e is CancellationException) throw e
                        failed++
                        dash.toast("${it.name}: ${(e as? ApiException)?.detail ?: e.message ?: "failed"}", ToastType.Error)
                    }
                }
                if (sent.isNotEmpty()) {
                    setMsgs(convId) { mergeThread(it, sent) }
                    clearMedia()
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
                _composer.update { it.copy(uploading = false) }
            }
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

    suspend fun askNeema(question: String): String = try {
        api.askNeema(_thread.value.activeId, question).answer
    } catch (e: Exception) {
        if (e is CancellationException) throw e
        "Couldn't check right now — try again."
    }

    /** Neema delivers the confirmed FACTS in her own voice; the thread stays in AI mode. */
    suspend fun answerViaNeema(facts: String): Pair<Boolean, String> = try {
        true to "Neema sent: “${api.answerViaNeema(_thread.value.activeId, facts).sent}”"
    } catch (e: Exception) {
        if (e is CancellationException) throw e
        val msg = (e as? ApiException)?.detail ?: e.message ?: ""
        false to (if (status(e) == 409 || msg.lowercase().contains("window"))
            "Outside the messaging window — reply yourself when they next write."
        else "Couldn't send right now — try again.")
    }

    suspend fun invite(phone: String, name: String?): Boolean = runCatching { api.whatsappInvite(phone, name) }.isSuccess

    /** Business-initiated WhatsApp call; no permission yet → ask for it automatically. */
    fun call(waId: String, name: String?) {
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
        const val MAX_IMAGE = 5 * MB
        const val MAX_VIDEO = 150 * MB
        const val MAX_AUDIO = 16 * MB
        const val MAX_DOC = 18 * MB
        val SENDABLE_IMAGES = setOf("image/jpeg", "image/png", "image/webp", "image/gif")
        /** WhatsApp first (it can transact), then the social channels. */
        val CHAN_ORDER = listOf("whatsapp", "messenger", "facebook", "instagram", "tiktok", "email", "sms")
    }
}

/** The customer's detected language — free, from translations cached on inbound rows. */
internal fun threadLangOf(t: ThreadUi): String? =
    t.messages[t.activeId]?.lastOrNull { it.inbound && it.translatedFrom != null }?.translatedFrom

/** Translate toggle: the agent's choice for this thread, else ON when the thread reads foreign. */
internal fun txOnOf(t: ThreadUi, c: ComposerUi): Boolean =
    t.activeId.isNotEmpty() && (c.txMode[t.activeId] ?: (threadLangOf(t) != null))

internal fun channelLabel(ch: String?): String = when (ch) {
    "whatsapp" -> "WhatsApp"; "messenger" -> "Messenger"; "facebook" -> "Facebook"; "instagram" -> "Instagram"
    "tiktok" -> "TikTok"; "email" -> "Email"; "sms" -> "SMS"; null -> ""; else -> ch
}
