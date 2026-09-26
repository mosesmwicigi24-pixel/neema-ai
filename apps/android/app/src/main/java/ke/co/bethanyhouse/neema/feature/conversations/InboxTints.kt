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

/**
 * The inbox's named colours beyond the core [ke.co.bethanyhouse.neema.core.ui.theme.Palette]:
 * the Tailwind shades the web's inbox, thread and customer panel use that the
 * core palette does not name yet (e.g. `sky-700`, `violet-700`, `orange-100`),
 * and the hex literals ConversationsView / CustomerSidebar write inline
 * (the WhatsApp-green reply bubble, the sage hairlines, the pipeline gold).
 * Every screen in the inbox names a colour from here, Palette, ChannelColors
 * or [Neema.colors] — no `Color(0x…)` elsewhere in feature/conversations.
 */
internal object Hue {
    val Sky100 = Color(0xFFE0F2FE)
    val Sky200 = Color(0xFFBAE6FD)
    val Sky300 = Color(0xFF7DD3FC)
    val Sky400 = Color(0xFF38BDF8)
    val Sky700 = Color(0xFF0369A1)
    val Violet100 = Color(0xFFEDE9FE)
    val Violet500 = Color(0xFF8B5CF6)
    val Violet700 = Color(0xFF6D28D9)
    val Purple100 = Color(0xFFF3E8FF)
    val Purple300 = Color(0xFFD8B4FE)
    val Indigo50 = Color(0xFFEEF2FF)
    val Indigo100 = Color(0xFFE0E7FF)
    val Indigo200 = Color(0xFFC7D2FE)
    val Indigo300 = Color(0xFFA5B4FC)
    val Indigo700 = Color(0xFF4338CA)
    val Blue100 = Color(0xFFDBEAFE)
    val Blue300 = Color(0xFF93C5FD)
    val Blue800 = Color(0xFF1E40AF)
    val Blue950 = Color(0xFF172554)
    val Green100 = Color(0xFFDCFCE7)
    val Green200 = Color(0xFFBBF7D0)
    val Green300 = Color(0xFF86EFAC)
    val Green400 = Color(0xFF4ADE80)
    val Green700 = Color(0xFF15803D)
    val Emerald100 = Color(0xFFD1FAE5)
    val Emerald900 = Color(0xFF064E3B)
    val Teal100 = Color(0xFFCCFBF1)
    val Teal300 = Color(0xFF5EEAD4)
    val Lime50 = Color(0xFFF7FEE7)
    val Lime300 = Color(0xFFBEF264)
    val Lime800 = Color(0xFF3F6417)
    val Orange50 = Color(0xFFFFF7ED)
    val Orange100 = Color(0xFFFFEDD5)
    val Orange200 = Color(0xFFFED7AA)
    val Orange300 = Color(0xFFFDBA74)
    val Orange500 = Color(0xFFF97316)
    val Orange600 = Color(0xFFEA580C)
    val Orange700 = Color(0xFFC2410C)
    val Slate100 = Color(0xFFF1F5F9)
    val Slate600 = Color(0xFF475569)
    val Slate800 = Color(0xFF1E293B)
    val Gray800 = Color(0xFF1F2937)
    val Amber950 = Color(0xFF451A03)
    val Red950 = Color(0xFF450A0A)
    val BubbleGreen = Color(0xFF2AD113)
    val BubbleInk = Color(0xFF0A2E05)
    val LivePill = Color(0xFFFFF3CD)
    val LivePillInk = Color(0xFF856404)
    val ActiveRow = Color(0xFFFDF6E9)
    val UnreadEdge = Color(0xFFFCD98A)
    val PickedRow = Color(0xFFEEF6E5)
    val StoneGreen = Color(0xFFF5F6F3)
    val ForestInk = Color(0xFF3A5C28)
    val SageRing = Color(0xFFDDE8D5)
    val SagePale = Color(0xFFC5D5BC)
    val SageDeep = Color(0xFF3D5A30)
    val SageDetail = Color(0xFF8FA383)
    val SageCaption = Color(0xFF5F6F57)
    val SageRim = Color(0xFFCFDAC6)
    val SageDash = Color(0xFFC7CEC0)
    val SageField = Color(0xFFE5E8E2)
    val SageFieldBg = Color(0xFFF6F7F5)
    val SageRule = Color(0xFFF2F4EF)
    val SageQuote = Color(0xFFF2F7EE)
    val SageStrip = Color(0xFFFBFCFA)
    val SageBanner = Color(0xFFFAFBF8)
    val SageResult = Color(0xFFF8FAF6)
    val SageResultRim = Color(0xFFE8EDE4)
    val SageButton = Color(0xFFEEF2E8)
    val MossNight = Color(0xFF7FC25A)
    val MossBright = Color(0xFF86C95E)
    val MossWash = Color(0xFFE9F6DF)
    val MossRim = Color(0xFFD6E9C2)
    val MossTint = Color(0xFFF0F9E8)
    val ForestText = Color(0xFF1A2E0F)
    val CoolGray = Color(0xFFF1F3F5)
    val WhatsAppDeep = Color(0xFF1DA851)
    val MessengerSky = Color(0xFF0099FF)
    val InstaOrange = Color(0xFFF09433)
    val InstaCoral = Color(0xFFE6683C)
    val InstaRed = Color(0xFFDC2743)
    val InstaMagenta = Color(0xFFCC2366)
    val InstaPurple = Color(0xFFBC1888)
    val PipeGold = Color(0xFFC89B3C)
    val PipeGoldSolid = Color(0xFFA97C14)
    val PipeGoldInk = Color(0xFF8A6D1F)
    val PipeGoldWash = Color(0xFFFDF8EC)
    val PipeGoldRim = Color(0xFFE3CF9B)
    val PipeLost = Color(0xFFF4CCCC)
    val PipeLostIcon = Color(0xFFEFA3A3)
    val PipeLostText = Color(0xFFE08A8A)
}
