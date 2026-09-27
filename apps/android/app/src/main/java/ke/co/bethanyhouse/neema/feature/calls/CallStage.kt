package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.TabularNums

// docs/CALLING_UX.md §5: every call screen is a WhatsApp call, drawn in
// WhatsApp's own dark call colours (core Palette.Call.Wa*).
private val Top = Palette.Call.WaTop
private val Bottom = Palette.Call.WaBottom
private val Ink = Palette.Call.WaText
private val Sub = Palette.Call.WaSub
private val Green = ChannelColors.WhatsApp
/** Filled call actions (Answer, the wrap-up's main action, Call now): white on WhatsApp's deep green, as the web. */
private val Teal = Palette.Call.WaTeal
/** Buttons with words on them (white text needs the darker green for contrast). */
private val TealText = Palette.Call.WaTealText
private val Red = Palette.Call.WaRed
private val Amber = Palette.Call.WaAmber
private val Control = Palette.Call.WaControl
private val Bar = Palette.Call.WaBar

private val CssEaseOut = CubicBezierEasing(0f, 0f, 0.58f, 1f)

/**
 * The call over the content area. Renders nothing when idle, and only the
 * [CallBar] (composed by the shell above the content) while minimised.
 * Always composed while signed in, so it also hosts the microphone prompt a
 * call raises ([CallManager.micRequest]) and lets a ringing / live call show
 * over the lock screen.
 */
@Composable
fun CallStage(dash: DashboardViewModel) {
    val calls = dash.container.calls
    val c by calls.state.collectAsStateWithLifecycle()
    val micRequest by calls.micRequest.collectAsStateWithLifecycle()
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        calls.onMicResult(granted)
    }
    // getUserMedia's prompt: a call is waiting for the microphone.
    LaunchedEffect(micRequest) {
        if (micRequest) runCatching { askMic.launch(Manifest.permission.RECORD_AUDIO) }.onFailure { calls.onMicResult(false) }
    }
    ShowOverLockScreen(c.live)

    if (c.phase == CallPhase.Idle || c.minimised) return
    CallCard(c, rememberCallActions(dash))
}

/**
 * What sits between the app's top bar and the view while a call is minimised
 * (§6), a second caller waits, or a customer just allowed calls: the rest of
 * Neema stays usable under it. Nothing when none of these holds.
 */
@Composable
fun CallBar(dash: DashboardViewModel, modifier: Modifier = Modifier) {
    val calls = dash.container.calls
    val c by calls.state.collectAsStateWithLifecycle()
    val grant by calls.permissionGranted.collectAsStateWithLifecycle()
    val actions = rememberCallActions(dash)
    val bar = c.minimised && c.phase != CallPhase.Idle
    if (!bar && grant == null) return
    Column(modifier.fillMaxWidth().background(Bottom)) {
        grant?.let { PermissionGrantBanner(it, onCall = calls::callGranted, onDismiss = calls::dismissGrant) }
        if (bar) {
            MinimisedCallBar(c, actions)
            c.waiting?.let { WaitingBanner(it, actions) }
        }
    }
}

/** Whether [CallBar] takes room at the top of the content (the shell pads for the status bar then). */
@Composable
fun callBarShown(dash: DashboardViewModel): Boolean {
    val c by dash.container.calls.state.collectAsStateWithLifecycle()
    val grant by dash.container.calls.permissionGranted.collectAsStateWithLifecycle()
    return (c.minimised && c.phase != CallPhase.Idle) || grant != null
}

