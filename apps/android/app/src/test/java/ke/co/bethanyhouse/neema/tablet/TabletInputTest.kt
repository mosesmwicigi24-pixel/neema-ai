package ke.co.bethanyhouse.neema.tablet

import androidx.compose.ui.input.key.Key
import ke.co.bethanyhouse.neema.core.ui.Shortcut
import ke.co.bethanyhouse.neema.core.ui.appShortcut
import ke.co.bethanyhouse.neema.core.ui.composerShortcut
import ke.co.bethanyhouse.neema.core.ui.stepThrough
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** A Tab S9 Ultra with its Book Cover Keyboard (or DeX): what each key does. */
class TabletInputTest {
    // ── The reply box ────────────────────────────────────────────────────────
    @Test fun enterSendsWithAHardwareKeyboard() =
        assertEquals(Shortcut.Send, composerShortcut(Key.Enter, down = true, shift = false, ctrl = false, hardwareKeyboard = true))

    @Test fun shiftEnterIsANewLine() =
        assertNull(composerShortcut(Key.Enter, down = true, shift = true, ctrl = false, hardwareKeyboard = true))

    @Test fun onScreenKeyboardEnterIsANewLine() =
        assertNull(composerShortcut(Key.Enter, down = true, shift = false, ctrl = false, hardwareKeyboard = false))

    @Test fun ctrlEnterAlwaysSends() {
        assertEquals(Shortcut.Send, composerShortcut(Key.Enter, down = true, shift = false, ctrl = true, hardwareKeyboard = false))
        assertEquals(Shortcut.Send, composerShortcut(Key.NumPadEnter, down = true, shift = false, ctrl = true, hardwareKeyboard = true))
    }

    @Test fun keyUpAndOtherKeysNeverSend() {
        assertNull(composerShortcut(Key.Enter, down = false, shift = false, ctrl = false, hardwareKeyboard = true))
        assertNull(composerShortcut(Key.A, down = true, shift = false, ctrl = true, hardwareKeyboard = true))
    }

    // ── App-wide ─────────────────────────────────────────────────────────────
    @Test fun ctrlDigitsOpenViews() {
        assertEquals(Shortcut.View(0), appShortcut(Key.One, down = true, ctrl = true, alt = false, shift = false))
        assertEquals(Shortcut.View(8), appShortcut(Key.Nine, down = true, ctrl = true, alt = false, shift = false))
    }

    @Test fun conversationWalking() {
        assertEquals(Shortcut.NextConversation, appShortcut(Key.DirectionDown, down = true, ctrl = false, alt = true, shift = false))
        assertEquals(Shortcut.PreviousConversation, appShortcut(Key.DirectionUp, down = true, ctrl = false, alt = true, shift = false))
        assertEquals(Shortcut.NextConversation, appShortcut(Key.RightBracket, down = true, ctrl = true, alt = false, shift = false))
        assertEquals(Shortcut.PreviousConversation, appShortcut(Key.LeftBracket, down = true, ctrl = true, alt = false, shift = false))
    }

    @Test fun searchAndSidebar() {
        assertEquals(Shortcut.Search, appShortcut(Key.F, down = true, ctrl = true, alt = false, shift = false))
        assertEquals(Shortcut.Search, appShortcut(Key.K, down = true, ctrl = true, alt = false, shift = false))
        assertEquals(Shortcut.ToggleNav, appShortcut(Key.B, down = true, ctrl = true, alt = false, shift = false))
    }

    // Plain typing, text editing chords and arrows without a modifier stay the field's.
    @Test fun typingAndEditingAreNeverTaken() {
        for (k in listOf(Key.A, Key.F, Key.One, Key.DirectionDown, Key.Enter, Key.Escape)) {
            assertNull("$k", appShortcut(k, down = true, ctrl = false, alt = false, shift = false))
        }
        for (k in listOf(Key.C, Key.V, Key.X, Key.Z, Key.A)) {
            assertNull("ctrl+$k", appShortcut(k, down = true, ctrl = true, alt = false, shift = false))
        }
        assertNull("ctrl+shift+F", appShortcut(Key.F, down = true, ctrl = true, alt = false, shift = true))
        assertNull("alt+→", appShortcut(Key.DirectionRight, down = true, ctrl = false, alt = true, shift = false))
        assertNull("key up", appShortcut(Key.One, down = false, ctrl = true, alt = false, shift = false))
    }

    // ── Drag and drop from another app (split screen / DeX) ──────────────────
    @Test fun dropsNeemaCanAttach() {
        assertEquals(true, ke.co.bethanyhouse.neema.core.ui.acceptsDrop(listOf("image/jpeg")))
        assertEquals(true, ke.co.bethanyhouse.neema.core.ui.acceptsDrop(listOf("text/plain", "video/mp4")))
        assertEquals(true, ke.co.bethanyhouse.neema.core.ui.acceptsDrop(listOf("application/pdf")))
        assertEquals(true, ke.co.bethanyhouse.neema.core.ui.acceptsDrop(listOf("APPLICATION/VND.OPENXMLFORMATS-OFFICEDOCUMENT.SPREADSHEETML.SHEET")))
    }

    @Test fun textAndLinksAreNotAttachments() {
        assertEquals(false, ke.co.bethanyhouse.neema.core.ui.acceptsDrop(listOf("text/plain")))
        assertEquals(false, ke.co.bethanyhouse.neema.core.ui.acceptsDrop(listOf("text/uri-list", "text/html")))
        assertEquals(false, ke.co.bethanyhouse.neema.core.ui.acceptsDrop(emptyList()))
    }

    @Test fun stepping() {
        val ids = listOf("a", "b", "c")
        assertEquals("b", stepThrough(ids, "a", true))
        assertEquals("c", stepThrough(ids, "c", true))
        assertEquals("a", stepThrough(ids, "a", false))
        assertEquals("a", stepThrough(ids, null, true))
        assertEquals("c", stepThrough(ids, "gone", false))
        assertNull(stepThrough(emptyList(), "a", true))
    }
}
