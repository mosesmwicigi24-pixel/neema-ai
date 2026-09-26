@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package ke.co.bethanyhouse.neema.feature.conversations.customer

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.conversations.isWebVisitor
import kotlin.math.roundToInt

/**
 * The customer profile / CRM panel beside a thread (components/ui/CustomerSidebar.tsx).
 *
 * CONTRACT — the inbox calls exactly this signature:
 *  - [conversation]: the open thread's row
 *  - [onClose]: hide the panel
 *  - [onOpenIdentity]: jump to this person's thread on another channel
 *  - [onNameChange]: the agent renamed the customer; the inbox patches its rows
 *  - [hideHeader]: the phone layout shows its own sheet header
 * Orders come from dash.orders; toasts go through dash.toast().
 *
 * The panel scrolls on its own; the made-to-order card and Quick Actions stay
 * pinned under the scroll, as on the web. It fills whatever [modifier] gives
 * it — a ~320dp side pane on tablets, a sheet or page on phones.
 */
@Composable
fun CustomerPanel(
    dash: DashboardViewModel,
    conversation: Conversation,
    onClose: () -> Unit,
    onOpenIdentity: (channel: String, externalId: String) -> Unit,
    onNameChange: (waId: String, newName: String) -> Unit,
    modifier: Modifier = Modifier,
    hideHeader: Boolean = false,
) {
    val c = Neema.colors
    val me by dash.me.collectAsState()
    val agents by dash.agents.collectAsState()
    val session by dash.session.collectAsState()
    // Web parity (owner's call): CustomerSidebar is open to every signed-in
    // agent and the CRM routes only check login. Only the stage editor stays
    // admin-only — shown exactly to whom PUT /settings/pipeline-stages admits
    // (superuser or the admin role), so nobody gets an editor that 403s.
    val isAdmin = remember(me, agents, session) { canEditPipelineStages(dash) }

    Column(modifier.fillMaxSize().background(c.bg2)) {
        if (!hideHeader) PanelHeader(onClose)
        val vm: CustomerViewModel = viewModel(key = "customer:${conversation.id}") { CustomerViewModel(dash, conversation) }
        // The web reloads the profile when the thread's row changes (new message, rename).
        LaunchedEffect(vm, conversation) { vm.sync(conversation) }
        // Live only while on screen: re-shown → refetch; foreground / reconnect / orders → catch up.
        DisposableEffect(vm) {
            vm.onShown()
            onDispose { vm.onHidden() }
        }
        PanelBody(
            vm = vm, dash = dash, conversation = conversation,
            canEdit = true,
            canReply = true,
            canProduce = true,
            isAdmin = isAdmin,
            onOpenIdentity = onOpenIdentity,
            onNameChange = onNameChange,
        )
    }
}

/** The server's rule for PUT /admin/settings/pipeline-stages (crm.py): superuser or role admin. */
internal fun canEditPipelineStages(dash: DashboardViewModel): Boolean {
    val s = dash.session.value
    val a = dash.currentAgent ?: dash.me.value
    return s?.isSuperuser == true || s?.role == "admin" || a?.isSuperuser == true || a?.role == "admin"
}

@Composable
private fun PanelHeader(onClose: () -> Unit) {
    val c = Neema.colors
    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp).height(48.dp), verticalAlignment = Alignment.CenterVertically) {
        Text("CUSTOMER", fontSize = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp, color = c.text, modifier = Modifier.weight(1f))
        IconButton(onClick = onClose) {
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, "Collapse sidebar", tint = c.muted)
        }
    }
    HorizontalDivider(color = c.hairline)
}

