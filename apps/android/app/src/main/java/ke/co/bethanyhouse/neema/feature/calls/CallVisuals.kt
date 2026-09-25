package ke.co.bethanyhouse.neema.feature.calls

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons

/**
 * The exact stroked icons CallStage.tsx (ICONS) and CallsView.tsx (DirIcon,
 * the transcript and chat buttons) draw, from the web's own SVG paths.
 * Tinted by the Icon that shows them.
 */
internal object CallIcons {
    private fun build(name: String, width: Float, vararg paths: String): ImageVector =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
            paths.forEach { d ->
                addPath(
                    pathData = addPathNodes(WebIcons.expandArcFlags(d)),
                    stroke = SolidColor(Color.Black),
                    strokeLineWidth = width,
                    strokeLineCap = StrokeCap.Round,
                    strokeLineJoin = StrokeJoin.Round,
                )
            }
        }.build()

    // CallStage.tsx ICONS (stroke 2).
    val Phone = build("call_phone", 2f, "M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z")
    val PhoneOff = build("call_phone_off", 2f, "M16 8l4-4m0 4l-4-4", "M18.5 16.5c.5.5.5 1.2.4 1.8A2 2 0 0117 20C9.7 20 4 14.3 4 7a2 2 0 011.7-2 1.9 1.9 0 011.8.4")
    val Callback = build("call_callback", 2f, "M9 14l-4-4 4-4M5 10h11a4 4 0 014 4v3")
    val Mic = build("call_mic", 2f, "M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z", "M5 10v1a7 7 0 0014 0v-1M12 18v3")
    val MicOff = build("call_mic_off", 2f, "M3 3l18 18", "M9 5a3 3 0 016 0v5m-1.3 2.7A3 3 0 019 11V9", "M5 10v1a7 7 0 0010.7 5.9M19 10v1a6.9 6.9 0 01-.3 2M12 18v3")
    /** Android only (earpiece ↔ loudspeaker), drawn in the same stroke style. */
    val Speaker = build("call_speaker", 2f, "M11 5L6 9H2v6h4l5 4V5z", "M15.54 8.46a5 5 0 010 7.07", "M19.07 4.93a10 10 0 010 14.14")

    // CallsView.tsx DirIcon (stroke 2.2).
    val DirIn = build("call_dir_in", 2.2f, "M17 7L7 17M7 17h7M7 17V10")
    val DirBack = build("call_dir_back", 2.2f, "M9 14l-4-4 4-4M5 10h10a4 4 0 014 4v2")

    // CallsView.tsx row buttons (stroke 2).
    val Transcript = build("call_transcript", 2f, "M4 6h16M4 12h16M4 18h10")
    val Chat = build("call_chat", 2f, "M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z")
}

/**
 * CSS `radial-gradient(<rx%> <ry%> at 50% 0%, …)`: an ellipse centred on the
 * top edge whose radii are fractions of the box's width and height. Compose's
 * radial brush is circular, so the circle is drawn squashed vertically.
 */
internal fun DrawScope.drawTopEllipseGradient(rxFraction: Float, ryFraction: Float, vararg stops: Pair<Float, Color>) {
    val rx = size.width * rxFraction
    val ry = size.height * ryFraction
    if (rx <= 0f || ry <= 0f) return
    val sy = ry / rx
    val center = Offset(size.width / 2f, 0f)
    withTransform({ scale(1f, sy, pivot = center) }) {
        drawRect(
            Brush.radialGradient(*stops, center = center, radius = rx),
            topLeft = Offset.Zero,
            size = Size(size.width, size.height / sy),
        )
    }
}

/**
 * A centred row with a fixed gap (the web's `justify-center gap-12`), which
 * narrows the gap instead of squeezing the buttons when the row is too tight
 * (a phone-width card is narrower than the web's 448px one).
 */
internal class CenteredGap(private val gap: Dp) : Arrangement.Horizontal {
    override val spacing: Dp get() = 0.dp

    override fun Density.arrange(totalSize: Int, sizes: IntArray, layoutDirection: LayoutDirection, outPositions: IntArray) {
        val sum = sizes.sum()
        val n = sizes.size
        val g = if (n > 1) minOf(gap.roundToPx(), ((totalSize - sum) / (n - 1)).coerceAtLeast(0)) else 0
        var x = ((totalSize - sum - g * (n - 1)) / 2).coerceAtLeast(0)
        val order = if (layoutDirection == LayoutDirection.Rtl) sizes.indices.reversed() else sizes.indices
        for (i in order) {
            outPositions[i] = x
            x += sizes[i] + g
        }
    }
}
