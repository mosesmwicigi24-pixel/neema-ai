package ke.co.bethanyhouse.neema.feature.calls

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.PhoneCallback
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ke.co.bethanyhouse.neema.app.DashboardViewModel

private val WaGreen = Color(0xFF25D366)
private val CardText = Color(0xFFE9EDEF)
private val SubText = Color(0xFF8AA89A)
private val PillText = Color(0xFFA8E6C4)
private val PillBg = Color(0x2425D366)
private val Red = Color(0xFFE24B4A)
private val Amber = Color(0xFFEF9F27)
private val LabelGrey = Color(0xFF8696A0)

private fun mmss(s: Int) = "%02d:%02d".format(s / 60, s % 60)

/** The call card over the content area (components/CallStage.tsx). Renders nothing when idle. */
@Composable
fun CallStage(dash: DashboardViewModel) {
    val calls = dash.container.calls
    val c by calls.state.collectAsStateWithLifecycle()
    val pendingAnswer by calls.pendingAnswer.collectAsStateWithLifecycle()
    val withMic = rememberMicPermission()

    // "Answer" tapped on the notification before the mic was allowed: ask now.
    LaunchedEffect(pendingAnswer) {
        if (pendingAnswer) {
            calls.consumePendingAnswer()
            withMic { calls.answer() }
        }
    }

    if (c.phase == CallPhase.Idle) return

    val who = c.name?.takeIf { it.isNotBlank() } ?: c.from?.takeIf { it.isNotEmpty() }?.let { "+$it" } ?: "Unknown"
    val initial = (who.replace("+", "").firstOrNull()?.toString() ?: "?").uppercase()
    val ringing = c.phase == CallPhase.Ringing
    val live = c.phase == CallPhase.InCall

    Box(
        Modifier
            .fillMaxSize()
            .drawBehind {
                // radial-gradient(130% 100% at 50% 0%, #0e5c3a 0%, #06110b 60%)
                drawRect(
                    Brush.radialGradient(
                        0f to Color(0xFF0E5C3A), 0.6f to Color(0xFF06110B), 1f to Color(0xFF06110B),
                        center = Offset(size.width / 2f, 0f),
                        radius = maxOf(size.height, size.width * 1.3f).coerceAtLeast(1f),
                    ),
                )
            }
            // The card owns the content area: swallow taps meant for the screen below.
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
        contentAlignment = Alignment.Center,
    ) {
        Column(
            Modifier
                .padding(24.dp)
                .widthIn(max = 448.dp)
                .fillMaxWidth()
                .shadow(30.dp, RoundedCornerShape(32.dp))
                .clip(RoundedCornerShape(32.dp))
                .background(Color(0x990B141A))
                .border(1.dp, Color(0x2E25D366), RoundedCornerShape(32.dp))
                .verticalScroll(rememberScrollState())
                .padding(start = 32.dp, end = 32.dp, top = 48.dp, bottom = 36.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // Avatar with the ringing pulse and the live dot.
            Box(Modifier.size(132.dp), contentAlignment = Alignment.Center) {
                if (ringing) {
                    PulseRing(maxScale = 2f, startAlpha = 0.45f)
                    PulseRing(maxScale = 2.6f, startAlpha = 0.3f)
                }
                Box(
                    Modifier.size(132.dp).clip(CircleShape).background(WaGreen),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(initial, color = Color(0xFF04220F), fontSize = 46.sp, fontWeight = FontWeight.SemiBold)
                }
                if (live) Box(
                    Modifier.align(Alignment.BottomEnd).padding(8.dp).size(26.dp).clip(CircleShape)
                        .background(Color(0xFF06110B)).padding(5.dp).clip(CircleShape).background(WaGreen),
                )
            }
            Spacer(Modifier.height(24.dp))
            Text(who, color = CardText, fontSize = 26.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (!c.from.isNullOrEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text("+${c.from}", color = SubText, fontSize = 14.sp, letterSpacing = 2.sp)
            }

            if (ringing) {
                Spacer(Modifier.height(20.dp))
                StatusPill("Incoming WhatsApp")
            }
            if (c.phase == CallPhase.Connecting) {
                Spacer(Modifier.height(24.dp))
                Text("Connecting…", color = Color(0xFFCFE9D9), fontSize = 14.sp)
            }
            if (live) {
                Spacer(Modifier.height(24.dp))
                Text(mmss(c.seconds), color = CardText, fontSize = 44.sp, fontWeight = FontWeight.Light, letterSpacing = 5.sp)
                Spacer(Modifier.height(16.dp))
                Waveform()
                Spacer(Modifier.height(16.dp))
                StatusPill("Connected")
            }
            c.error?.let {
                Spacer(Modifier.height(16.dp))
                Text(it, color = Color(0xFFFCA5A5), fontSize = 14.sp)
            }
            if (c.phase == CallPhase.Ended) {
                Spacer(Modifier.height(16.dp))
                Text(c.note ?: "Call ended", color = Color(0xFFA8C7B6), fontSize = 14.sp)
            }

            Spacer(Modifier.height(40.dp))
            if (ringing) {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.Bottom,
                ) {
                    CallButton(Red, "Decline", Icons.Filled.CallEnd, onClick = calls::hangup)
                    CallButton(Amber, "Callback", Icons.Filled.PhoneCallback, size = ButtonSize.Small, onClick = calls::callback)
                    CallButton(WaGreen, "Answer", Icons.Filled.Call, size = ButtonSize.Big) { withMic { calls.answer() } }
                }
            }
            if (c.phase == CallPhase.Connecting || live) {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CallButton(
                        if (c.muted) LabelGrey else Color(0xFF1F2C33),
                        if (c.muted) "Unmute" else "Mute",
                        if (c.muted) Icons.Filled.MicOff else Icons.Filled.Mic,
                        onClick = calls::toggleMute,
                    )
                    CallButton(
                        if (c.speaker) LabelGrey else Color(0xFF1F2C33),
                        if (c.speaker) "Speaker on" else "Speaker",
                        Icons.AutoMirrored.Filled.VolumeUp,
                        onClick = calls::toggleSpeaker,
                    )
                    CallButton(Red, "Hang up", Icons.Filled.CallEnd, size = ButtonSize.Big, onClick = calls::hangup)
                }
            }
        }
    }
}

