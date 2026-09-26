package ke.co.bethanyhouse.neema.feature.conversations

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.Checklist
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import ke.co.bethanyhouse.neema.core.model.InboxSummary
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.channelStyle
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaFont
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

/** Email + SMS hidden for now — no traffic on those channels yet (as on the web). */
private val CHANNEL_TABS = listOf(
    Triple("all", "All", "All"),
    Triple("whatsapp", "WhatsApp", "WA"),
    Triple("facebook", "Facebook", "FB"),
    Triple("messenger", "Messenger", "MSG"),
    Triple("instagram", "Instagram", "IG"),
)
private val ALL_TAB_ACCENT = Palette.Amber500
private val ROW_ACCENT = Palette.Amber500
private val Green = Palette.Moss600

/** Lead-stage row chip palette (matches the sidebar pipeline): bg, fg, border. */
private val STAGE_CHIP = mapOf(
    "contacted" to Triple(Palette.Sky100, Palette.Sky700, Palette.Sky200),
    "qualified" to Triple(Palette.Amber100, Palette.Amber700, Palette.Amber200),
    "negotiation" to Triple(Palette.Violet100, Palette.Violet700, Palette.Violet200),
    "proposal" to Triple(Palette.Violet100, Palette.Violet700, Palette.Violet200),
    "won" to Triple(Palette.Green100, Palette.Green700, Palette.Green200),
    "lost" to Triple(Palette.Red100, Palette.Red700, Palette.Red200),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ConversationList(
    vm: ConversationsViewModel,
    inbox: InboxUi,
    listUi: ListUi,
    rows: List<RowGroup>,
    activeId: String,
    perms: InboxPerms,
    modifier: Modifier = Modifier,
    /** Held by the screen, so the list keeps its place while a thread covers it. */
    state: androidx.compose.foundation.lazy.LazyListState = rememberLazyListState(),
) {
    val c = Neema.colors
    val summary = inbox.summary
    val f = inbox.filters
    val me = perms.me
    // Badges are counted by the SERVER over every conversation; a count over a
    // paged list would be a count of one page. Fallbacks only before it answers —
    // and computed once per change, not on every recomposition of the list.
    val fallback = remember(inbox.cache, summary, me) { if (summary == null) localBadges(inbox.cache.values, me) else null }
    val unreadCount = summary?.unread ?: fallback?.unread ?: 0
    val humanCount = summary?.human ?: fallback?.human ?: 0
    val yoursCount = summary?.yours ?: fallback?.yours ?: 0
    val allTags = summary?.tags ?: fallback?.tags.orEmpty()
    val heldIds = remember(rows, listUi.selected) { vm.selectedHeldIds() }

    Column(modifier.background(c.bg2)) {
        // ── Header ──
        Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (listUi.selectMode) "${listUi.selected.size} selected" else "Chats",
                    fontSize = 14.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.14).sp, color = c.text, modifier = Modifier.weight(1f),
                )
                if (listUi.selectMode) {
                    TextButton(onClick = vm::selectAllOrClear) {
                        Text(if (listUi.selected.size == rows.size && rows.isNotEmpty()) "Clear" else "Select all", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = if (c.isDark) Green else Palette.Moss700)
                    }
                    TextButton(onClick = vm::exitSelect) { Text("Cancel", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = c.muted) }
                } else {
                    if (humanCount > 0) {
                        val lt = tint(Palette.LivePill, Palette.LivePillInk)
                        Text(
                            "$humanCount live", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = lt.fg, maxLines = 1, softWrap = false,
                            modifier = Modifier.clip(RoundedCornerShape(50)).background(lt.bg).padding(horizontal = 8.dp, vertical = 2.dp),
                        )
                    }
                    IconButton(onClick = { vm.enterSelect() }, modifier = Modifier.size(36.dp)) {
                        Icon(Icons.Outlined.Checklist, "Select several (or press and hold a chat)", tint = c.muted, modifier = Modifier.size(18.dp))
                    }
                }
                Box(
                    Modifier.size(30.dp).clip(RoundedCornerShape(8.dp)).background(if (listUi.showFilters) Green else Color.Transparent)
                        .clickable(onClick = vm::toggleFilters),
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Filled.FilterList, "Filters", tint = if (listUi.showFilters) Color.White else c.muted, modifier = Modifier.size(16.dp)) }
            }
            Spacer(Modifier.height(10.dp))
            // ── All / Unread / Read / Human / Yours ──
            // Equal fifths while they fit (the web's flex-1); at a large font scale each
            // tab keeps its whole label and count, and the row scrolls sideways instead.
            BoxWithConstraints(Modifier.fillMaxWidth()) {
            val fifth = (maxWidth - 16.dp) / 5
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf("all", "unread", "read", "human", "yours").forEach { t ->
                    val active = f.tab == t
                    val accent = when (t) { "unread" -> Palette.Moss700; "human" -> Palette.Amber700; "yours" -> Green; else -> Palette.Ink }
                    val count = when (t) { "unread" -> unreadCount; "human" -> humanCount; "yours" -> yoursCount; else -> 0 }
                    Row(
                        Modifier.widthIn(min = fifth).heightIn(min = 28.dp).clip(RoundedCornerShape(8.dp))
                            .background(if (active) accent else if (c.isDark) c.bg3 else Palette.StoneGreen)
                            .clickable(onClickLabel = t.replaceFirstChar { it.uppercase() }) { vm.setTab(t) }
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center,
                    ) {
                        Text(t.replaceFirstChar { it.uppercase() }, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = if (active) Color.White else if (c.isDark) c.textMid else Palette.Sage500, maxLines = 1, softWrap = false)
                        if (count > 0) {
                            Spacer(Modifier.width(3.dp))
                            Text(
                                if (count > 999) "999+" else "$count", fontSize = 10.sp, lineHeight = 10.sp, fontWeight = FontWeight.Bold, color = Color.White, maxLines = 1,
                                softWrap = false,
                                modifier = Modifier.clip(RoundedCornerShape(50)).background(if (active) Color.White.copy(alpha = 0.25f) else accent).padding(horizontal = 5.dp, vertical = 2.dp),
                            )
                        }
                    }
                }
            }
            }
            Spacer(Modifier.height(8.dp))
            // ── Search (the server searches names, phones and everything said) ──
            Row(
                Modifier.fillMaxWidth().heightIn(min = 32.dp).clip(RoundedCornerShape(8.dp))
                    .background(if (c.isDark) c.bg3 else Palette.StoneGreen).border(1.dp, if (c.isDark) c.border else Palette.Hairline2, RoundedCornerShape(8.dp))
                    .padding(horizontal = 10.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Filled.Search, null, tint = Palette.Sage300, modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(8.dp))
                Box(Modifier.weight(1f)) {
                    if (listUi.search.isEmpty()) Text("Start typing to search", fontSize = 13.sp, color = if (c.isDark) c.muted else Palette.Sage300, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    BasicTextField(
                        value = listUi.search, onValueChange = vm::setSearch, singleLine = true,
                        textStyle = TextStyle(fontFamily = NeemaFont, fontSize = 13.sp, color = c.text), cursorBrush = SolidColor(Green),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                if (listUi.search.isNotEmpty()) Icon(Icons.Filled.Close, "Clear", tint = c.muted, modifier = Modifier.size(16.dp).clickable { vm.setSearch("") })
            }
            Spacer(Modifier.height(10.dp))
            // ── Channel tabs — each in its own brand hue, with unread-message counts ──
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                CHANNEL_TABS.forEach { (id, label, short) ->
                    val active = f.channel == id
                    val accent = if (id == "all") ALL_TAB_ACCENT else channelStyle(id).color
                    val count = summary?.unreadMessages?.get(id) ?: fallback?.channels?.get(id) ?: 0
                    Box(Modifier.weight(1f)) {
                        Column(
                            Modifier.fillMaxWidth().heightIn(min = 40.dp).clip(RoundedCornerShape(8.dp))
                                .background(if (active) accent else accent.copy(alpha = if (c.isDark) 0.14f else 0.08f))
                                .border(1.dp, if (active) accent else accent.copy(alpha = 0.2f), RoundedCornerShape(8.dp))
                                .clickable(onClickLabel = label) { vm.setChannel(id) }.padding(vertical = 2.dp),
                            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
                        ) {
                            ChannelIcons.of(id)?.let { Icon(it, null, tint = if (active) Color.White else accent, modifier = Modifier.size(14.dp)) }
                                ?: Box(Modifier.size(10.dp).clip(CircleShape).background(if (active) Color.White else accent))
                            Spacer(Modifier.height(2.dp))
                            Text(short, fontSize = 8.sp, lineHeight = 8.sp, fontWeight = FontWeight.Bold, color = if (active) Color.White else ink(accent), maxLines = 1, softWrap = false)
                        }
                        if (count > 0) Box(
                            Modifier.align(Alignment.TopEnd).offset(4.dp, (-4).dp).defaultMinSize(minWidth = 14.dp, minHeight = 14.dp)
                                .clip(RoundedCornerShape(50)).background(if (active) Palette.Red500 else accent).padding(horizontal = 3.dp),
                            contentAlignment = Alignment.Center,
                        ) { Text(if (count > 999) "999+" else "$count", fontSize = 8.sp, lineHeight = 8.sp, fontWeight = FontWeight.Bold, color = Color.White, maxLines = 1, softWrap = false) }
                    }
                }
            }
            // ── Extra filters: tags, then mode ──
            if (listUi.showFilters) {
                Spacer(Modifier.height(8.dp))
                FlowRowCompat {
                    if (allTags.isNotEmpty()) {
                        FilterPill("All tags", f.tag == null) { vm.setTag(null) }
                        allTags.forEach { tag -> FilterPill(tag, f.tag == tag) { vm.setTag(if (f.tag == tag) null else tag) } }
                    }
                }
                if (allTags.isNotEmpty()) Spacer(Modifier.height(6.dp))
                FlowRowCompat {
                    listOf("all", "ai", "human", "paused").forEach { m -> FilterPill(m.replaceFirstChar { it.uppercase() }, f.mode == m) { vm.setMode(m) } }
                }
            }
        }
        HorizontalDivider(color = if (c.isDark) c.border else Palette.Hairline2)

        // ── The list — paged: the next page loads as it nears its end ──
        val nearEnd by remember { derivedStateOf { (state.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0) >= state.layoutInfo.totalItemsCount - 6 } }
        // Also tops up a page that doesn't fill the pane (nothing to scroll).
        LaunchedEffect(nearEnd, inbox.hasMore, inbox.loadingMore, rows.size) {
            if (nearEnd && inbox.hasMore && !inbox.loadingMore && !inbox.moreError) vm.loadMore()
        }
        // Rows on screen but the refresh failed: they stay, and the list says it's showing saved rows.
        if (inbox.loadError && rows.isNotEmpty()) {
            Row(
                Modifier.fillMaxWidth().background(if (c.isDark) Palette.Amber950.copy(alpha = 0.35f) else Palette.Amber50)
                    .padding(start = 16.dp, end = 8.dp, top = 6.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    if (inbox.errorText?.startsWith("No connection") == true) "No connection — showing saved conversations."
                    else "Couldn't refresh — showing saved conversations.",
                    fontSize = 12.sp, lineHeight = 16.sp, color = if (c.isDark) Palette.Amber400 else Palette.Amber800, modifier = Modifier.weight(1f),
                )
                Text(
                    "Retry", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Green,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClickLabel = "Retry loading conversations", onClick = vm::refresh)
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
        }
        PullToRefreshBox(isRefreshing = inbox.loading && rows.isNotEmpty(), onRefresh = vm::refresh, modifier = Modifier.weight(1f)) {
            LazyColumn(state = state, modifier = Modifier.fillMaxSize()) {
                if (rows.isEmpty()) item(key = "empty") {
                    Box(Modifier.fillMaxWidth().padding(vertical = 64.dp), contentAlignment = Alignment.Center) {
                        when {
                            // A filter's first page is on its way — "none found" would be a
                            // claim the server has not made yet.
                            inbox.loading -> EmptyText("Loading…")
                            // The web would say "Loading…" forever after a failure; say
                            // what happened and offer the one useful thing.
                            inbox.loadError -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    EmptyText("Couldn't load — ")
                                    Text(
                                        "Retry", fontSize = 14.sp, fontWeight = FontWeight.Medium, color = Green,
                                        modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClickLabel = "Retry loading conversations", onClick = vm::refresh)
                                            .padding(horizontal = 4.dp, vertical = 2.dp),
                                    )
                                }
                                inbox.errorText?.let {
                                    Text(it, fontSize = 12.sp, color = Palette.Sage400, textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.padding(top = 4.dp, start = 24.dp, end = 24.dp))
                                }
                            }
                            !inbox.freshLoaded -> EmptyText("Loading…")
                            else -> EmptyText("No conversations found")
                        }
                    }
                }
                items(rows, key = { it.key }, contentType = { "row" }) { g ->
                    // Only what THIS row draws: typing in the search box or picking another
                    // row leaves every other row's parameters equal, so they skip.
                    val act = if (activeId.isNotEmpty() && g.siblings.any { it.id == activeId }) activeId else ""
                    ConversationRow(g, act, me, listUi.selectMode, g.key in listUi.selected, onOpen = { id -> vm.select(id) }, vm = vm)
                }
                if (rows.isNotEmpty() && (inbox.loadingMore || inbox.hasMore)) item(key = "more") {
                    Box(Modifier.fillMaxWidth().padding(vertical = 16.dp), contentAlignment = Alignment.Center) {
                        if (inbox.loadingMore) Text("Loading more…", fontSize = 12.sp, color = Palette.Sage300)
                        else if (inbox.moreError) TextButton(onClick = { vm.loadMore(force = true) }) {
                            Text("Couldn't load more — Retry", fontSize = 12.sp, color = Green)
                        }
                        else TextButton(onClick = { vm.loadMore() }) { Text("Load more conversations", fontSize = 12.sp, color = Green) }
                    }
                }
            }
        }

        // ── Bulk action bar — only while selecting ──
        if (listUi.selectMode) {
            HorizontalDivider(color = if (c.isDark) c.border else Palette.Hairline2)
            Row(Modifier.fillMaxWidth().background(if (c.isDark) c.bg3 else Palette.SageStrip).padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        if (listUi.selected.isEmpty()) "Tap chats to select" else "${listUi.selected.size} chat${if (listUi.selected.size == 1) "" else "s"} selected",
                        fontSize = 11.sp, fontWeight = FontWeight.Medium, color = if (c.isDark) c.text else Palette.SageDeep,
                    )
                    if (listUi.selected.isNotEmpty()) Text(
                        if (heldIds.isEmpty()) "none are human-held" else "${heldIds.size} to hand back to Neema",
                        fontSize = 10.sp, color = c.muted,
                    )
                }
                Button(
                    onClick = vm::releaseSelected, enabled = !listUi.bulkBusy && heldIds.isNotEmpty(),
                    colors = ButtonDefaults.buttonColors(containerColor = Green, contentColor = Color.White, disabledContainerColor = Green.copy(alpha = 0.4f), disabledContentColor = Color.White), shape = RoundedCornerShape(8.dp),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp), modifier = Modifier.webHeight(32.dp),
                ) { Text(if (listUi.bulkBusy) "Releasing…" else "Release" + if (heldIds.isNotEmpty()) " ${heldIds.size}" else "", fontSize = 12.sp, fontWeight = FontWeight.SemiBold) }
            }
        }
    }
}

