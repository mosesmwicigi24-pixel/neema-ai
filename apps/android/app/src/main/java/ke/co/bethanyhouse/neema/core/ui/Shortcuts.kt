package ke.co.bethanyhouse.neema.core.ui

import android.content.res.Configuration
import androidx.compose.runtime.Composable
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEvent
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.isAltPressed
import androidx.compose.ui.input.key.isCtrlPressed
import androidx.compose.ui.input.key.isMetaPressed
import androidx.compose.ui.input.key.isShiftPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalConfiguration

/**
 * Hardware-keyboard shortcuts (a Tab S9 Ultra with its Book Cover Keyboard,
 * DeX with a desk keyboard). The decisions are pure, so every combination is
 * unit-tested; the composables only read the event and act.
 *
 * - Enter sends a reply when a hardware keyboard is attached; Shift+Enter is
 *   a new line. Ctrl/⌘+Enter always sends (the on-screen keyboard too).
 * - Ctrl+1…9 opens the nth view in the navigation; Ctrl+B shows or hides the
 *   sidebar's labels.
 * - In the inbox: Alt+↓ / Alt+↑ (or Ctrl+] / Ctrl+[) move to the next /
 *   previous conversation; Ctrl+F or Ctrl+K jumps to the search box.
 */
sealed interface Shortcut {
    data object Send : Shortcut
    data object NextConversation : Shortcut
    data object PreviousConversation : Shortcut
    data object Search : Shortcut
    data object ToggleNav : Shortcut
    data class View(val index: Int) : Shortcut
}

/** What a key press means for the reply box. Null: type it as usual. */
fun composerShortcut(key: Key, down: Boolean, shift: Boolean, ctrl: Boolean, hardwareKeyboard: Boolean): Shortcut? {
    if (!down || (key != Key.Enter && key != Key.NumPadEnter)) return null
    return when {
        ctrl -> Shortcut.Send
        shift -> null
        hardwareKeyboard -> Shortcut.Send
        else -> null
    }
}

/** What a key press means app-wide / in the inbox (never plain letters: those type). */
fun appShortcut(key: Key, down: Boolean, ctrl: Boolean, alt: Boolean, shift: Boolean): Shortcut? {
    if (!down || shift) return null
    if (alt && !ctrl) return when (key) {
        Key.DirectionDown -> Shortcut.NextConversation
        Key.DirectionUp -> Shortcut.PreviousConversation
        else -> null
    }
    if (!ctrl || alt) return null
    return when (key) {
        Key.RightBracket -> Shortcut.NextConversation
        Key.LeftBracket -> Shortcut.PreviousConversation
        Key.F, Key.K -> Shortcut.Search
        Key.B -> Shortcut.ToggleNav
        Key.One -> Shortcut.View(0)
        Key.Two -> Shortcut.View(1)
        Key.Three -> Shortcut.View(2)
        Key.Four -> Shortcut.View(3)
        Key.Five -> Shortcut.View(4)
        Key.Six -> Shortcut.View(5)
        Key.Seven -> Shortcut.View(6)
        Key.Eight -> Shortcut.View(7)
        Key.Nine -> Shortcut.View(8)
        else -> null
    }
}

fun KeyEvent.appShortcut(): Shortcut? =
    appShortcut(key, type == KeyEventType.KeyDown, isCtrlPressed || isMetaPressed, isAltPressed, isShiftPressed)

fun KeyEvent.composerShortcut(hardwareKeyboard: Boolean): Shortcut? =
    composerShortcut(key, type == KeyEventType.KeyDown, isShiftPressed, isCtrlPressed || isMetaPressed, hardwareKeyboard)

/** A physical keyboard is attached and open (a Book Cover Keyboard, a Bluetooth or DeX keyboard). */
@Composable
fun hardwareKeyboardAttached(): Boolean {
    val c = LocalConfiguration.current
    return c.keyboard == Configuration.KEYBOARD_QWERTY && c.hardKeyboardHidden != Configuration.HARDKEYBOARDHIDDEN_YES
}

/** The next / previous id in [ids] from [current] (wrapping never: the ends stay put). */
fun stepThrough(ids: List<String>, current: String?, forward: Boolean): String? {
    if (ids.isEmpty()) return null
    val i = ids.indexOf(current)
    if (i < 0) return if (forward) ids.first() else ids.last()
    val j = (if (forward) i + 1 else i - 1).coerceIn(0, ids.lastIndex)
    return ids[j]
}