@Composable
private fun StatusPill(text: String) {
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(PillBg).padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(WaGreen))
        Spacer(Modifier.width(8.dp))
        Text(text, color = PillText, fontSize = 13.sp)
    }
}

/** The expanding green rings behind a ringing avatar (cr1 / cr2 keyframes). */
@Composable
private fun PulseRing(maxScale: Float, startAlpha: Float) {
    val t = rememberInfiniteTransition(label = "ring")
    val p by t.animateFloat(
        0f, 1f,
        infiniteRepeatable(tween(1700, easing = FastOutSlowInEasing), RepeatMode.Restart),
        label = "ringP",
    )
    Box(
        Modifier.size(132.dp)
            .graphicsLayer {
                val s = 1f + (maxScale - 1f) * p
                scaleX = s; scaleY = s
                alpha = startAlpha * (1f - p)
            }
            .clip(CircleShape)
            .background(WaGreen),
    )
}

/** 15 bars bouncing between 5 and 26dp (the cwf keyframes). */
@Composable
private fun Waveform() {
    val t = rememberInfiniteTransition(label = "wave")
    Row(Modifier.height(30.dp), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
        repeat(15) { i ->
            val h by t.animateFloat(
                5f, 26f,
                infiniteRepeatable(
                    tween(450, easing = LinearEasing), RepeatMode.Reverse,
                    initialStartOffset = StartOffset((i % 8) * 80),
                ),
                label = "bar$i",
            )
            Box(Modifier.width(3.dp).height(h.dp).clip(RoundedCornerShape(2.dp)).background(WaGreen))
        }
    }
}

private enum class ButtonSize(val d: Dp, val icon: Dp) { Small(54.dp, 24.dp), Normal(62.dp, 24.dp), Big(72.dp, 28.dp) }

@Composable
private fun CallButton(
    color: Color,
    label: String,
    icon: ImageVector,
    size: ButtonSize = ButtonSize.Normal,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Column(
        Modifier
            .clickable(interactionSource = interaction, indication = null, onClick = onClick)
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
        Text(label, color = LabelGrey, fontSize = 12.sp)
    }
}