@Composable
private fun EmptyText(text: String) = Text(text, fontSize = 14.sp, color = if (Neema.colors.isDark) Neema.colors.muted else Palette.Sage300)

/** The tab and chip counts from the loaded rows, for the moment before the server's summary answers. */
private class LocalBadges(val unread: Int, val human: Int, val yours: Int, val tags: List<String>, val channels: Map<String, Int>)

private fun localBadges(all: Collection<ke.co.bethanyhouse.neema.core.model.Conversation>, me: String?): LocalBadges {
    var unread = 0; var human = 0; var yours = 0
    val tags = java.util.TreeSet<String>()
    // The chips sum unread MESSAGES; the Unread tab counts conversations.
    val channels = HashMap<String, Int>()
    for (c in all) {
        if (c.unread > 0) {
            unread++
            channels["all"] = (channels["all"] ?: 0) + c.unread
            channels[c.channel] = (channels[c.channel] ?: 0) + c.unread
        }
        if (c.interceptMode == "human") { human++; if (c.assignedAgentId == me) yours++ }
        tags += c.tags
    }
    return LocalBadges(unread, human, yours, tags.toList(), channels)
}

@Composable
private fun FilterPill(label: String, active: Boolean, onClick: () -> Unit) {
    val t = tint(Palette.Willow100, Palette.Willow600)
    Text(
        label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = if (active) Color.White else t.fg,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(if (active) Green else t.bg).clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ConversationRow(g: RowGroup, activeId: String, me: String?, selectMode: Boolean, picked: Boolean, onOpen: (String) -> Unit, vm: ConversationsViewModel) {
    val c = Neema.colors
    // The row shows the person; the ACTIVE conversation is whichever sibling is open.
    val conv = g.siblings.find { it.id == activeId } ?: g.rep
    val isActive = g.siblings.any { it.id == activeId }
    val hasUnread = g.unread > 0
    val multi = g.siblings.size > 1
    val name = inboxName(conv)
    // Human pickup on ANY of this person's channels shows on the row.
    val chipConv = g.siblings.find { it.interceptMode == "human" } ?: conv
    val stage = g.siblings.firstNotNullOfOrNull { it.leadStage?.takeIf { s -> s.isNotBlank() } }
    val orders = g.siblings.maxOf { it.ordersCount }.coerceAtLeast(0)
    val heldHere = g.siblings.any { it.interceptMode == "human" }
    val bg = when { picked -> Palette.PickedRow; isActive -> Palette.ActiveRow; else -> Color.Transparent }
    val edge = when { picked -> Green; isActive -> ROW_ACCENT; hasUnread -> Palette.UnreadEdge; else -> Color.Transparent }

    Row(
        Modifier.fillMaxWidth().background(if (c.isDark && bg != Color.Transparent) bg.copy(alpha = 0.12f) else bg)
            // Press and hold to start selecting — the WhatsApp gesture.
            .combinedClickable(
                onClick = { if (selectMode) vm.toggleRow(g.key) else onOpen(conv.id) },
                onLongClick = { if (!selectMode) vm.enterSelect(g.key) },
            )
            .height(IntrinsicSize.Min),
    ) {
        Box(Modifier.width(3.dp).fillMaxHeight().background(edge))
        Row(Modifier.weight(1f).padding(start = 13.dp, end = 16.dp, top = 12.dp, bottom = 12.dp), verticalAlignment = Alignment.Top) {
            if (selectMode) {
                Box(
                    // As on the web: faded whenever nobody human holds the row — picked or not —
                    // so the Release count never surprises; a little smaller until picked.
                    Modifier.padding(top = 12.dp, end = 12.dp).alpha(if (heldHere) 1f else 0.45f).size(18.dp)
                        .graphicsLayer { val s = if (picked) 1f else 0.92f; scaleX = s; scaleY = s }
                        .clip(RoundedCornerShape(6.dp))
                        .background(if (picked) Green else c.bg2)
                        .border(1.dp, if (picked) Green else Palette.SageRim, RoundedCornerShape(6.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    // A row Neema already handles stays selectable but reads as a no-op.
                    if (picked) Icon(Icons.Filled.Check, null, tint = Color.White, modifier = Modifier.size(12.dp))
                }
            }
            Box {
                Avatar(name, conv.avatarUrl, size = 38.dp)
                conv.countryIso?.takeIf { it.length == 2 }?.let { iso ->
                    AsyncImage(
                        "https://flagcdn.com/w20/${iso.lowercase()}.png", iso, contentScale = ContentScale.Crop,
                        modifier = Modifier.align(Alignment.TopEnd).offset(3.dp, (-2).dp).size(16.dp, 12.dp).clip(RoundedCornerShape(2.dp)).border(1.dp, c.bg2, RoundedCornerShape(2.dp)),
                    )
                }
                if (hasUnread) Box(Modifier.align(Alignment.TopStart).offset((-2).dp, (-2).dp).size(10.dp).clip(CircleShape).background(c.bg2).padding(2.dp).clip(CircleShape).background(ROW_ACCENT))
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(name, fontSize = 14.sp, fontWeight = if (hasUnread) FontWeight.SemiBold else FontWeight.Medium, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    // Repeat-buyer badge: completed (paid) orders.
                    if (orders > 0) Text(
                        if (orders > 99) "99+" else "$orders", fontSize = 9.sp, lineHeight = 9.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center, fontWeight = FontWeight.Bold, color = Color.White,
                        modifier = Modifier.padding(start = 6.dp).defaultMinSize(minWidth = 16.dp).clip(RoundedCornerShape(50))
                            .background(Brush.linearGradient(listOf(Palette.Amber500, Palette.Amber600))).padding(horizontal = 4.dp, vertical = 3.5.dp),
                    )
                    Text(
                        g.lastAt?.let { Fmt.timeAgo(it) } ?: "", fontSize = 10.sp,
                        fontWeight = if (hasUnread) FontWeight.SemiBold else FontWeight.Normal,
                        color = if (hasUnread) ink(Palette.Moss700) else if (c.isDark) c.muted else Palette.Sage300, maxLines = 1, softWrap = false, modifier = Modifier.padding(start = 6.dp),
                    )
                }
                Spacer(Modifier.height(3.dp))
                FlowRowCompat(spacing = 4.dp) {
                    // One chip per linked channel; tapping opens THAT channel's thread.
                    g.siblings.forEach { s ->
                        val st = channelStyle(s.channel)
                        val open = s.id == activeId
                        Box {
                            Text(
                                CH_SHORT[s.channel] ?: st.label, fontSize = 10.sp, fontWeight = FontWeight.Bold,
                                color = if (open) Color.White else ink(st.color), maxLines = 1,
                                modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(if (open) st.color else st.color.copy(alpha = if (c.isDark) 0.16f else 0.08f))
                                    .border(1.dp, if (open) st.color else st.color.copy(alpha = if (c.isDark) 0.45f else 0.2f), RoundedCornerShape(4.dp))
                                    .then(if (multi && !selectMode) Modifier.clickable(onClickLabel = "Open ${s.channel}") { onOpen(s.id) } else Modifier)
                                    .padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                            if (multi && s.unread > 0 && !open) Box(Modifier.align(Alignment.TopEnd).offset(3.dp, (-3).dp).size(6.dp).clip(CircleShape).background(Green))
                        }
                    }
                    if (stage != null && stage != "new") {
                        val (sbg, sfg, sbd) = STAGE_CHIP[stage] ?: STAGE_CHIP.getValue("contacted")
                        val st = tint(sbg, sfg, sbd)
                        Text(
                            stage.replaceFirstChar { it.uppercase() }, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = st.fg, maxLines = 1,
                            modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(st.bg).border(1.dp, st.border, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 1.dp),
                        )
                    }
                    conv.countryIso?.takeIf { it.isNotBlank() }?.let { iso ->
                        val ct = tint(Palette.Orange100, Palette.Orange700, Palette.Orange300)
                        Text(
                            Fmt.countryName(iso), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = ct.fg, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.widthIn(max = 110.dp).clip(RoundedCornerShape(4.dp)).background(ct.bg)
                                .border(1.dp, ct.border, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 1.dp),
                        )
                    }
                    if (chipConv.interceptMode != "ai") {
                        InterceptBadge(chipConv.interceptMode)
                        if (chipConv.interceptMode == "human" && chipConv.assignedAgentId != null) {
                            val mine = chipConv.assignedAgentId == me
                            Text(
                                if (mine) "● Yours" else "🔒 ${chipConv.assignedAgentName?.split(" ")?.firstOrNull()?.ifBlank { null } ?: "Agent"}",
                                fontSize = 10.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis,
                                color = ink(if (mine) Palette.Moss700 else Palette.Amber600), modifier = Modifier.widthIn(max = 100.dp),
                            )
                        }
                    }
                    if (hasUnread) Text(
                        if (g.unread > 99) "99+" else "${g.unread}", fontSize = 10.sp, lineHeight = 10.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center, fontWeight = FontWeight.Bold, color = Color.White,
                        modifier = Modifier.defaultMinSize(minWidth = 18.dp).clip(RoundedCornerShape(50)).background(Green).padding(horizontal = 4.dp, vertical = 4.dp),
                    )
                }
                Spacer(Modifier.height(3.dp))
                Text(
                    conv.lastMessagePreview?.takeIf { it.isNotBlank() } ?: "No messages yet",
                    fontSize = 12.sp, lineHeight = 16.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                    color = if (hasUnread) (if (c.isDark) c.textMid else Palette.SageDeep) else c.muted, fontWeight = if (hasUnread) FontWeight.Medium else FontWeight.Normal,
                )
            }
        }
    }
    HorizontalDivider(color = if (c.isDark) c.border else Palette.SageRule)
}
