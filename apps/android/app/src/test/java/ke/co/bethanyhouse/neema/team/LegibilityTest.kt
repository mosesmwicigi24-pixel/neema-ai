package ke.co.bethanyhouse.neema.team

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import ke.co.bethanyhouse.neema.core.ui.theme.DarkNeema
import ke.co.bethanyhouse.neema.core.ui.theme.LightNeema
import ke.co.bethanyhouse.neema.feature.agents.ROLE_COLORS
import ke.co.bethanyhouse.neema.feature.agents.contentOn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Round 7: the colour choices the Team / Profile screens make for legibility.
 * (No Compose UI-test runner is on the classpath, so touch targets and
 * content descriptions are checked in the screenshots and code, not here.)
 */
class LegibilityTest {
    private fun contrast(a: Color, b: Color): Float {
        val la = a.luminance(); val lb = b.luminance()
        return (maxOf(la, lb) + 0.05f) / (minOf(la, lb) + 0.05f)
    }

    private fun hex(s: String) = Color(0xFF000000 or s.removePrefix("#").toLong(16))

    @Test fun everyRoleColourGetsReadableChipText() {
        ROLE_COLORS.forEach { h ->
            val fill = hex(h)
            val text = contentOn(fill)
            assertTrue("$h: chip text at ${contrast(text, fill)}:1", contrast(text, fill) >= 3f)
        }
    }

    @Test fun darkRoleColoursKeepTheWebsWhiteText() {
        listOf("#427425", "#2a48a2", "#1f367a", "#7c3aed", "#0f766e", "#b45309").forEach {
            assertEquals(it, Color.White, contentOn(hex(it)))
        }
    }

    @Test fun paleFillsGetTheBrandText() {
        assertEquals(Color(0xFF1C2917), contentOn(Color(0xFFF59E0B)))
        assertEquals(Color(0xFF1C2917), contentOn(Color(0xFFE6F3D8)))
    }

    /** The secondary text the Team cards and Profile now use ("faint") reads on their cards. */
    @Test fun secondaryTextBeatsTheWebsPaleGreen() {
        val web = contrast(LightNeema.border2, LightNeema.bg2)
        val now = contrast(LightNeema.textDim, LightNeema.bg2)
        assertTrue("web #9ccd65 on white is $web:1", web < 2f)
        assertTrue("textDim on white is $now:1", now >= 3f)
        assertTrue(contrast(DarkNeema.muted, DarkNeema.bg2) >= 4.5f)
    }
}
