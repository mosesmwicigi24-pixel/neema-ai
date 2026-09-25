package ke.co.bethanyhouse.neema.feature.orders

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons
import java.util.Locale

/**
 * The web's flat channel marks — OrdersView `CH_ICON` and LeadsView `CH_SVG`,
 * path for path. Brand marks are filled, email/SMS stroked at 1.5; draw them
 * with `Icon(tint = White)` on the channel colour.
 */
object ChannelGlyphs {
    private fun glyph(name: String, d: String, stroked: Boolean = false): ImageVector =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
            addPath(
                pathData = addPathNodes(WebIcons.expandArcFlags(d)),
                fill = if (stroked) null else SolidColor(Color.White),
                stroke = if (stroked) SolidColor(Color.White) else null,
                strokeLineWidth = 1.5f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            )
        }.build()

    val WhatsApp = glyph(
        "whatsapp",
        "M12 2C6.48 2 2 6.48 2 12c0 1.82.48 3.54 1.32 5.04L2 22l5.08-1.3A9.94 9.94 0 0012 22c5.52 0 10-4.48 10-10S17.52 2 12 2zm0 18c-1.56 0-3.02-.44-4.26-1.2l-.3-.18-3.14.72.7-3.06-.2-.32A7.96 7.96 0 014 12c0-4.42 3.58-8 8-8s8 3.58 8 8-3.58 8-8 8zm4.24-5.78c-.24-.12-1.42-.7-1.64-.78-.22-.08-.38-.12-.54.12-.16.24-.62.78-.76.94-.14.16-.28.18-.52.06-.24-.12-1.02-.38-1.94-1.18a7.2 7.2 0 01-1.34-1.64c-.14-.24 0-.36.1-.5.1-.1.24-.28.36-.42.12-.16.16-.26.24-.44.08-.16.04-.3 0-.42-.06-.14-.54-1.32-.74-1.8-.2-.48-.4-.42-.54-.44h-.46c-.16 0-.42.06-.64.3-.22.24-.84.82-.84 2s.86 2.32.98 2.48c.12.16 1.7 2.6 4.12 3.64.58.26 1.02.4 1.38.52.58.18 1.1.16 1.52.1.46-.08 1.42-.58 1.62-1.14.2-.56.2-1.04.14-1.14-.08-.1-.22-.16-.46-.28z",
    )
    val Messenger = glyph(
        "messenger",
        "M12 2C6.477 2 2 6.145 2 11.259c0 2.906 1.395 5.502 3.58 7.215V22l3.254-1.843A10.61 10.61 0 0012 20.518c5.523 0 10-4.145 10-9.259S17.523 2 12 2zm1.067 12.508L10.9 12.26l-4.24 2.248 4.718-5.009 2.249 2.25 4.148-2.25-4.708 5.009z",
    )
    val Instagram = glyph(
        "instagram",
        "M12 7.5A4.5 4.5 0 1012 16.5 4.5 4.5 0 0012 7.5zm0 7.5a3 3 0 110-6 3 3 0 010 6zm5.92-7.69a1.05 1.05 0 11-2.1 0 1.05 1.05 0 012.1 0zM21.94 9c-.07-1.47-.4-2.77-1.48-3.85S17.47 3.13 16 3.06C14.48 3 9.52 3 8 3.06 6.53 3.13 5.23 3.46 4.15 4.54S2.13 7.53 2.06 9C2 10.52 2 15.48 2.06 17c.07 1.47.4 2.77 1.48 3.85S6.53 22.87 8 22.94c1.52.06 6.48.06 8 0 1.47-.07 2.77-.4 3.85-1.48S22.87 18.47 22.94 17C23 15.48 23 10.52 22.94 9zM21.2 18.62a3.26 3.26 0 01-1.84 1.84c-1.27.5-4.29.39-5.7.39s-4.43.1-5.7-.39a3.26 3.26 0 01-1.84-1.84C5.63 17.35 5.74 14.33 5.74 12s-.1-5.35.39-5.62A3.26 3.26 0 017.97 4.54c1.27-.5 4.29-.39 5.7-.39s4.43-.1 5.7.39a3.26 3.26 0 011.84 1.84c.5 1.27.39 4.29.39 5.62s.11 5.35-.4 5.62z",
    )
    val Facebook = glyph("facebook", "M13 10V7a1 1 0 011-1h1V3h-2a4 4 0 00-4 4v3H7v3h2v8h3v-8h2.5l.5-3H13z")
    val Email = glyph("email", "M3 8l9 6 9-6M5 6h14a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2z", stroked = true)
    val Sms = glyph(
        "sms",
        "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
        stroked = true,
    )

    /** LeadsView `CH_SVG[ch] ?? CH_SVG.sms` — every lead channel has a mark. */
    fun forLead(ch: String): ImageVector = when (ch.lowercase(Locale.ROOT)) {
        "whatsapp" -> WhatsApp
        "messenger" -> Messenger
        "instagram" -> Instagram
        "facebook" -> Facebook
        "email" -> Email
        else -> Sms
    }

    /** OrdersView `CH_ICON[ch]` — only these four carry a mark in the orders list. */
    fun forOrder(ch: String): ImageVector? = when (ch.lowercase(Locale.ROOT)) {
        "whatsapp" -> WhatsApp
        "messenger" -> Messenger
        "email" -> Email
        "sms" -> Sms
        else -> null
    }
}