@Composable
private fun rememberCallActions(dash: DashboardViewModel): CallActions {
    val calls = dash.container.calls
    val ctx = LocalContext.current
    return remember(calls, dash) {
        CallActions(
            answer = calls::answer, decline = calls::hangup, callback = calls::callback,
            toggleMute = calls::toggleMute, toggleSpeaker = calls::toggleSpeaker, hangup = calls::hangup,
            selectRoute = calls::selectRoute,
            openChat = { calls.openChat()?.let(dash::openConversationFor) },
            minimise = calls::minimise, expand = calls::expand, redial = calls::redial, dismiss = calls::dismiss,
            sendCallRequest = calls::sendCallRequest,
            callNow = calls::callNow,
            openCallingSettings = { calls.dismiss(); dash.navigate(ke.co.bethanyhouse.neema.app.ViewId.Settings) },
            openSettings = {
                runCatching {
                    ctx.startActivity(
                        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${ctx.packageName}"))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                }
                calls.dismiss()
            },
            declineWaiting = calls::declineWaiting, callbackWaiting = calls::callbackWaiting, endAndAnswer = calls::endAndAnswer,
        )
    }
}

/** While a call rings or runs, the activity shows over the keyguard and wakes the screen. */
@Composable
private fun ShowOverLockScreen(active: Boolean) {
    val ctx = LocalContext.current
    DisposableEffect(active) {
        val activity = ctx.findActivity()
        if (active && activity != null && Build.VERSION.SDK_INT >= 27) {
            activity.setShowWhenLocked(true)
            activity.setTurnScreenOn(true)
        }
        onDispose {
            if (active && activity != null && Build.VERSION.SDK_INT >= 27) {
                activity.setShowWhenLocked(false)
                activity.setTurnScreenOn(false)
            }
        }
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

/** Animator duration scale 0 ("Remove animations"): no ring pulse. */
@Composable
internal fun rememberReducedMotion(): Boolean {
    val ctx = LocalContext.current
    return remember(ctx) {
        runCatching { Settings.Global.getFloat(ctx.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }
            .getOrDefault(false)
    }
}

/** What the call screen's buttons do (every one a no-op by default, for previews and tests). */
class CallActions(
    val answer: () -> Unit = {},
    val decline: () -> Unit = {},
    val callback: () -> Unit = {},
    val toggleMute: () -> Unit = {},
    val toggleSpeaker: () -> Unit = {},
    val hangup: () -> Unit = {},
    val selectRoute: (AudioRoute) -> Unit = {},
    val openChat: () -> Unit = {},
    val minimise: () -> Unit = {},
    val expand: () -> Unit = {},
    val redial: () -> Unit = {},
    val dismiss: () -> Unit = {},
    val sendCallRequest: () -> Unit = {},
    val openSettings: () -> Unit = {},
    val callNow: () -> Unit = {},
    /** Settings → WhatsApp calling (admins, after a template_required refusal). */
    val openCallingSettings: () -> Unit = {},
    val declineWaiting: () -> Unit = {},
    val callbackWaiting: () -> Unit = {},
    val endAndAnswer: () -> Unit = {},
)

/**
 * The call screen for any [CallUiState] (idle included — callers skip it):
 * WhatsApp's dark surface, the caller large and centred, the phase's own
 * words, and the controls in a rounded bar at the bottom — Decline left,
 * Answer (the largest) right, as in WhatsApp. After the call, the wrap-up.
 */
@Composable
fun CallCard(c: CallUiState, actions: CallActions) {
    BoxWithConstraints(
        Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(Top, Bottom)))
            // The card owns the content area: swallow taps meant for the screen below
            // (a gesture, not a click: it must not merge the card into one accessibility node).
            .pointerInput(Unit) { detectTapGestures { } }
            .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal)),
        contentAlignment = Alignment.TopCenter,
    ) {
        val fontScale = LocalDensity.current.fontScale
        // A short screen (a small phone, big text, landscape): a smaller avatar
        // and tighter spacing, so the whole card — above all its controls — fits.
        val short = maxHeight < 640.dp || maxHeight / fontScale < 560.dp
        // A phone on its side: who on the left, the controls on the right.
        val sideBySide = maxWidth > maxHeight && maxHeight < 520.dp
        val narrow = maxWidth / fontScale < 400.dp
        val pad = if (narrow) 16.dp else 24.dp
        Column(Modifier.fillMaxSize().widthIn(max = if (sideBySide) 900.dp else 520.dp).padding(horizontal = pad)) {
            TopRow(c, actions)
            c.waiting?.let { WaitingBanner(it, actions, Modifier.padding(bottom = 8.dp)) }
            if (sideBySide) {
                Row(Modifier.weight(1f).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(
                        Modifier.weight(1f).verticalScroll(rememberScrollState()),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) { Who(c, short = true) }
                    Spacer(Modifier.width(16.dp))
                    Column(
                        Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(vertical = 8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) { Controls(c, actions, compact = true) }
                }
            } else {
                // Who / status scroll if they must; the controls below are always on screen.
                Column(
                    Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Spacer(Modifier.height(if (short) 8.dp else 32.dp))
                    Who(c, short)
                    Spacer(Modifier.height(if (short) 8.dp else 24.dp))
                }
                Column(
                    Modifier.fillMaxWidth().padding(bottom = if (short) 12.dp else 28.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) { Controls(c, actions, compact = short) }
            }
        }
    }
}

/** Minimise (the call keeps running in the bar at the top of the app). */
@Composable
private fun TopRow(c: CallUiState, actions: CallActions) {
    Row(Modifier.fillMaxWidth().heightIn(min = 48.dp), verticalAlignment = Alignment.CenterVertically) {
        // On a call, Minimise sits in the control bar; before that, up here.
        if (c.live && c.phase != CallPhase.Ringing && c.phase != CallPhase.InCall) {
            IconCell(CallIcons.Minimise, "Minimise call", onClick = actions.minimise)
        }
    }
}

@Composable
private fun IconCell(icon: ImageVector, label: String, tint: Color = Ink, onClick: () -> Unit) {
    Box(
        Modifier.size(48.dp).clip(CircleShape).clickable(role = Role.Button, onClickLabel = label, onClick = onClick)
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) { Icon(icon, null, tint = tint, modifier = Modifier.size(24.dp)) }
}

/** Avatar (with the ring pulse while it rings), name, number, "WhatsApp voice call", the status line. */
@Composable
private fun ColumnScope.Who(c: CallUiState, short: Boolean) {
    val who = c.who
    val avatar = if (short) 88.dp else 120.dp
    val ringing = c.phase == CallPhase.Ringing || c.phase == CallPhase.Placing || c.phase == CallPhase.RingingOut
    val reduced = rememberReducedMotion()
    Box(Modifier.size(avatar), contentAlignment = Alignment.Center) {
        if (ringing && !reduced) {
            PulseRing(maxScale = 1.6f, startAlpha = 0.35f, size = avatar)
            PulseRing(maxScale = 2f, startAlpha = 0.2f, size = avatar)
        }
        Box(
            Modifier.size(avatar).clip(CircleShape).background(Palette.Call.Avatars[avatarIndex(who)]),
            contentAlignment = Alignment.Center,
        ) {
            // The initials are a picture inside a fixed circle: they don't grow with the font scale.
            val size = with(LocalDensity.current) { (if (short) 32.dp else 42.dp).toSp() }
            Text(initialsOf(who).ifEmpty { "?" }, color = Color.White, fontSize = size, fontWeight = FontWeight.SemiBold, maxLines = 1)
        }
    }
    Spacer(Modifier.height(if (short) 12.dp else 20.dp))
    Text(
        who, color = Ink, fontSize = 26.sp, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis,
        textAlign = TextAlign.Center, lineHeight = 32.sp,
    )
    if (!c.name.isNullOrBlank() && !c.from.isNullOrEmpty()) {
        Spacer(Modifier.height(4.dp))
        Text("+${c.from}", color = Sub, fontSize = 14.sp, style = TabularNums, maxLines = 1)
    }
    Spacer(Modifier.height(6.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(CallIcons.Phone, null, tint = Green, modifier = Modifier.size(14.dp))
        Spacer(Modifier.width(6.dp))
        Text("WhatsApp voice call", color = Sub, fontSize = 14.sp, maxLines = 1)
    }
    Spacer(Modifier.height(if (short) 10.dp else 16.dp))
    StatusLine(c)
}

/** The phase's own words, announced when they change (a live region). */
@Composable
private fun StatusLine(c: CallUiState) {
    val text = c.statusText()
    val live = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
    when {
        c.reconnecting && c.live -> Row(
            live.clip(RoundedCornerShape(50)).background(Amber.copy(alpha = 0.14f)).padding(horizontal = 14.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(CallIcons.NoSignal, null, tint = Amber, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(8.dp))
            Text(text, color = Amber, fontSize = 15.sp, fontWeight = FontWeight.Medium)
        }
        c.phase == CallPhase.InCall -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(text, color = Ink, fontSize = 18.sp, style = TabularNums, modifier = live.semantics { contentDescription = "On call, ${spokenLength(c.seconds)}" })
            // Only while a recording really runs: this phone's, or WhatsApp's own (the customer heard it announced).
            if (c.recording || c.metaTranscription) {
                Spacer(Modifier.height(8.dp))
                Row(
                    Modifier.clip(RoundedCornerShape(50)).background(Red.copy(alpha = 0.16f)).padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(Modifier.size(8.dp).clip(CircleShape).background(Red))
                    Spacer(Modifier.width(6.dp))
                    Text(if (c.recording) "Recording" else "Recorded by WhatsApp", color = Ink, fontSize = 13.sp)
                }
            }
        }
        c.phase == CallPhase.Connecting -> Row(live, verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(14.dp), color = Teal, strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp))
            Text(text, color = Sub, fontSize = 15.sp)
        }
        // Every outcome is an icon AND words (never colour alone, §5).
        c.phase == CallPhase.Ended -> Row(live, verticalAlignment = Alignment.CenterVertically) {
            val owed = c.outcome.let {
                it is CallOutcome.Missed || it == CallOutcome.NoAnswer || it == CallOutcome.Rejected || it == CallOutcome.ConnectionLost ||
                    it is CallOutcome.Failed || it == CallOutcome.MicBlocked || it == CallOutcome.PermissionNeeded
            }
            val tint = if (owed) OwedInk else Ink
            Icon(outcomeIcon(c.outcome), null, tint = tint, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(text, color = tint, fontSize = 16.sp, fontWeight = FontWeight.Medium, textAlign = TextAlign.Center)
        }
        else -> Text(text, color = Sub, fontSize = 15.sp, textAlign = TextAlign.Center, modifier = live)
    }
    // Before the call goes through: they left our last calls unanswered (a caution, never a block).
    c.callCaution()?.let {
        Spacer(Modifier.height(12.dp))
        Row(
            Modifier.widthIn(max = 360.dp).clip(RoundedCornerShape(12.dp)).background(Amber.copy(alpha = 0.14f))
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(CallIcons.Alert, null, tint = Amber, modifier = Modifier.size(16.dp).padding(top = 1.dp))
            Spacer(Modifier.width(8.dp))
            Text(it, color = Ink, fontSize = 13.sp, lineHeight = 18.sp)
        }
    }
    c.outcomeNote()?.let {
        Spacer(Modifier.height(8.dp))
        Text(it, color = Sub, fontSize = 13.sp, textAlign = TextAlign.Center, lineHeight = 18.sp, modifier = Modifier.widthIn(max = 340.dp))
    }
    c.recordingNote?.takeIf { c.phase == CallPhase.Ended }?.let {
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(Sub))
            Spacer(Modifier.width(6.dp))
            Text(it, color = Sub, fontSize = 13.sp, textAlign = TextAlign.Center)
        }
    }
    c.error?.let {
        Spacer(Modifier.height(10.dp))
        Text(it, color = Palette.Red300, fontSize = 14.sp, textAlign = TextAlign.Center, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
    }
}

/** The wrap-up's outcome glyph (CallStage.tsx OUTCOME_ICON). */
internal fun outcomeIcon(o: CallOutcome?): ImageVector = when (o) {
    is CallOutcome.AnsweredElsewhere, CallOutcome.PermissionRequested, CallOutcome.AlreadyAllowed -> CallIcons.Check
    is CallOutcome.Missed -> CallIcons.DirIn
    is CallOutcome.Callback -> CallIcons.Callback
    CallOutcome.ConnectionLost -> CallIcons.NoSignal
    CallOutcome.NoAnswer, CallOutcome.Rejected, is CallOutcome.Failed, CallOutcome.PermissionNeeded, CallOutcome.MicBlocked -> CallIcons.Alert
    else -> CallIcons.PhoneDown
}

/** The outcome words when the agent still owes the customer something (the web's #FFD1D9). */
private val OwedInk = Color(0xFFFFD1D9)

private fun spokenLength(s: Int): String {
    val m = s / 60
    val sec = s % 60
    return if (m > 0) "$m minute${if (m == 1) "" else "s"} $sec second${if (sec == 1) "" else "s"}" else "$sec second${if (sec == 1) "" else "s"}"
}

/** The controls for the phase (the §3 table's last column). */
@Composable
private fun Controls(c: CallUiState, actions: CallActions, compact: Boolean) {
    when (c.phase) {
        CallPhase.Ringing -> {
            // Disabled (dimmed) while a callback is being saved: no second request.
            val on = !c.busy
            Row(
                Modifier.fillMaxWidth().widthIn(max = 360.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.Bottom,
            ) {
                RoundButton("Decline", "Decline call", CallIcons.PhoneDown, Red, size = 64.dp, enabled = on, onClick = actions.decline)
                RoundButton("Answer", "Answer call", CallIcons.PhoneFill, Teal, size = 76.dp, enabled = on, onClick = actions.answer)
            }
            Spacer(Modifier.height(if (compact) 4.dp else 12.dp))
            TextAction(if (c.busy) "Saving…" else "Call back later", CallIcons.Callback, enabled = on, onClick = actions.callback)
        }
        CallPhase.Placing, CallPhase.RingingOut, CallPhase.Connecting, CallPhase.InCall -> ControlBar {
            MuteButton(c, actions, Modifier.weight(1f))
            if (c.phase == CallPhase.Connecting || c.phase == CallPhase.InCall) AudioButton(c, actions, Modifier.weight(1f))
            if (c.phase == CallPhase.InCall && c.chatKey != null) {
                RoundButton("Chat", "Open chat", CallIcons.Chat, Control, onClick = actions.openChat, modifier = Modifier.weight(1f))
            }
            if (c.phase == CallPhase.InCall) {
                RoundButton("Minimise", "Minimise call", CallIcons.Minimise, Control, onClick = actions.minimise, modifier = Modifier.weight(1f))
            }
            RoundButton("End", "End call", CallIcons.PhoneDown, Red, onClick = actions.hangup, modifier = Modifier.weight(1f))
        }
        CallPhase.Ended -> WrapUp(c, actions)
        CallPhase.Idle -> Unit
    }
}

@Composable
private fun ControlBar(content: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit) {
    Row(
        Modifier.fillMaxWidth().widthIn(max = 460.dp).clip(RoundedCornerShape(32.dp)).background(Bar)
            .padding(horizontal = 4.dp, vertical = 12.dp),
        verticalAlignment = Alignment.Top,
        content = content,
    )
}

@Composable
private fun MuteButton(c: CallUiState, actions: CallActions, modifier: Modifier) {
    RoundButton(
        if (c.muted) "Unmute" else "Mute", if (c.muted) "Unmute" else "Mute",
        if (c.muted) CallIcons.MicOff else CallIcons.Mic,
        if (c.muted) Ink else Control, iconTint = if (c.muted) Bottom else Ink,
        state = if (c.muted) "Microphone off" else null,
        onClick = actions.toggleMute, modifier = modifier,
    )
}

/**
 * Earpiece ↔ speaker when that is all there is; with a headset or Bluetooth,
 * the current route and a list to choose from (as a phone's call screen).
 */
@Composable
private fun AudioButton(c: CallUiState, actions: CallActions, modifier: Modifier) {
    if (!c.routeChoice) {
        val on = c.speaker
        RoundButton(
            "Speaker", if (on) "Speaker on" else "Speaker", CallIcons.Speaker,
            if (on) Ink else Control, iconTint = if (on) Bottom else Ink,
            enabled = c.routes.size > 1, state = if (on) "On" else "Off",
            onClick = actions.toggleSpeaker, modifier = modifier,
        )
        return
    }
    var open by remember { mutableStateOf(false) }
    Box(modifier, contentAlignment = Alignment.TopCenter) {
        RoundButton(
            c.route.label, "Audio: ${c.route.label} — choose where the call plays", routeIcon(c.route.kind),
            Ink, iconTint = Bottom, onClick = { open = true },
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            c.routes.forEach { r ->
                DropdownMenuItem(
                    text = { Text(r.label) },
                    leadingIcon = { Icon(routeIcon(r.kind), null, modifier = Modifier.size(20.dp)) },
                    trailingIcon = { if (r == c.route) Icon(CallIcons.Check, "Selected", modifier = Modifier.size(18.dp)) },
                    onClick = { open = false; actions.selectRoute(r) },
                )
            }
        }
    }
}

internal fun routeIcon(k: AudioRouteKind): ImageVector = when (k) {
    AudioRouteKind.Earpiece -> CallIcons.Earpiece
    AudioRouteKind.Speaker -> CallIcons.Speaker
    AudioRouteKind.Wired -> CallIcons.Headset
    AudioRouteKind.Bluetooth -> CallIcons.Bluetooth
}

/** The wrap-up's actions: the one the agent most likely wants, filled; the rest outlined; Done last. */
@Composable
private fun WrapUp(c: CallUiState, actions: CallActions) {
    val list = c.wrapActions()
    Column(Modifier.fillMaxWidth().widthIn(max = 360.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        list.forEachIndexed { i, a ->
            val run = actions.run(a)
            val label = if (a == WrapAction.SendCallRequest && c.busy) "Sending…" else a.label
            val closer = a == WrapAction.Done || a == WrapAction.Cancel
            // Meta's request limit is used up: the button stays, dimmed; the line above says when it can go.
            val blocked = a == WrapAction.SendCallRequest && c.sendRequestBlocked() != null
            when {
                closer -> PillButton(label, filled = false, outlined = false, onClick = run)
                i == 0 -> PillButton(label, filled = true, enabled = !c.busy && !blocked, onClick = run)
                else -> PillButton(label, filled = false, enabled = !c.busy && !blocked, onClick = run)
            }
        }
    }
}

@Composable
private fun PillButton(text: String, filled: Boolean, outlined: Boolean = true, enabled: Boolean = true, onClick: () -> Unit) {
    val shape = RoundedCornerShape(50)
    Box(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).alpha(if (enabled) 1f else 0.5f).clip(shape)
            .then(if (filled) Modifier.background(TealText) else Modifier)
            .then(if (!filled && outlined) Modifier.border(1.dp, Sub.copy(alpha = 0.5f), shape) else Modifier)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text, color = if (filled) Color.White else Ink, fontSize = 15.sp,
            fontWeight = if (filled) FontWeight.SemiBold else FontWeight.Medium, textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun TextAction(text: String, icon: ImageVector, enabled: Boolean = true, onClick: () -> Unit) {
    Row(
        Modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(50)).alpha(if (enabled) 1f else 0.5f)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = Ink, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(text, color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    }
}

/** The expanding green rings behind a ringing avatar (the only motion besides the connecting spinner). */
@Composable
private fun PulseRing(maxScale: Float, startAlpha: Float, size: Dp) {
    val t = rememberInfiniteTransition(label = "ring")
    val p by t.animateFloat(
        0f, 1f,
        infiniteRepeatable(tween(1700, easing = CssEaseOut), RepeatMode.Restart),
        label = "ringP",
    )
    Box(
        Modifier.size(size)
            .graphicsLayer {
                val s = 1f + (maxScale - 1f) * p
                scaleX = s; scaleY = s
                alpha = startAlpha * (1f - p)
            }
            .clip(CircleShape)
            .background(Green),
    )
}

/**
 * A round call control with its label under it: 56dp at least (64 for
 * Decline, 76 for Answer), the whole column one touch target.
 */
@Composable
private fun RoundButton(
    label: String,
    description: String,
    icon: ImageVector,
    color: Color,
    iconTint: Color = Color.White,
    size: Dp = 56.dp,
    enabled: Boolean = true,
    state: String? = null,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Column(
        modifier
            .alpha(if (enabled) 1f else 0.45f)
            .clickable(interactionSource = interaction, indication = null, enabled = enabled, onClick = onClick)
            .semantics {
                contentDescription = description
                role = Role.Button
                if (state != null) stateDescription = state
            },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier.scale(if (pressed) 0.95f else 1f).size(size).clip(CircleShape).background(color),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, null, tint = iconTint, modifier = Modifier.size(if (size > 60.dp) 30.dp else 24.dp))
        }
        Spacer(Modifier.height(8.dp))
        // The label grows with the font scale only so far: five controls share a
        // 320dp row, and a word must never break in half. TalkBack reads the full
        // description whatever the size.
        val d = LocalDensity.current
        val labelSize = with(d) { (12.dp * minOf(d.fontScale, 1.15f)).toSp() }
        Text(label, color = Ink, fontSize = labelSize, textAlign = TextAlign.Center, maxLines = 1, softWrap = false, overflow = TextOverflow.Ellipsis)
    }
}

/**
 * The minimised call (§6): a slim bar at the top of the content — live dot
 * (amber, with its icon, while reconnecting), who, the status or timer, Mute
 * and End. A tap anywhere else brings the call screen back.
 */
@Composable
fun MinimisedCallBar(c: CallUiState, actions: CallActions) {
    val ended = c.phase == CallPhase.Ended
    val inCall = c.phase == CallPhase.InCall
    Row(
        Modifier.fillMaxWidth().background(Bar)
            .clickable(onClickLabel = "Show the call", role = Role.Button, onClick = actions.expand)
            .heightIn(min = 56.dp).padding(start = 16.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (c.reconnecting) Icon(CallIcons.NoSignal, null, tint = Amber, modifier = Modifier.size(14.dp))
        else Box(Modifier.size(10.dp).clip(CircleShape).background(if (ended) Sub else Green))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f).padding(vertical = 8.dp)) {
            Text(c.who, color = Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val timer = inCall && !c.reconnecting
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    c.statusText(), color = if (c.reconnecting) Amber else Sub, fontSize = 13.sp, style = TabularNums,
                    // The clock never breaks across lines; words may take two.
                    maxLines = if (timer) 1 else 2, softWrap = !timer, overflow = TextOverflow.Ellipsis,
                    modifier = (if (timer) Modifier else Modifier.weight(1f, fill = false)).semantics { liveRegion = LiveRegionMode.Polite },
                )
                if (timer && c.recording) {
                    Spacer(Modifier.width(8.dp))
                    Box(Modifier.size(8.dp).clip(CircleShape).background(RecInk).semantics { contentDescription = "Recording" })
                    // At large text sizes the dot alone: the timer and the controls keep their room.
                    if (LocalDensity.current.fontScale <= 1.3f) {
                        Spacer(Modifier.width(4.dp))
                        Text("Rec", color = RecInk, fontSize = 13.sp, maxLines = 1, softWrap = false)
                    }
                }
            }
        }
        if (ended) {
            // A wrap-up that arrived while minimised: its main action, and Done.
            val primary = c.wrapActions().firstOrNull()?.takeIf { it != WrapAction.Done && it != WrapAction.Cancel }
            if (primary != null) {
                Box(
                    Modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(50))
                        .clickable(enabled = !c.busy, role = Role.Button, onClick = actions.run(primary)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        primary.label, color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
                        modifier = Modifier.clip(RoundedCornerShape(50)).background(TealText).padding(horizontal = 12.dp, vertical = 8.dp),
                    )
                }
            }
            Box(
                Modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(50))
                    .clickable(role = Role.Button, onClick = actions.dismiss).padding(horizontal = 12.dp),
                contentAlignment = Alignment.Center,
            ) { Text("Done", color = Ink, fontSize = 13.sp, fontWeight = FontWeight.Medium) }
        } else {
            // Chat: the customer's conversation, the call stays up here (the web's bar has it too).
            if (inCall && c.chatKey != null) IconCell(CallIcons.Chat, "Open chat with ${c.who} — the call keeps going", onClick = actions.openChat)
            IconCell(if (c.muted) CallIcons.MicOff else CallIcons.Mic, if (c.muted) "Unmute" else "Mute", onClick = actions.toggleMute)
            Box(
                Modifier.size(48.dp).clip(CircleShape)
                    .clickable(role = Role.Button, onClickLabel = "End call", onClick = actions.hangup)
                    .semantics { contentDescription = "End call" },
                contentAlignment = Alignment.Center,
            ) {
                Box(Modifier.size(38.dp).clip(CircleShape).background(Red), contentAlignment = Alignment.Center) {
                    Icon(CallIcons.PhoneDown, null, tint = Color.White, modifier = Modifier.size(20.dp))
                }
            }
        }
    }
}

