package ke.co.bethanyhouse.neema.feature.calls

import ke.co.bethanyhouse.neema.core.ui.theme.TabularNums
import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

// CallStage.tsx's inline palette (core Palette.Call).
private val WaGreen = ChannelColors.WhatsApp
private val CardText = Palette.Call.Text
private val SubText = Palette.Call.StageSubText
private val PillText = Palette.Call.StagePillText
private val PillBg = ChannelColors.WhatsApp.copy(alpha = 0.14f)
private val Red = Palette.Call.StageRed
private val Amber = Palette.Call.StageAmber
private val LabelGrey = Palette.Call.StageLabel

private val CssEaseOut = CubicBezierEasing(0f, 0f, 0.58f, 1f)
private val CssEaseInOut = CubicBezierEasing(0.42f, 0f, 0.58f, 1f)

private fun mmss(s: Int) = "%02d:%02d".format(s / 60, s % 60)

/**
 * The call card over the content area (components/CallStage.tsx). Renders
 * nothing when idle. Always composed while signed in, so it also hosts the
 * microphone prompt a call raises ([CallManager.micRequest]) and lets a
 * ringing / live call show over the lock screen.
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
    ShowOverLockScreen(c.phase != CallPhase.Idle)

    if (c.phase == CallPhase.Idle) return
    CallCard(
        c,
        CallActions(
            answer = calls::answer, decline = calls::hangup, callback = calls::callback,
            toggleMute = calls::toggleMute, toggleSpeaker = calls::toggleSpeaker, hangup = calls::hangup,
        ),
    )
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

/** What the card's buttons do. */
class CallActions(
    val answer: () -> Unit = {},
    val decline: () -> Unit = {},
    val callback: () -> Unit = {},
    val toggleMute: () -> Unit = {},
    val toggleSpeaker: () -> Unit = {},
    val hangup: () -> Unit = {},
)

