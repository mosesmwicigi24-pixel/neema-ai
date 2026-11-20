package ke.co.bethanyhouse.neema.theme

import ke.co.bethanyhouse.neema.core.ui.theme.TextScale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The app-wide text size (owner, 2026-11-20): A− and A+ move one step, never past the ends. */
class TextScaleTest {
    @Test fun stepsUpAndDownFromTheStandardSize() {
        assertEquals(1.1f, TextScale.bigger(1f))
        assertEquals(0.9f, TextScale.smaller(1f))
        assertEquals("100%", TextScale.label(TextScale.DEFAULT))
        assertEquals("120%", TextScale.label(1.2f))
    }

    @Test fun neverPastTheEnds() {
        val top = TextScale.STEPS.last(); val bottom = TextScale.STEPS.first()
        assertEquals(top, TextScale.bigger(top)); assertFalse(TextScale.canGrow(top))
        assertEquals(bottom, TextScale.smaller(bottom)); assertFalse(TextScale.canShrink(bottom))
        assertTrue(TextScale.canGrow(1f) && TextScale.canShrink(1f))
    }

    @Test fun aStoredOddValueLandsOnAStep() {
        assertEquals(1.1f, TextScale.clamp(1.08f))
        assertEquals(1.6f, TextScale.clamp(9f))
        assertEquals(0.85f, TextScale.clamp(0f))
    }
}
