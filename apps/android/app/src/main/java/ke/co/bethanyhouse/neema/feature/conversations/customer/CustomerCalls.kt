package ke.co.bethanyhouse.neema.feature.conversations.customer

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.CallPermission
import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.feature.calls.firstNameOf
import ke.co.bethanyhouse.neema.feature.calls.permissionLines
import androidx.compose.ui.draw.alpha
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.util.liveAgo
import ke.co.bethanyhouse.neema.feature.calls.CallIcons
import ke.co.bethanyhouse.neema.feature.calls.CallTone
import ke.co.bethanyhouse.neema.feature.calls.agentFirst
import ke.co.bethanyhouse.neema.feature.calls.callDuration
import ke.co.bethanyhouse.neema.feature.calls.callRowWords

/**
 * The panel's "Calls" section (CALLING_UX.md §7): this customer's last calls —
 * outcome, time, length, who took it — and how many still owe them a call
 * back. "All calls" opens the Calls view on them.
 */
@Composable
internal fun CallsSection(vm: CustomerViewModel, dash: DashboardViewModel) {
    val key = vm.callsKey() ?: return
    val calls by vm.recentCalls.collectAsState()
    val permission by vm.callPermission.collectAsState()
    val request by vm.callRequest.collectAsState()
    LaunchedEffect(vm, key) {
        vm.loadCalls()
        vm.loadPermission()
        vm.watchCalls()
    }
    val c = Neema.colors
    val list = calls ?: return
    val open = list.count { it.followUpOpen }
    Column(Modifier.fillMaxWidth().background(c.bg2).padding(start = 16.dp, end = 8.dp, top = 8.dp, bottom = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "CALLS", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp, color = c.muted,
                modifier = Modifier.semantics { heading() },
            )
            if (open > 0) {
                Spacer(Modifier.width(8.dp))
                Text(
                    "$open to call back", fontSize = 10.sp, fontWeight = FontWeight.SemiBold,
                    color = if (c.isDark) Palette.Red300 else Palette.Red700,
                    modifier = Modifier.clip(RoundedCornerShape(50)).background(Palette.Red500.copy(alpha = 0.12f))
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
            Spacer(Modifier.weight(1f))
            if (list.isNotEmpty()) Box(
                Modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(8.dp))
                    .clickable(role = Role.Button) { dash.callsFocusKey.value = key; dash.navigate(ViewId.Calls) }
                    .padding(horizontal = 8.dp),
                contentAlignment = Alignment.Center,
            ) { Text("All calls", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = if (c.isDark) Palette.Emerald300 else Palette.Emerald700) }
        }
        CallPermissionBlock(
            permission, request, first = firstNameOf(vm.displayNameForCalls()) ?: "them",
            onSend = vm::sendCallRequest, onCallNow = { vm.call(key) },
            onSettings = { dash.navigate(ViewId.Settings) },
        )
        if (list.isEmpty()) {
            Text("No calls with this customer yet.", fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(vertical = 6.dp))
        }
        list.forEach { CallLine(it) }
    }
}

/**
 * Where this customer's call permission stands (CALLING_UX.md §2.1) — said
 * honestly: allowed permanently / until a date, a request waiting, declined,
 * revoked after unanswered calls, when a new request can go, calls left
 * today — and "Send call request" when calling them needs one.
 */
@Composable
internal fun CallPermissionBlock(
    p: CallPermission?,
    request: CustomerViewModel.CallRequestUi,
    first: String,
    onSend: () -> Unit,
    onCallNow: () -> Unit,
    onSettings: () -> Unit,
) {
    val c = Neema.colors
    val lines = p?.let { permissionLines(it, first, AppClock.now()) }.orEmpty()
    val needsRequest = p != null && p.canCall == false && p.status != "requested" && !request.sent && !request.alreadyAllowed &&
        !request.templateRequired
    if (lines.isEmpty() && !needsRequest && !request.sent && !request.alreadyAllowed && request.error == null) return
    val link = if (c.isDark) Palette.Emerald300 else Palette.Emerald700
    Column(Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 4.dp, end = 8.dp)) {
        lines.forEach { Text(it, fontSize = 12.sp, color = c.textMid, lineHeight = 17.sp) }
        when {
            request.alreadyAllowed -> {
                Text("$first already allowed calls", fontSize = 12.sp, color = link, lineHeight = 17.sp)
                SmallPill("Call now", filled = true, onClick = onCallNow)
            }
            request.sent -> Text("Call request sent — you'll be told when $first taps Allow", fontSize = 12.sp, color = link, lineHeight = 17.sp)
            needsRequest -> {
                val blocked = p?.canRequest == false
                SmallPill(if (request.busy) "Sending…" else "Send call request", filled = true, enabled = !blocked && !request.busy, onClick = onSend)
            }
        }
        request.error?.let {
            Text(it, fontSize = 12.sp, color = if (c.isDark) Palette.Red300 else Palette.Red700, lineHeight = 17.sp, modifier = Modifier.padding(top = 4.dp))
            if (request.adminCanFix) SmallPill("Open WhatsApp calling settings", filled = false, onClick = onSettings)
        }
    }
}

