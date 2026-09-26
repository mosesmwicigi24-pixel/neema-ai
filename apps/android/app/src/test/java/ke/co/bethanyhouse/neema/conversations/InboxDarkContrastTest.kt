package ke.co.bethanyhouse.neema.conversations

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.luminance
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import ke.co.bethanyhouse.neema.core.ui.theme.DarkNeema
import ke.co.bethanyhouse.neema.feature.conversations.darkInk
import ke.co.bethanyhouse.neema.feature.conversations.darkTint
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Round 7: the inbox's tinted chips, pills and strips in dark mode. Every ink
 * the inbox paints on a tint (stage chips, country chip, live pill, window
 * strip, AI draft, notes, escalation / flag / event pills, channel chips) must
 * read at WCAG AA — ≥ 4.5:1 text on its own wash over every dark surface the
 * inbox uses — and each rim must be visible (≥ 2:1 against the surface it
 * sits on — a decorative hairline: the wash and the words carry the meaning).
 */
class InboxDarkContrastTest {
    private val inks = mapOf(
        "amber-700 (Human, escalated, qualified)" to Color(0xFFB45309),
        "amber-800 (note body)" to Color(0xFF92400E),
        "amber-600 (note label, lock)" to Color(0xFFD97706),
        "moss-dark (window open, unread, new divider)" to Color(0xFF427425),
        "blue-700 (AI draft)" to Color(0xFF1D4ED8),
        "blue-500 (draft actions)" to Color(0xFF3B82F6),
        "blue-600 (Generate AI draft)" to Color(0xFF2563EB),
        "blue-800 (draft edit text)" to Color(0xFF1E40AF),
        "red-700 (flag, closed window)" to Color(0xFFB91C1C),
        "sky-700 (contacted)" to Color(0xFF0369A1),
        "violet-700 (proposal / negotiation)" to Color(0xFF6D28D9),
        "green-700 (won, approve pill)" to Color(0xFF15803D),
        "orange-700 (country chip)" to Color(0xFFC2410C),
        "live pill" to Color(0xFF856404),
        "filter pill" to Color(0xFF699A32),
        "stone-500 (translate off)" to Color(0xFF78716C),
        "stone-600 (event pill)" to Color(0xFF57534E),
        "indigo-700 (transfer pill)" to Color(0xFF4338CA),
        "blue-700 (release pill)" to Color(0xFF1D4ED8),
        "WhatsApp" to ChannelColors.WhatsApp,
        "Messenger" to ChannelColors.Messenger,
        "Facebook" to ChannelColors.Facebook,
        "Instagram" to ChannelColors.Instagram,
    )
    private val surfaces = mapOf("bg" to DarkNeema.bg, "bg2" to DarkNeema.bg2, "bg3" to DarkNeema.bg3)

    private fun contrast(a: Color, b: Color): Double {
        val (hi, lo) = listOf(a.luminance() + 0.05, b.luminance() + 0.05).sortedDescending()
        return hi / lo
    }

    @Test fun everyTintedInk_readsAtAA_onEveryDarkSurface() {
        val failures = buildList {
            for ((name, ink) in inks) for ((sName, surface) in surfaces) {
                val t = darkTint(ink)
                val wash = t.bg.compositeOver(surface)
                val text = contrast(t.fg, wash)
                if (text < 4.5) add("$name on $sName: text ${"%.2f".format(text)}:1")
                val rim = contrast(t.border.compositeOver(surface), surface)
                if (rim < 2.0) add("$name on $sName: rim ${"%.2f".format(rim)}:1")
                // Ink straight on the page (timestamps, the ↳ marker, "● Yours").
                val bare = contrast(darkInk(ink), surface)
                if (bare < 4.5) add("$name bare on $sName: ${"%.2f".format(bare)}:1")
            }
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }
}