/** The card itself, for any [CallUiState] (idle included — callers skip it). */
@Composable
fun CallCard(c: CallUiState, actions: CallActions) {
    val who = c.name?.takeIf { it.isNotBlank() } ?: c.from?.takeIf { it.isNotEmpty() }?.let { "+$it" } ?: "Unknown"
    // who.replace("+", "")[0] — JS replaces only the first "+".
    val initial = firstGlyph(who.replaceFirst("+", "")).ifEmpty { "?" }.uppercase()
    val ringing = c.phase == CallPhase.Ringing
    val live = c.phase == CallPhase.InCall

    BoxWithConstraints(
        Modifier
            .fillMaxSize()
            .drawBehind {
                // radial-gradient(130% 100% at 50% 0%, #0e5c3a 0%, #06110b 60%)
                drawTopEllipseGradient(1.3f, 1f, 0f to Palette.Call.StageGlow, 0.6f to Palette.Call.StageInk, 1f to Palette.Call.StageInk)
            }
            // The card owns the content area: swallow taps meant for the screen below.
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
        contentAlignment = Alignment.Center,
    ) {
        // A short screen (a small phone, big text, landscape): a smaller avatar
        // and tighter spacing, so the whole card — above all its buttons — fits.
        val short = maxHeight < 720.dp
        // Little room for text (a small phone or big text): slimmer margins.
        val narrow = maxWidth / LocalDensity.current.fontScale < 400.dp
        val avatar = if (short) 104.dp else 132.dp
        val initialSize = with(LocalDensity.current) { (if (short) 36.dp else 46.dp).toSp() }
        Column(
            Modifier
                .padding(if (narrow) 16.dp else 24.dp)
                .widthIn(max = 448.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(32.dp))
                .background(Palette.Call.StageGlass.copy(alpha = 0.6f))
                .border(1.dp, ChannelColors.WhatsApp.copy(alpha = 0.18f), RoundedCornerShape(32.dp))
                .padding(
                    start = if (narrow) 20.dp else 40.dp, end = if (narrow) 20.dp else 40.dp,
                    top = if (short) 32.dp else 56.dp, bottom = if (short) 24.dp else 40.dp,
                ),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
        // Who / status scroll if they must; the controls below are always on screen.
        Column(
            Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // Avatar with the ringing pulse and the live dot.
            Box(Modifier.size(avatar), contentAlignment = Alignment.Center) {
                if (ringing) {
                    PulseRing(maxScale = 2f, startAlpha = 0.45f, size = avatar)
                    PulseRing(maxScale = 2.6f, startAlpha = 0.3f, size = avatar)
                }
                Box(
                    Modifier.size(avatar).clip(CircleShape).background(WaGreen),
                    contentAlignment = Alignment.Center,
                ) {
                    // The initial fills the circle at any font scale (it is a picture, not text to read).
                    Text(initial, color = Palette.Call.StageInitial, fontSize = initialSize, fontWeight = FontWeight.SemiBold)
                }
                if (live) Box(
                    Modifier.align(Alignment.BottomEnd).padding(8.dp).size(26.dp).clip(CircleShape)
                        .background(Palette.Call.StageInk).padding(5.dp).clip(CircleShape)
                        .background(if (c.reconnecting) Amber else WaGreen),
                )
            }
            Spacer(Modifier.height(if (short) 16.dp else 24.dp))
            Text(
                who, color = CardText, fontSize = 26.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(horizontal = 8.dp),
            )
            if (!c.from.isNullOrEmpty()) {
                Spacer(Modifier.height(6.dp))
                // tracking-widest: 0.1em.
                Text("+${c.from}", color = SubText, fontSize = 14.sp, letterSpacing = 1.4.sp, style = TabularNums, maxLines = 1)
            }

            if (ringing) {
                Spacer(Modifier.height(20.dp))
                StatusPill("Incoming WhatsApp")
            }
            if (c.phase == CallPhase.Connecting) {
                Spacer(Modifier.height(24.dp))
                Text("Connecting…", color = Palette.Call.Soft, fontSize = 14.sp)
            }
            if (live) {
                Spacer(Modifier.height(if (short) 16.dp else 24.dp))
                // font-light tabular-nums, letter-spacing 0.12em.
                Text(
                    mmss(c.seconds), color = CardText, fontSize = 44.sp, fontWeight = FontWeight.Light,
                    letterSpacing = 5.28.sp, style = TabularNums, maxLines = 1,
                )
                Spacer(Modifier.height(16.dp))
                if (c.reconnecting) {
                    // The network blipped: no bouncing bars while no audio flows.
                    Box(Modifier.height(30.dp))
                    Spacer(Modifier.height(16.dp))
                    StatusPill("Reconnecting…", dot = Amber, bg = Amber.copy(alpha = 0.14f), textColor = Palette.Call.Gold)
                } else {
                    Waveform()
                    Spacer(Modifier.height(16.dp))
                    StatusPill("Connected")
                }
            }
            c.error?.let {
                Spacer(Modifier.height(16.dp))
                Text(it, color = Palette.Red300, fontSize = 14.sp, textAlign = TextAlign.Center)
            }
            if (c.busy) {
                Spacer(Modifier.height(16.dp))
                Text("Saving the callback…", color = Palette.Call.Soft, fontSize = 14.sp, textAlign = TextAlign.Center)
            }
            if (c.phase == CallPhase.Ended) {
                Spacer(Modifier.height(16.dp))
                Text(c.note ?: "Call ended", color = Palette.Call.StageEnded, fontSize = 14.sp, textAlign = TextAlign.Center)
            }
        }

            Spacer(Modifier.height(if (short) 24.dp else 40.dp))
            if (ringing) {
                // justify-center gap-12 items-end
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = CenteredGap(48.dp),
                    verticalAlignment = Alignment.Bottom,
                ) {
                    // Disabled (dimmed) while a callback is being saved: no second request.
                    val on = !c.busy
                    CallButton(Red, "Decline", CallIcons.PhoneOff, enabled = on, onClick = actions.decline)
                    CallButton(Amber, "Callback", CallIcons.Callback, size = ButtonSize.Small, enabled = on, onClick = actions.callback)
                    CallButton(WaGreen, "Answer", CallIcons.Phone, size = ButtonSize.Big, enabled = on, onClick = actions.answer)
                }
            }
            if (c.phase == CallPhase.Connecting || live) {
                // justify-center gap-14 items-center (web: Mute + Hang up; the
                // speaker toggle is Android's — a phone has an earpiece).
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = CenteredGap(56.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CallButton(
                        if (c.muted) LabelGrey else Palette.Call.StageControl,
                        if (c.muted) "Unmute" else "Mute",
                        if (c.muted) CallIcons.MicOff else CallIcons.Mic,
                        onClick = actions.toggleMute,
                    )
                    CallButton(
                        if (c.speaker) LabelGrey else Palette.Call.StageControl,
                        if (c.speaker) "Speaker on" else "Speaker",
                        CallIcons.Speaker,
                        onClick = actions.toggleSpeaker,
                    )
                    CallButton(Red, "Hang up", CallIcons.PhoneOff, size = ButtonSize.Big, onClick = actions.hangup)
                }
            }
        }
    }
}