/** Order → the panel's order shape (the fallback when the profile carries no hub history). */
private fun Order.toPanel() = PanelOrder(
    id = id, orderNumber = hubOrderNumber, status = status, paymentStatus = paymentStatus,
    total = total, subtotal = subtotal, currencyCode = currency, createdAt = createdAt,
    items = items.map { PanelOrderItem(name = it.name, qty = it.qty, total = it.total) }, source = "whatsapp",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ColumnScope.PanelBody(
    vm: CustomerViewModel,
    dash: DashboardViewModel,
    conversation: Conversation,
    canEdit: Boolean,
    canReply: Boolean,
    canProduce: Boolean,
    isAdmin: Boolean,
    onOpenIdentity: (String, String) -> Unit,
    onNameChange: (String, String) -> Unit,
) {
    val c = Neema.colors
    val loading by vm.loading.collectAsState()
    val refreshing by vm.refreshing.collectAsState()
    val profile by vm.profile.collectAsState()
    val saving by vm.saving.collectAsState()
    val tab by vm.tab.collectAsState()
    val customStages by vm.customStages.collectAsState()
    val allOrders by dash.orders.collectAsState()

    if (loading && profile == null) { Loading(Modifier.weight(1f)); return }
    val p = profile ?: return

    // Prefer the hub history served on the profile (POS, web AND WhatsApp); fall
    // back to the local WhatsApp orders only when the profile has none.
    val orders = remember(p.orders, allOrders, conversation.waId) {
        p.orders ?: allOrders.filter { it.waId == conversation.waId || it.contactPhone == conversation.waId }.map { it.toPanel() }
    }
    // Lifetime spend is the hub's; the client sum is only a fallback.
    val totalSpent = p.totalSpent.takeIf { it != 0.0 } ?: orders.sumOf { it.amount }
    val lastOrder = orders.maxByOrNull { Fmt.millis(it.createdIso) ?: 0L }
    val ctx = PanelCtx(p, orders, totalSpent, lastOrder, customStages, canEdit, canReply, isAdmin)

    // The web pins the made-to-order card and Quick Actions under the scroll. On a
    // short pane (a landscape tablet, a small sheet) that pair would leave almost no
    // room to scroll, so there the card rides at the top of the scroll instead.
    BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
        val pinEnquiry = maxHeight >= PIN_ENQUIRY_MIN_HEIGHT
        Column(Modifier.fillMaxSize()) {
            PullToRefreshBox(isRefreshing = refreshing, onRefresh = { vm.refresh() }, modifier = Modifier.weight(1f)) {
                // The tab body's surface runs to the bottom even when a tab is short, as on the web.
                Column(Modifier.fillMaxSize().background(c.surface).verticalScroll(rememberScrollState())) {
                    LoadErrorBanner(vm, refreshing)
                    Hero(vm, ctx, saving, conversation, onOpenIdentity)
                    HorizontalDivider(color = c.hairline)
                    QuickStats(ctx)
                    HorizontalDivider(color = c.hairline)
                    if (!pinEnquiry) EnquiryCard(vm, canProduce, inline = true)
                    Tabs(tab) { vm.tab.value = it }
                    Column(Modifier.fillMaxWidth().background(c.surface).padding(16.dp)) {
                        when (tab) {
                            CustomerTab.Profile -> ProfileTab(vm, ctx, onNameChange, onOpenIdentity)
                            CustomerTab.Insights -> InsightsTab(ctx)
                            CustomerTab.Activity -> ActivityTab(ctx)
                        }
                    }
                }
            }
            if (pinEnquiry) EnquiryCard(vm, canProduce, inline = false)
            QuickActions(vm, ctx)
        }
    }
}

/**
 * The last profile GET failed: say why above what is still shown (the last good
 * profile, or the fallback from the chat row), with a Retry. The web shows the
 * fallback silently, so an agent offline in a matatu could not tell it apart
 * from a customer with no history.
 */