@Composable
private fun SmallPill(text: String, filled: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    val c = Neema.colors
    Box(
        Modifier.padding(top = 4.dp).heightIn(min = 48.dp).clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.CenterStart,
    ) {
        Row(
            Modifier.alpha(if (enabled) 1f else 0.5f).clip(RoundedCornerShape(50))
                .then(if (filled) Modifier.background(Palette.Call.WaDeep) else Modifier.border(1.dp, c.border, RoundedCornerShape(50)))
                .padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (filled) {
                Icon(CallIcons.Phone, null, tint = Color.White, modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(6.dp))
            }
            Text(text, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = if (filled) Color.White else c.text)
        }
    }
}

@Composable
private fun CallLine(call: Call) {
    val c = Neema.colors
    val w = callRowWords(call)
    val tone = when (w.tone) {
        CallTone.Live, CallTone.Good -> if (c.isDark) Palette.Emerald300 else Palette.Emerald700
        CallTone.Bad -> if (c.isDark) Palette.Red300 else Palette.Red700
        CallTone.Warn -> if (c.isDark) Palette.Amber300 else Palette.Amber700
        CallTone.Neutral -> c.textMid
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(w.icon, null, tint = tone, modifier = Modifier.size(14.dp))
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Text(
                listOfNotNull(w.label, callDuration(call.duration).ifEmpty { null }, agentFirst(call.agentName)).joinToString(" · "),
                fontSize = 12.sp, color = tone, fontWeight = FontWeight.Medium, maxLines = 1,
            )
            call.summary?.takeIf { it.isNotBlank() }?.let { Text(it, fontSize = 11.sp, color = c.textMid, maxLines = 2) }
            if (call.hasVoicemail) Text("Voicemail — open the chat to listen", fontSize = 11.sp, color = c.textMid, maxLines = 1)
        }
        if (call.followUpOpen) {
            Text(
                "Follow up", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = if (c.isDark) Palette.Amber300 else Palette.Amber700,
                modifier = Modifier.padding(horizontal = 6.dp),
            )
        }
        Text(liveAgo(call.startedAt), fontSize = 11.sp, color = c.muted, maxLines = 1)
    }
}

/** A conversation on a platform that has no business calling API. */
enum class CallPlatform(val title: String, val colors: List<Color>) {
    Messenger("Messenger", ChannelColors.MessengerGradient),
    Instagram("Instagram", ChannelColors.InstagramGradient),
}

/** Messenger and Instagram cannot be called (never promise it); every other channel is WhatsApp's or has no call. */
fun callPlatformOf(channel: String?): CallPlatform? = when (channel) {
    "messenger" -> CallPlatform.Messenger
    "instagram" -> CallPlatform.Instagram
    else -> null
}

/**
 * The Call button on a Messenger / Instagram conversation: the platform says
 * plainly that it doesn't let businesses take calls, and offers a WhatsApp
 * call instead — to the number on file, or the question that asks for it.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CallOnWhatsAppSheet(
    platform: CallPlatform,
    first: String?,
    phone: String?,
    onCall: () -> Unit,
    onAsk: () -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        CallOnWhatsAppContent(platform, first, phone, onCall = { onDismiss(); onCall() }, onAsk = { onDismiss(); onAsk() }, onDismiss = onDismiss)
    }
}

/** The sheet's body (its own composable so it can be looked at without the sheet around it). */
@Composable
fun CallOnWhatsAppContent(
    platform: CallPlatform,
    first: String?,
    phone: String?,
    onCall: () -> Unit,
    onAsk: () -> Unit,
    onDismiss: () -> Unit,
) {
    val c = Neema.colors
    val who = first ?: "them"
    Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 20.dp, vertical = 8.dp)) {
        // The platform's own look: its gradient, its name.
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
                .background(Brush.linearGradient(platform.colors)).padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(36.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.22f)), contentAlignment = Alignment.Center) {
                Icon(CallIcons.PhoneDown, null, tint = Color.White, modifier = Modifier.size(18.dp))
            }
            Spacer(Modifier.width(12.dp))
            Text(
                "${platform.title} doesn't let businesses take calls.", color = Color.White, fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold, lineHeight = 20.sp, modifier = Modifier.semantics { heading() },
            )
        }
        Spacer(Modifier.height(14.dp))
        Text(
            if (phone != null) "Call $who on WhatsApp instead." else "Call $who on WhatsApp instead — ask for their WhatsApp number first.",
            fontSize = 14.sp, color = c.text, lineHeight = 20.sp,
        )
        Spacer(Modifier.height(16.dp))
        if (phone != null) {
            SheetButton("Call on WhatsApp", filled = true, onClick = onCall)
        } else {
            SheetButton("Ask for their WhatsApp number", filled = true, onClick = onAsk)
            Text(
                "Puts the question in your reply box — nothing is sent until you send it.",
                fontSize = 12.sp, color = c.muted, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
        SheetButton("Not now", filled = false, onClick = onDismiss)
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun SheetButton(text: String, filled: Boolean, onClick: () -> Unit) {
    val c = Neema.colors
    Box(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(RoundedCornerShape(50))
            // White on WhatsApp's deep green (#008069, as the web's sheet): 4.9:1, not white on #25D366.
            .then(if (filled) Modifier.background(Palette.Call.WaDeep) else Modifier.border(1.dp, c.border, RoundedCornerShape(50)))
            .clickable(role = Role.Button, onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
            if (filled) {
                Icon(CallIcons.Phone, null, tint = Color.White, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(8.dp))
            }
            Text(text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (filled) Color.White else c.text)
        }
    }
}