@Composable
private fun StatusPill(text: String, dot: Color = WaGreen, bg: Color = PillBg, textColor: Color = PillText) {
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(bg).padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
        Spacer(Modifier.width(8.dp))
        Text(text, color = textColor, fontSize = 13.sp)
    }
}

/** The expanding green rings behind a ringing avatar (cr1 / cr2 keyframes). */
@Composable
private fun PulseRing(maxScale: Float, startAlpha: Float, size: Dp = 132.dp) {
    val t = rememberInfiniteTransition(label = "ring")
    val p by t.animateFloat(
        0f, 1f,
        // cr1 / cr2: 1.7s ease-out infinite.
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
            .background(WaGreen),
    )
}

/**
 * 15 bars bouncing between 5 and 26dp (the cwf keyframes). The heights are
 * read while drawing, not composing: a live call redraws one small canvas per
 * frame instead of recomposing and re-measuring fifteen boxes 60 times a second.
 */
@Composable
private fun Waveform() {
    val t = rememberInfiniteTransition(label = "wave")
    val heights = List(15) { i ->
        t.animateFloat(
            5f, 26f,
            infiniteRepeatable(
                // cwf: 0.9s ease-in-out — each half is its own ease-in-out segment.
                tween(450, easing = CssEaseInOut), RepeatMode.Reverse,
                initialStartOffset = StartOffset((i % 8) * 80),
            ),
            label = "bar$i",
        )
    }
    // 15 × 3dp bars, 4dp apart, centred in a 30dp band.
    Box(
        Modifier.size(width = (15 * 3 + 14 * 4).dp, height = 30.dp).drawBehind {
            val w = 3.dp.toPx()
            val gap = 4.dp.toPx()
            val r = androidx.compose.ui.geometry.CornerRadius(2.dp.toPx())
            heights.forEachIndexed { i, h ->
                val hp = h.value.dp.toPx()
                drawRoundRect(
                    WaGreen,
                    topLeft = androidx.compose.ui.geometry.Offset(i * (w + gap), (size.height - hp) / 2f),
                    size = androidx.compose.ui.geometry.Size(w, hp),
                    cornerRadius = r,
                )
            }
        },
    )
}

/** Every call control is at least 56dp across (Callback was the web's 54px). */
private enum class ButtonSize(val d: Dp, val icon: Dp) { Small(56.dp, 24.dp), Normal(62.dp, 24.dp), Big(72.dp, 28.dp) }

@Composable
private fun CallButton(
    color: Color,
    label: String,
    icon: ImageVector,
    size: ButtonSize = ButtonSize.Normal,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Column(
        Modifier
            .alpha(if (enabled) 1f else 0.45f)
            .clickable(interactionSource = interaction, indication = null, enabled = enabled, onClick = onClick)
            .semantics { contentDescription = label },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier
                .scale(if (pressed) 0.95f else 1f)
                .size(size.d)
                .shadow(8.dp, CircleShape)
                .clip(CircleShape)
                .background(color),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, null, tint = Color.White, modifier = Modifier.size(size.icon))
        }
        Spacer(Modifier.height(10.dp))
        // Large text wraps under its own button instead of pushing the row off the card.
        Text(
            label, color = LabelGrey, fontSize = 12.sp, textAlign = TextAlign.Center, maxLines = 2,
            modifier = Modifier.widthIn(max = size.d + 48.dp),
        )
    }
}
