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
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

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

/**
 * Moved to core: `Palette` now names every one of these colours. These
 * forwards keep existing references compiling until the integrator points
 * them at `Palette.X` and deletes this object.
 */
internal object Hue {
    val Sky100 = Palette.Sky100
    val Sky200 = Palette.Sky200
    val Sky300 = Palette.Sky300
    val Sky400 = Palette.Sky400
    val Sky700 = Palette.Sky700
    val Violet100 = Palette.Violet100
    val Violet500 = Palette.Violet500
    val Violet700 = Palette.Violet700
    val Purple100 = Palette.Purple100
    val Purple300 = Palette.Purple300
    val Indigo50 = Palette.Indigo50
    val Indigo100 = Palette.Indigo100
    val Indigo200 = Palette.Indigo200
    val Indigo300 = Palette.Indigo300
    val Indigo700 = Palette.Indigo700
    val Blue100 = Palette.Blue100
    val Blue300 = Palette.Blue300
    val Blue800 = Palette.Blue800
    val Blue950 = Palette.Blue950
    val Green100 = Palette.Green100
    val Green200 = Palette.Green200
    val Green300 = Palette.Green300
    val Green400 = Palette.Green400
    val Green700 = Palette.Green700
    val Emerald100 = Palette.Emerald100
    val Emerald900 = Palette.Emerald900
    val Teal100 = Palette.Teal100
    val Teal300 = Palette.Teal300
    val Lime50 = Palette.Lime50
    val Lime300 = Palette.Lime300
    val Lime800 = Palette.Lime800
    val Orange50 = Palette.Orange50
    val Orange100 = Palette.Orange100
    val Orange200 = Palette.Orange200
    val Orange300 = Palette.Orange300
    val Orange500 = Palette.Orange500
    val Orange600 = Palette.Orange600
    val Orange700 = Palette.Orange700
    val Slate100 = Palette.Slate100
    val Slate600 = Palette.Slate600
    val Slate800 = Palette.Slate800
    val Gray800 = Palette.Gray800
    val Amber950 = Palette.Amber950
    val Red950 = Palette.Red950
    val BubbleGreen = Palette.BubbleGreen
    val BubbleInk = Palette.BubbleInk
    val LivePill = Palette.LivePill
    val LivePillInk = Palette.LivePillInk
    val ActiveRow = Palette.ActiveRow
    val UnreadEdge = Palette.UnreadEdge
    val PickedRow = Palette.PickedRow
    val StoneGreen = Palette.StoneGreen
    val ForestInk = Palette.ForestInk
    val SageRing = Palette.SageRing
    val SagePale = Palette.SagePale
    val SageDeep = Palette.SageDeep
    val SageDetail = Palette.SageDetail
    val SageCaption = Palette.SageCaption
    val SageRim = Palette.SageRim
    val SageDash = Palette.SageDash
    val SageField = Palette.SageField
    val SageFieldBg = Palette.SageFieldBg
    val SageRule = Palette.SageRule
    val SageQuote = Palette.SageQuote
    val SageStrip = Palette.SageStrip
    val SageBanner = Palette.SageBanner
    val SageResult = Palette.SageResult
    val SageResultRim = Palette.SageResultRim
    val SageButton = Palette.SageButton
    val MossNight = Palette.MossNight
    val MossBright = Palette.MossBright
    val MossWash = Palette.MossWash
    val MossRim = Palette.MossRim
    val MossTint = Palette.MossTint
    val ForestText = Palette.ForestText
    val CoolGray = Palette.CoolGray
    val WhatsAppDeep = Palette.WhatsAppDeep
    val MessengerSky = Palette.MessengerSky
    val InstaOrange = Palette.InstaOrange
    val InstaCoral = Palette.InstaCoral
    val InstaRed = Palette.InstaRed
    val InstaMagenta = Palette.InstaMagenta
    val InstaPurple = Palette.InstaPurple
    val PipeGold = Palette.PipeGold
    val PipeGoldSolid = Palette.PipeGoldSolid
    val PipeGoldInk = Palette.PipeGoldInk
    val PipeGoldWash = Palette.PipeGoldWash
    val PipeGoldRim = Palette.PipeGoldRim
    val PipeLost = Palette.PipeLost
    val PipeLostIcon = Palette.PipeLostIcon
    val PipeLostText = Palette.PipeLostText
}
