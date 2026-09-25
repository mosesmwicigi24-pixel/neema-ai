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
    // Re-read permissions when /me lands (can() reads plain values).
    val me by dash.me.collectAsState()
    val agents by dash.agents.collectAsState()
    // Web parity (owner's call): CustomerSidebar is open to every signed-in
    // agent and the CRM routes only check login. Only the stage editor stays
    // admin-only, which the server enforces too.
    val isAdmin = remember(me, agents) { dash.isAdmin }

    Column(modifier.fillMaxSize().background(c.bg2)) {
        if (!hideHeader) PanelHeader(onClose)
        val vm: CustomerViewModel = viewModel(key = "customer:${conversation.id}") { CustomerViewModel(dash, conversation) }
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
    val lastOrder = orders.maxByOrNull { Fmt.millis(it.createdAt) ?: 0L }
    val ctx = PanelCtx(p, orders, totalSpent, lastOrder, customStages, canEdit, canReply, isAdmin)

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { vm.load(showSpinner = false) }, modifier = Modifier.weight(1f)) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            Hero(vm, ctx, saving, conversation, onOpenIdentity)
            HorizontalDivider(color = c.hairline)
            QuickStats(ctx)
            HorizontalDivider(color = c.hairline)
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
    EnquiryCard(vm, canProduce)
    QuickActions(vm, ctx)
}

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
    val phoneDigits = (p.phone ?: "").filter { it.isDigit() }
    val reachable = phoneDigits.length in 7..15

    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 12.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Avatar(Fmt.displayName(p.name, p.waId), size = 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (!p.name.isNullOrEmpty()) {
                        Text(p.name, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text, maxLines = 1,
                            overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                    } else {
                        Text("Unknown", fontSize = 14.sp, fontStyle = FontStyle.Italic, color = c.muted)
                    }
                    if (p.nameConfirmed) Text(" ✓", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = Color(0xFF059669))
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val flag = Fmt.flagEmoji(p.countryIso)
                    if (flag.isNotEmpty()) Text("$flag ", fontSize = 12.sp)
                    Text(
                        Fmt.formatPhone(if (phoneDigits.length >= 7) p.phone else p.waId),
                        fontSize = 12.sp, color = c.muted, fontFamily = FontFamily.Monospace, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                }
                FlowRow(
                    Modifier.padding(top = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    val sm = stageMeta(p.leadStage)
                    Row(
                        Modifier.clip(RoundedCornerShape(50)).background(sm.color.dim()).padding(horizontal = 6.dp, vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(sm.dot))
                        Spacer(Modifier.width(4.dp))
                        Text(sm.label, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = sm.color)
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
        p.tier?.let { tier ->
            val tm = TIER_META[tier]
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                itemVerticalAlignment = Alignment.CenterVertically) {
                Hint(tm?.title) {
                    val fg = tm?.color ?: c.textMid
                    Text(
                        p.tierLabel ?: tm?.label ?: tier, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = fg,
                        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(fg.dim(0.1f))
                            .border(1.dp, tm?.border ?: c.hairline, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
                p.buyingRhythm?.cadenceLabel?.let { Text("Buys $it", fontSize = 10.sp, color = c.textMid) }
                if (p.buyingRhythm?.overdue == true) {
                    Hint("Past their usual buying gap — a good moment to reach out") {
                        Text(
                            "⏰ Overdue", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFB45309),
                            modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(Color(0xFFF59E0B).dim(0.1f))
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
                Hint("Open ${ch.channel} conversation") {
                    Row(
                        Modifier.clip(RoundedCornerShape(4.dp)).background(c.bg3).border(1.dp, c.border, RoundedCornerShape(4.dp))
                            .clickable {
                                // Non-WhatsApp channels have no wa_id identifier; this thread's own handle stands in.
                                val handle = ch.identifier ?: if (ch.channel == conversation.channel) conversation.handle else ""
                                onOpenIdentity(ch.channel, handle)
                            }
                            .padding(horizontal = 6.dp, vertical = 3.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ChannelBadge(ch.channel, 16.dp)
                        Spacer(Modifier.width(4.dp))
                        Text(ch.channel.replaceFirstChar { it.uppercase() }, fontSize = 10.sp, color = c.text)
                    }
                }
            }
            // A captured phone gives this customer a WhatsApp door before their first
            // WhatsApp message — shown only when no WhatsApp thread exists yet.
            val hasWa = p.channels.any { it.channel == "whatsapp" }
            if (!hasWa && reachable && ctx.canReply) {
                Hint("Send this customer a WhatsApp invite (delivers the approved template to their number)") {
                    Row(
                        Modifier.clip(RoundedCornerShape(4.dp)).background(WA_GREEN).border(1.dp, Color(0xFF1DA851), RoundedCornerShape(4.dp))
                            .clickable { vm.inviteToWhatsApp(phoneDigits) { url -> runCatching { uri.openUri(url) } } }
                            .padding(horizontal = 6.dp, vertical = 3.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ChannelBadge("whatsapp", 16.dp)
                        Spacer(Modifier.width(4.dp))
                        Text("Invite to WhatsApp", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                    }
                }
            }
            if (p.mergedIds.isNotEmpty()) {
                Text("+${p.mergedIds.size} merged", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = Color(0xFF7C3AED))
            }
        }

        // Reach-out actions: WhatsApp voice call + the approved template (re-opens
        // the chat / requests call permission). Only for a customer with a valid phone.
        if (reachable && ctx.canReply) {
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { vm.call(phoneDigits) },
                    modifier = Modifier.weight(1f).height(38.dp),
                    shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = WA_GREEN, contentColor = Color.White),
                    contentPadding = PaddingValues(horizontal = 8.dp),
                ) {
                    Icon(Icons.Default.Call, null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Call", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                }
                OutlinedButton(
                    onClick = { vm.sendTemplate(phoneDigits) },
                    enabled = !templateBusy,
                    modifier = Modifier.weight(1f).height(38.dp),
                    shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.outlinedButtonColors(containerColor = c.bg3, contentColor = c.textMid),
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
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
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
    Row(Modifier.fillMaxWidth()) {
        CustomerTab.entries.forEach { t ->
            val on = t == active
            Column(
                Modifier.weight(1f).clickable { onSelect(t) },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    t.label.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp,
                    color = if (on) c.text else c.muted, modifier = Modifier.padding(vertical = 10.dp),
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
private fun EnquiryCard(vm: CustomerViewModel, canProduce: Boolean) {
    val enquiry by vm.enquiry.collectAsState()
    val pushing by vm.pushing.collectAsState()
    val e = enquiry ?: return
    val c = Neema.colors
    val green = if (c.isDark) c.gold2 else Color(0xFF3A5C28)
    HorizontalDivider(color = c.hairline)
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
                    fontWeight = FontWeight.SemiBold, color = c.gold, modifier = Modifier.padding(top = 8.dp))
                "declined" -> Text("Dismissed", fontSize = 10.sp, color = c.muted, modifier = Modifier.padding(top = 8.dp))
                else -> if (canProduce) {
                    Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        TintButton(if (pushing) "Sending…" else "→ Push to production", c.gold, { vm.pushProduction() },
                            Modifier.weight(1f), filled = true, enabled = !pushing && e.pushable)
                        TintButton("Dismiss", c.muted, { vm.declineProduction() })
                    }
                    if (!e.pushable) {
                        Text("No linked hub product — set this order up in the hub manually.", fontSize = 9.sp, color = c.muted,
                            modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun QuickActions(vm: CustomerViewModel, ctx: PanelCtx) {
    if (!ctx.canEdit) return
    val c = Neema.colors
    val p = ctx.profile
    HorizontalDivider(color = c.hairline)
    Column(Modifier.fillMaxWidth().background(c.bg2).padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text("QUICK ACTIONS", fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp, color = c.textMid,
            modifier = Modifier.padding(bottom = 8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            TintButton("✓ Mark Won", Color(0xFF047857), { vm.setStage("won") }, Modifier.weight(1f))
            TintButton("✕ Mark Lost", Color(0xFFDC2626), { vm.setStage("lost") }, Modifier.weight(1f))
        }
        Spacer(Modifier.height(6.dp))
        TintButton("→ Advance Stage", c.text, {
            // Next along the forward path (custom stages included); Lost re-opens at Won, as on the web.
            val forward = listOf("new", "contacted", "qualified", "proposal", "negotiation") + ctx.customStages + "won"
            val idx = forward.indexOf(p.leadStage)
            val next = if (p.leadStage == "lost") "won" else forward[minOf(idx + 1, forward.size - 1)]
            if (next != p.leadStage) vm.setStage(next)
        }, Modifier.fillMaxWidth())
    }
}
