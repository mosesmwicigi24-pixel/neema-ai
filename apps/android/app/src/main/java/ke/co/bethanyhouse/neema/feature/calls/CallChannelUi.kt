package ke.co.bethanyhouse.neema.feature.calls

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Messenger's accent on the call surfaces (CallStage.tsx MSGR): white glyph on
 * [Blue] is 3.7:1 (≥ 3:1 for the Answer icon); text buttons sit on the darker
 * [Ink] (5.4:1 for white text). Everything else about a call is shared.
 */
internal object Msgr {
    val Blue = Color(0xFF0084FF)
    val Ink = Color(0xFF0066D6)
    val Purple = Color(0xFFA033FF)
    val Ring = Brush.linearGradient(listOf(Blue, Purple))
    /** The badge on the dark call log (CallsView.tsx CH_BADGE): 7:1+ on its tint. */
    val BadgeFg = Color(0xFF9CCBFF)
    val BadgeBg = Color(0x2E0084FF)
    /** The badge on the light thread (ConversationsView.tsx CallPill). */
    val LightFg = Ink
    val LightBg = Color(0xFFEAF3FF)
}

/** WhatsApp's badge colours: on the dark log, and on the light thread. */
private val WaBadgeFg = Color(0xFF7EE2A8)
private val WaBadgeBg = Color(0x2425D366)
private val WaLightFg = Color(0xFF128C4B)
private val WaLightBg = Color(0xFFE7F6EC)

/** The call glyphs of CallStage.tsx (WhatsAppGlyph / MessengerGlyph), 24×24. */
internal object ChannelGlyphs {
    // Compact arc flags ("a.8.8 0 001.12.71") are expanded first: PathParser can't read them.
    private fun nodes(d: String) = addPathNodes(ke.co.bethanyhouse.neema.core.ui.theme.WebIcons.expandArcFlags(d))

    private const val MSGR_BUBBLE =
        "M12 2C6.36 2 2 6.13 2 11.7c0 2.91 1.19 5.44 3.14 7.17.16.14.26.35.27.57l.05 1.78a.8.8 0 001.12.71l1.98-.87a.8.8 0 01.53-.04c.91.25 1.87.38 2.91.38 5.64 0 10-4.13 10-9.7S17.64 2 12 2z"
    private const val MSGR_BOLT =
        "M6 14.54l2.94-4.66a1.5 1.5 0 012.17-.4l2.34 1.75a.6.6 0 00.72 0l3.16-2.4c.42-.32.97.18.69.63l-2.94 4.66a1.5 1.5 0 01-2.17.4l-2.34-1.75a.6.6 0 00-.72 0l-3.16 2.4c-.42.32-.97-.18-.69-.63z"
    private const val WA_RING =
        "M12 2a10 10 0 00-8.6 15.1L2 22l5-1.3A10 10 0 1012 2zm0 1.8a8.2 8.2 0 11-4.2 15.3l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 0112 3.8z"
    private const val WA_HANDSET =
        "M8.9 7.3c-.2-.4-.4-.4-.6-.4h-.5a1 1 0 00-.7.3 3 3 0 00-.9 2.2 5.2 5.2 0 001.1 2.7 11.8 11.8 0 004.6 4c2.3.9 2.7.7 3.2.7a2.7 2.7 0 001.8-1.3 2.2 2.2 0 00.2-1.3c-.1-.1-.3-.2-.6-.3l-1.9-.9c-.3-.1-.5-.2-.7.1l-.8 1a.5.5 0 01-.7.1 6.8 6.8 0 01-2-1.2 7.5 7.5 0 01-1.4-1.7.4.4 0 01.1-.6l.4-.5.3-.5a.5.5 0 000-.4l-.9-2z"

    /** Messenger's bubble in its blue → purple gradient with the white bolt (drawn untinted). */
    val Messenger: ImageVector by lazy {
        ImageVector.Builder("msgr_glyph", 24.dp, 24.dp, 24f, 24f)
            .addPath(nodes(MSGR_BUBBLE), fill = Brush.linearGradient(listOf(Msgr.Blue, Msgr.Purple), start = Offset(2f, 22f), end = Offset(22f, 2f)))
            .addPath(nodes(MSGR_BOLT), fill = SolidColor(Color.White))
            .build()
    }

    /** WhatsApp's bubble + handset, one colour (tinted by the Icon). */
    val WhatsApp: ImageVector by lazy {
        ImageVector.Builder("wa_glyph", 24.dp, 24.dp, 24f, 24f)
            .addPath(nodes(WA_RING), fill = SolidColor(Color.Black))
            .addPath(nodes(WA_HANDSET), fill = SolidColor(Color.Black))
            .build()
    }
}

/** The call's app glyph: Messenger's own colours, or WhatsApp's in [waTint]. */
@Composable
internal fun ChannelGlyph(channel: String?, size: Dp, waTint: Color, modifier: Modifier = Modifier) {
    if (channelOf(channel) == MESSENGER) Icon(ChannelGlyphs.Messenger, null, tint = Color.Unspecified, modifier = modifier.size(size))
    else Icon(ChannelGlyphs.WhatsApp, null, tint = waTint, modifier = modifier.size(size))
}

/**
 * "WhatsApp" / "Messenger" with its glyph — on every Calls row, the details
 * and the thread's call pills, so a mixed history is never ambiguous
 * (colour AND word, never colour alone).
 */
@Composable
fun CallChannelBadge(channel: String?, onDark: Boolean, fontSize: TextUnit = 11.sp, modifier: Modifier = Modifier) {
    val m = channelOf(channel) == MESSENGER
    val fg = when { m && onDark -> Msgr.BadgeFg; m -> Msgr.LightFg; onDark -> WaBadgeFg; else -> WaLightFg }
    val bg = when { m && onDark -> Msgr.BadgeBg; m -> Msgr.LightBg; onDark -> WaBadgeBg; else -> WaLightBg }
    val label = channelLabel(channel)
    Row(
        modifier.clip(RoundedCornerShape(50)).background(bg).padding(start = 3.dp, end = 6.dp, top = 1.dp, bottom = 1.dp)
            .semantics { contentDescription = label },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ChannelGlyph(channel, (fontSize.value + 1f).dp, waTint = fg)
        Spacer(Modifier.width(3.dp))
        Text(label, color = fg, fontSize = fontSize, fontWeight = FontWeight.SemiBold, maxLines = 1)
    }
}