@Composable
private fun LoadErrorBanner(vm: CustomerViewModel, refreshing: Boolean) {
    val error by vm.loadError.collectAsState()
    val msg = error ?: return
    val c = Neema.colors
    val amber = if (c.isDark) Color(0xFFFCD34D) else Color(0xFF92400E)
    Row(
        Modifier.fillMaxWidth().background(if (c.isDark) Color(0xFFF59E0B).copy(alpha = 0.12f) else Color(0xFFFFFBEB))
            .padding(start = 16.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(msg, fontSize = 11.sp, lineHeight = 15.sp, color = amber, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(8.dp))
        TextButton(onClick = { vm.refresh() }, enabled = !refreshing, contentPadding = PaddingValues(horizontal = 10.dp)) {
            Text(if (refreshing) "Retrying…" else "Retry", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = amber)
        }
    }
    HorizontalDivider(color = if (c.isDark) Color(0xFFF59E0B).copy(alpha = 0.3f) else Color(0xFFFCD34D))
}

/** Below this the made-to-order card scrolls with the panel instead of being pinned. */
private val PIN_ENQUIRY_MIN_HEIGHT = 860.dp

// ── Hero ────────────────────────────────────────────────────────────────────

@Composable
private fun Hero(
    vm: CustomerViewModel,
    ctx: PanelCtx,
    saving: Boolean,
    conversation: Conversation,
    onOpenIdentity: (String, String) -> Unit,
) {
    val p = ctx.profile
    val c = Neema.colors
    val uri = LocalUriHandler.current
    val templateBusy by vm.templateBusy.collectAsState()
    val inviteBusy by vm.inviteBusy.collectAsState()
    val callBusy by vm.callBusy.collectAsState()
    // A dialable phone — never a web visitor's `web_<hash>` key (see realPhoneDigits).
    val phoneDigits = realPhoneDigits(p.phone)
    // A website chat visitor with no phone on file: say so, never a number made from the hash.
    val webVisitor = isWebVisitor(p.waId) && phoneDigits == null

    Column(Modifier.fillMaxWidth().background(c.bg2).padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 12.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Avatar(Fmt.displayName(p.name, p.waId), size = 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (!p.name.isNullOrEmpty()) {
                        Text(p.name, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text, maxLines = 1,
                            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                    } else {
                        // The thread header's words for an unnamed web visitor; otherwise the web's "Unknown".
                        Text(if (isWebVisitor(p.waId)) "Website visitor" else "Unknown", fontSize = 14.sp, fontStyle = FontStyle.Italic, color = c.muted)
                    }
                    if (p.nameConfirmed) Text(" ✓", fontSize = 9.sp, fontWeight = FontWeight.Bold, color = Color(0xFF059669))
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val flag = Fmt.flagEmoji(p.countryIso)
                    if (flag.isNotEmpty()) Text("$flag ", fontSize = 12.sp)
                    // The web: the phone when it has ≥ 7 digits, else the wa_id.
                    val phoneLike = (p.phone ?: "").count { it.isDigit() } >= 7 && !isWebVisitor(p.phone)
                    Text(
                        if (webVisitor) "Web chat" else Fmt.formatPhone(if (phoneLike) p.phone else p.waId),
                        fontSize = 12.sp, color = c.muted, fontFamily = if (webVisitor) null else FontFamily.Monospace,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                }
                FlowRow(
                    Modifier.padding(top = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    val sm = stageMeta(ctx.stage)
                    Row(
                        Modifier.clip(RoundedCornerShape(50)).background(sm.color.dim()).padding(horizontal = 6.dp, vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(sm.dot))
                        Spacer(Modifier.width(4.dp))
                        Text(sm.label, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = sm.color.themed())
                    }
                    p.countryIso?.takeIf { it.isNotEmpty() }?.let { iso ->
                        Hint(p.country ?: iso) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                // Coil renders PNG, not the SVG flag_url may point at.
                                val flagUrl = p.flagUrl?.takeUnless { it.endsWith(".svg") }
                                    ?: "https://flagcdn.com/w40/${iso.lowercase()}.png"
                                AsyncImage(flagUrl, iso, contentScale = ContentScale.Crop,
                                    modifier = Modifier.size(16.dp).clip(RoundedCornerShape(2.dp)).border(1.dp, c.hairline, RoundedCornerShape(2.dp)))
                                Spacer(Modifier.width(4.dp))
                                // An explicit (user-entered) country wins over the ISO's English name.
                                Text(p.country?.trim()?.ifEmpty { null } ?: Fmt.countryName(iso), fontSize = 10.sp, color = c.textMid)
                            }
                        }
                    }
                    if (saving) Text("saving…", fontSize = 10.sp, color = c.muted)
                }
            }
        }

        // The SERVER owns the score (it ranks the leads list on it).
        val score = minOf(100, p.leadScore.roundToInt())
        Row(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 4.dp)) {
            Text("Lead Score", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = c.muted, modifier = Modifier.weight(1f))
            Text("$score/100", fontSize = 10.sp, color = c.textMid)
        }
        ScoreBar(score)

        // Segment badge + buying rhythm — a quick read while chatting.
        p.tier?.takeIf { it.isNotEmpty() }?.let { tier ->
            val tm = TIER_META[tier]
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                itemVerticalAlignment = Alignment.CenterVertically) {
                Hint(tm?.title) {
                    val fg = tm?.color?.themed() ?: c.textMid
                    Text(
                        p.tierLabel?.ifEmpty { null } ?: tm?.label ?: tier, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = fg,
                        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(if (c.isDark || tm == null) fg.dim(0.1f) else tm.bg)
                            .border(1.dp, tm?.border ?: c.hairline, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
                p.buyingRhythm?.cadenceLabel?.takeIf { it.isNotEmpty() }?.let { Text("Buys $it", fontSize = 10.sp, color = c.textMid) }
                if (p.buyingRhythm?.overdue == true) {
                    Hint("Past their usual buying gap — a good moment to reach out") {
                        Text(
                            "⏰ Overdue", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFB45309).themed(),
                            modifier = Modifier.clip(RoundedCornerShape(4.dp))
                                .background(if (c.isDark) Color(0xFFF59E0B).dim(0.1f) else Color(0xFFFFFBEB))
                                .border(1.dp, Color(0xFFFCD34D), RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
                        )
                    }
                }
            }
        }

        // Channel chips (tap → that channel's thread), the WhatsApp invite, "+N merged".
        FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
            itemVerticalAlignment = Alignment.CenterVertically) {
            p.channels.forEach { ch ->
                val label = channelLabel(ch.channel, ch.identifier)
                Hint("Open $label conversation") {
                    Row(
                        Modifier.clip(RoundedCornerShape(4.dp)).background(if (c.isDark) c.bg3 else Color(0xFFF1F5F9)).border(1.dp, c.border, RoundedCornerShape(4.dp))
                            .clickable {
                                // Non-WhatsApp channels have no wa_id identifier; this thread's own handle stands in.
                                val handle = ch.identifier ?: if (ch.channel == conversation.channel) conversation.handle else ""
                                onOpenIdentity(ch.channel, handle)
                            }
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ChannelBadge(badgeKey(ch.channel, ch.identifier), 20.dp)
                        Spacer(Modifier.width(4.dp))
                        Text(label, fontSize = 10.sp, color = c.text)
                    }
                }
            }
            // A captured phone gives this customer a WhatsApp door before their first
            // WhatsApp message — shown only when no WhatsApp thread exists yet. A web
            // visitor's thread rides the "whatsapp" channel but is not one, so a
            // visitor who left a real number still gets the invite (to that number).
            val hasWa = p.channels.any { it.channel == "whatsapp" && !isWebVisitor(it.identifier) }
            if (!hasWa && phoneDigits != null && ctx.canReply) {
                Hint("Send this customer a WhatsApp invite (delivers the approved template to their number)") {
                    Row(
                        Modifier.clip(RoundedCornerShape(4.dp)).background(WA_GREEN).border(1.dp, Color(0xFF1DA851), RoundedCornerShape(4.dp))
                            .clickable(enabled = !inviteBusy) { vm.inviteToWhatsApp(phoneDigits) { url -> runCatching { uri.openUri(url) } } }
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ChannelBadge("whatsapp", 20.dp)
                        Spacer(Modifier.width(4.dp))
                        Text(if (inviteBusy) "Sending invite…" else "Invite to WhatsApp", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                    }
                }
            }
            if (p.mergedIds.isNotEmpty()) {
                Text("+${p.mergedIds.size} merged", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = Color(0xFF7C3AED).themed())
            }
        }

        // Reach-out actions: WhatsApp voice call + the approved template (re-opens
        // the chat / requests call permission). Only for a customer with a valid phone.
        if (phoneDigits != null && ctx.canReply) {
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { vm.call(phoneDigits) },
                    // One call at a time: a second tap while dialling would say "Already in a call".
                    enabled = !callBusy,
                    modifier = Modifier.weight(1f).height(36.dp),
                    shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = WA_GREEN, contentColor = Color.White,
                        disabledContainerColor = WA_GREEN.copy(alpha = 0.55f), disabledContentColor = Color.White,
                    ),
                    contentPadding = PaddingValues(horizontal = 8.dp),
                ) {
                    Icon(Icons.Default.Call, null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(if (callBusy) "Calling…" else "Call", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                }
                OutlinedButton(
                    onClick = { vm.sendTemplate(phoneDigits) },
                    enabled = !templateBusy,
                    modifier = Modifier.weight(1f).height(36.dp),
                    shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.outlinedButtonColors(containerColor = if (c.isDark) c.bg3 else Color(0xFFEEF2E8), contentColor = if (c.isDark) c.textMid else Color(0xFF3D5A30)),
                    border = androidx.compose.foundation.BorderStroke(1.dp, c.bg4),
                    contentPadding = PaddingValues(horizontal = 8.dp),
                ) {
                    Icon(Icons.Outlined.ChatBubbleOutline, null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(if (templateBusy) "Sending…" else "Send template", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
                }
            }
        }
    }
}

@Composable
private fun QuickStats(ctx: PanelCtx) {
    val c = Neema.colors
    val convs = ctx.profile.channels.sumOf { it.conversationCount }.takeIf { it > 0 } ?: 1
    Row(Modifier.fillMaxWidth().background(c.bg2).height(IntrinsicSize.Min)) {
        listOf("Orders" to "${ctx.orderCount}", "Spent" to Fmt.currency(ctx.totalSpent), "Convs" to "$convs")
            .forEachIndexed { i, (label, value) ->
                Column(Modifier.weight(1f).padding(horizontal = 8.dp, vertical = 10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(value, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(label, fontSize = 10.sp, color = c.textMid)
                }
                if (i < 2) VerticalDivider(color = c.hairline)
            }
    }
}

@Composable
private fun Tabs(active: CustomerTab, onSelect: (CustomerTab) -> Unit) {
    val c = Neema.colors
    Row(Modifier.fillMaxWidth().background(c.bg2)) {
        CustomerTab.entries.forEach { t ->
            val on = t == active
            Column(
                Modifier.weight(1f).clickable { onSelect(t) },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    t.label.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp,
                    color = if (on) c.text else c.muted, modifier = Modifier.padding(vertical = 8.dp),
                )
                Box(Modifier.fillMaxWidth().height(2.dp).background(if (on) c.text else Color.Transparent))
            }
        }
    }
    HorizontalDivider(color = c.hairline)
}

// ── Pinned footer ───────────────────────────────────────────────────────────

/** Made-to-order enquiry (measurement form → hub production). */
@Composable
private fun EnquiryCard(vm: CustomerViewModel, canProduce: Boolean, inline: Boolean) {
    val enquiry by vm.enquiry.collectAsState()
    val pushing by vm.pushing.collectAsState()
    val e = enquiry ?: return
    val c = Neema.colors
    val green = if (c.isDark) c.gold2 else Color(0xFF3A5C28)
    if (!inline) HorizontalDivider(color = c.hairline)
    Column(Modifier.fillMaxWidth().background(c.bg2).padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text("🧵 MADE-TO-ORDER REQUEST", fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp, color = c.textMid,
            modifier = Modifier.padding(bottom = 8.dp))
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(c.greenDim)
                .border(1.dp, c.hairline, RoundedCornerShape(8.dp)).padding(10.dp),
        ) {
            Text(e.productName?.ifEmpty { null } ?: "Custom item", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
            if (e.measurements.isNotEmpty()) {
                Text(e.measurements.entries.joinToString(" · ") { (k, v) -> "$k: ${v.display()}" }, fontSize = 10.sp, color = green,
                    modifier = Modifier.padding(top = 4.dp))
            }
            e.notes?.takeIf { it.isNotEmpty() }?.let { Text("Notes: $it", fontSize = 10.sp, color = green, modifier = Modifier.padding(top = 4.dp)) }
            when (e.status) {
                "pushed" -> Text("✓ In production" + (e.hubOrderNumber?.let { " · $it" } ?: ""), fontSize = 10.sp,
                    fontWeight = FontWeight.SemiBold, color = c.gold2, modifier = Modifier.padding(top = 8.dp))
                "declined" -> Text("Dismissed", fontSize = 10.sp, color = c.muted, modifier = Modifier.padding(top = 8.dp))
                else -> if (canProduce) {
                    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        TintButton(if (pushing) "Sending…" else "→ Push to production", c.gold, { vm.pushProduction() },
                            Modifier.weight(1f), filled = true, enabled = !pushing && e.pushable)
                        NeutralButton("Dismiss", { vm.declineProduction() }, textColor = c.textMid, enabled = !pushing)
                    }
                    if (!e.pushable) {
                        Text("No linked hub product — set this order up in the hub manually.", fontSize = 9.sp, color = c.muted,
                            modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
        }
    }
    if (inline) HorizontalDivider(color = c.hairline)
}

@Composable
private fun QuickActions(vm: CustomerViewModel, ctx: PanelCtx) {
    if (!ctx.canEdit) return
    val c = Neema.colors
    // A stage move in flight: an impatient second tap on Advance must not skip a stage.
    val busy by vm.stageBusy.collectAsState()
    HorizontalDivider(color = c.hairline)
    Column(Modifier.fillMaxWidth().background(c.bg2).padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text("QUICK ACTIONS", fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp, color = c.textMid,
            modifier = Modifier.padding(bottom = 8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            TintButton("✓ Mark Won", Color(0xFF047857).themed(), { vm.setStage("won") }, Modifier.weight(1f), enabled = !busy)
            TintButton("✕ Mark Lost", Color(0xFFDC2626).themed(), { vm.setStage("lost") }, Modifier.weight(1f), enabled = !busy)
        }
        Spacer(Modifier.height(6.dp))
        NeutralButton("→ Advance Stage", {
            // Next along the forward path (custom stages included); Lost re-opens at Won, as on the web.
            val next = nextStage(ctx.stage, ctx.customStages)
            if (next != ctx.stage) vm.setStage(next)
        }, Modifier.fillMaxWidth(), enabled = !busy)
    }
}