/** "● Rec" on the minimised bar (CallStage.tsx #FF6B81). */
private val RecInk = Color(0xFFFF6B81)

/** What a wrap-up action does. */
internal fun CallActions.run(a: WrapAction): () -> Unit = when (a) {
    WrapAction.OpenChat, WrapAction.Message -> openChat
    WrapAction.CallAgain, WrapAction.CallBack, WrapAction.TryAgain -> redial
    WrapAction.SendCallRequest -> sendCallRequest
    WrapAction.OpenSettings -> openSettings
    WrapAction.CallNow -> callNow
    WrapAction.CallingSettings -> openCallingSettings
    WrapAction.Done, WrapAction.Cancel -> dismiss
}

/**
 * A second caller while this phone is on a call: a banner, never a take-over.
 * The API has no hold — taking them means ending this call ("End & answer").
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun WaitingBanner(w: WaitingCall, actions: CallActions, modifier: Modifier = Modifier) {
    Column(
        modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Bar)
            .border(1.dp, Green.copy(alpha = 0.35f), RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 10.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(CallIcons.Phone, null, tint = Green, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(8.dp))
            Text("${w.who} is also calling", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.height(8.dp))
        // As the web's banner: three filled pills — Decline red, Call back later quiet, End & answer green.
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SmallAction("Decline", Red, Color.White, "Decline ${w.who}'s call", actions.declineWaiting)
            SmallAction("Call back later", Control, Ink, null, actions.callbackWaiting)
            SmallAction("End & answer", TealText, Color.White, null, actions.endAndAnswer)
        }
    }
}

@Composable
private fun SmallAction(text: String, fill: Color, ink: Color, description: String?, onClick: () -> Unit) {
    Box(
        Modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(50)).background(fill)
            .clickable(role = Role.Button, onClick = onClick)
            .then(if (description != null) Modifier.semantics { contentDescription = description } else Modifier)
            .padding(horizontal = 16.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, color = ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, maxLines = 1) }
}

/** "{First} allowed calls — Call now": a customer this phone asked has tapped Allow. */
@Composable
fun PermissionGrantBanner(g: PermissionGrant, onCall: () -> Unit, onDismiss: () -> Unit) {
    val first = firstNameOf(g.name) ?: "+${g.waId}"
    Row(
        Modifier.fillMaxWidth().background(Palette.Call.WaTeal.copy(alpha = 0.18f)).heightIn(min = 56.dp)
            .padding(start = 16.dp, end = 4.dp).semantics { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(CallIcons.Phone, null, tint = Green, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(10.dp))
        Text("$first allowed calls", color = Ink, fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f), maxLines = 2)
        Box(
            Modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(50)).clickable(role = Role.Button, onClick = onCall),
            contentAlignment = Alignment.Center,
        ) {
            Row(
                Modifier.clip(RoundedCornerShape(50)).background(TealText).padding(horizontal = 14.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(CallIcons.Phone, null, tint = Color.White, modifier = Modifier.size(15.dp))
                Spacer(Modifier.width(6.dp))
                Text("Call now", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
            }
        }
        IconCell(CallIcons.Close, "Dismiss", onClick = onDismiss)
    }
}
