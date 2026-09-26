package ke.co.bethanyhouse.neema.feature.conversations

import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.layout.layout
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Dp
import ke.co.bethanyhouse.neema.core.ui.theme.Neema

/**
 * A tinted surface — a chip, a pill, a strip — as the web draws it in light
 * mode (a Tailwind `*-50` fill, `*-200` border and `*-700` ink).
 *
 * The web keeps those pastel boxes as they are on its dark theme, which on the
 * app's Prussian-blue dark mode reads as a glaring white card. In dark mode the
 * same hue becomes a translucent wash of its ink over the dark surface, a
 * stronger rim, and the ink lifted toward white — ≥ 4.5:1 on the dark
 * background for every ink the inbox uses.
 */
@Immutable
internal data class Tint(val bg: Color, val fg: Color, val border: Color)

@Composable
internal fun tint(bg: Color, fg: Color, border: Color = bg): Tint =
    if (!Neema.colors.isDark) Tint(bg, fg, border) else darkTint(fg)

/** The dark-mode form of a tint whose light-mode ink is [fg]. */
internal fun darkTint(fg: Color): Tint =
    Tint(bg = fg.copy(alpha = 0.16f), fg = darkInk(fg), border = darkInk(fg).copy(alpha = 0.45f))

internal fun darkInk(fg: Color): Color = lerp(fg, Color.White, 0.45f)

/** Just the ink of [tint] — text sitting on the page, not on a tinted box. */
@Composable
internal fun ink(fg: Color): Color = if (!Neema.colors.isDark) fg else darkInk(fg)

/**
 * Vertical text (a collapsed side rail's label): rotated −90° AND measured
 * rotated, so it takes its real height in the column instead of spilling over
 * its neighbours — at any font scale.
 */
internal fun Modifier.verticalLabel(): Modifier = layout { m, _ ->
    val p = m.measure(Constraints())
    layout(p.height, p.width) { p.place(-(p.width - p.height) / 2, (p.width - p.height) / 2) }
}.rotate(-90f)


/**
 * A Material button's fixed web height (h-7, h-8, h-9) at the default font
 * scale — Material would otherwise pad it to its own 40 dp minimum — and at
 * least that height, growing with its label, when the user has asked for
 * larger text. (Touch targets stay 48 dp either way: Compose widens the hit
 * area of a small control on its own.)
 */
@Composable
internal fun Modifier.webHeight(h: Dp): Modifier =
    if (LocalDensity.current.fontScale > 1f) heightIn(min = h) else height(h)
