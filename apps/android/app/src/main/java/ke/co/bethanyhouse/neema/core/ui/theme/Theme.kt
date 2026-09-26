package ke.co.bethanyhouse.neema.core.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.R

/**
 * The dashboard palette (lib/themes.ts): moss-green on willow parchment by
 * day, Prussian-blue night by dark. Names follow the CSS variables so a port
 * of any view can use `Neema.colors.gold` where the web wrote `var(--gold)`.
 */
@Immutable
data class NeemaColors(
    val bg: Color, val bg2: Color, val bg3: Color, val bg4: Color,
    val border: Color, val border2: Color,
    val gold: Color, val gold2: Color, val goldDim: Color,
    val text: Color, val textDim: Color, val textMid: Color,
    val green: Color, val greenDim: Color,
    val red: Color, val redDim: Color,
    val blue: Color, val blueDim: Color,
    val amber: Color, val amberDim: Color,
    val indigo: Color, val indigoDim: Color,
    /** The dashboard shell (`#f7f8f5` surface, `#e8ebe3` hairlines, `#8a9e80` muted). */
    val surface: Color, val hairline: Color, val muted: Color,
    val isDark: Boolean,
)

val LightNeema = NeemaColors(
    bg = Color(0xFFF3F9EC), bg2 = Color(0xFFFFFFFF), bg3 = Color(0xFFE6F3D8), bg4 = Color(0xFFCEE6B2),
    border = Color(0xFFB5DA8B), border2 = Color(0xFF9CCD65),
    gold = Color(0xFF589B31), gold2 = Color(0xFF427425), goldDim = Color(0x1A589B31),
    text = Color(0xFF16270C), textDim = Color(0xFF699A32), textMid = Color(0xFF4F7425),
    green = Color(0xFF589B31), greenDim = Color(0x1A589B31),
    red = Color(0xFFC0392B), redDim = Color(0x1AC0392B),
    blue = Color(0xFF2A48A2), blueDim = Color(0x1A2A48A2),
    amber = Color(0xFFBCC13E), amberDim = Color(0x1FBCC13E),
    indigo = Color(0xFF3D528F), indigoDim = Color(0x1A3D528F),
    surface = Color(0xFFF7F8F5), hairline = Color(0xFFE8EBE3), muted = Color(0xFF8A9E80),
    isDark = false,
)

val DarkNeema = NeemaColors(
    bg = Color(0xFF070D1C), bg2 = Color(0xFF0A1229), bg3 = Color(0xFF0B0E19), bg4 = Color(0xFF0F1424),
    border = Color(0xFF152451), border2 = Color(0xFF1F367A),
    gold = Color(0xFF84C13E), gold2 = Color(0xFF9CCD65), goldDim = Color(0x1F84C13E),
    text = Color(0xFFF3F9EC), textDim = Color(0xFF699A32), textMid = Color(0xFFB5DA8B),
    green = Color(0xFF84C13E), greenDim = Color(0x1F84C13E),
    red = Color(0xFFE05555), redDim = Color(0x1FE05555),
    blue = Color(0xFF5D7BD5), blueDim = Color(0x1F5D7BD5),
    amber = Color(0xFFD7DA8B), amberDim = Color(0x1FD7DA8B),
    indigo = Color(0xFF7085C2), indigoDim = Color(0x1A7085C2),
    surface = Color(0xFF070D1C), hairline = Color(0xFF152451), muted = Color(0xFF8A9E80),
    isDark = true,
)

val LocalNeemaColors = staticCompositionLocalOf { LightNeema }

object Neema {
    val colors: NeemaColors @Composable get() = LocalNeemaColors.current
    /** Success / warning / error / info looks for the current theme. */
    val tones: NeemaTones @Composable get() = if (LocalNeemaColors.current.isDark) DarkTones else LightTones
    /** The phone header / bottom bar / panel inks for the current theme. */
    val chrome: NeemaChrome @Composable get() = if (LocalNeemaColors.current.isDark) DarkChrome else LightChrome
}

/**
 * The shell's fixed brand colours (components/ui/Sidebar.tsx): a navy sidebar
 * with amber for the logo, the active item and badges — the same in light and
 * dark, exactly as on the web.
 */
object Brand {
    val Navy = Color(0xFF0E1729)
    val NavyBorder = Color(0xFF1E2A44)
    val NavyHover = Color(0xFF1B2740)
    val Amber = Color(0xFFF59E0B)
    val TextLight = Color(0xFFF8FAFC)
    val TextMuted = Color(0xFF94A3B8)
    val Online = Color(0xFF22C55E)
    val Moss = Color(0xFF589B31)
    /** Amber for text / glyphs on a light surface (amber-700, 5:1 on white; #f59e0b is 2.1:1). */
    val AmberInk = Color(0xFFB45309)
}

/**
 * Every literal colour the web writes inline (Tailwind classes such as
 * `text-stone-500`, and the shell's hand-picked sage greys), named once so
 * a screen can say `Palette.Stone500` where the web wrote `text-stone-500`
 * instead of repeating `Color(0xFF78716C)`. Prefer [Neema.colors] (the CSS
 * variables, which flip for dark mode) and [Neema.tones] / [Neema.chrome]
 * first; reach for these only where the web itself hard-codes a colour.
 */
object Palette {
    // Neema's own ramps (globals.css)
    val Moss50 = Color(0xFFF0F9EC); val Moss100 = Color(0xFFE2F3D8); val Moss200 = Color(0xFFC5E7B1)
    val Moss600 = Color(0xFF589B31); val Moss700 = Color(0xFF427425); val Moss800 = Color(0xFF2C4E18); val Moss900 = Color(0xFF16270C)
    val Willow50 = Color(0xFFF3F9EC); val Willow100 = Color(0xFFE6F3D8); val Willow200 = Color(0xFFCEE6B2); val Willow300 = Color(0xFFB5DA8B)
    val Willow400 = Color(0xFF9CCD65); val Willow500 = Color(0xFF84C13E); val Willow600 = Color(0xFF699A32); val Willow700 = Color(0xFF4F7425)
    val Prussian400 = Color(0xFF5D7BD5); val Prussian700 = Color(0xFF1F367A); val Prussian800 = Color(0xFF152451)
    val Prussian850 = Color(0xFF0F1A38); val Prussian900 = Color(0xFF0A1229); val Prussian950 = Color(0xFF070D1C)
    /** `#7a8fa8` — secondary ink on the Prussian night surfaces (5.6:1 on `#0a1229`). */
    val NightMuted = Color(0xFF7A8FA8)
    val Indigo500 = Color(0xFF4D66B3); val Indigo900 = Color(0xFF0F1424)

    // The dashboard shell's sage neutrals (Sidebar.tsx, Notifications.tsx)
    /** Body ink of the shell (`#1c2917`). */
    val Ink = Color(0xFF1C2917)
    /** `#6b7e64` — secondary ink that still clears 4.3:1 on white. */
    val Sage500 = Color(0xFF6B7E64)
    /** `#8a9e80` — the shell's muted grey-green (decorative on white: 2.9:1). */
    val Sage400 = Color(0xFF8A9E80)
    val Sage300 = Color(0xFFB5C9A8); val Sage200 = Color(0xFFDDE4D6)
    val Parchment = Color(0xFFF7F8F5); val Mist = Color(0xFFF5F7F2); val Leaf = Color(0xFFF0F4EC)
    /** components/ui/Avatar.tsx: the stone-green disc, its dark-green initials and ring. */
    val AvatarDisc = Color(0xFFF5F6F3); val AvatarInk = Color(0xFF3A5C28); val AvatarRing = Color(0xFFDDE8D5)
    val Hairline = Color(0xFFE8EBE3); val Hairline2 = Color(0xFFEDF0EA)
    /** The unread-row wash of the bell panel. */
    val SproutTint = Color(0xFFFAFEF7)

    // Tailwind neutrals
    val Stone50 = Color(0xFFFAFAF9); val Stone100 = Color(0xFFF5F5F4); val Stone200 = Color(0xFFE7E5E4); val Stone300 = Color(0xFFD6D3D1)
    val Stone400 = Color(0xFFA8A29E); val Stone500 = Color(0xFF78716C); val Stone600 = Color(0xFF57534E); val Stone900 = Color(0xFF1C1917)
    val Gray100 = Color(0xFFF3F4F6); val Gray200 = Color(0xFFE5E7EB); val Gray300 = Color(0xFFD1D5DB); val Gray400 = Color(0xFF9CA3AF)
    val Gray500 = Color(0xFF6B7280); val Gray600 = Color(0xFF4B5563); val Gray700 = Color(0xFF374151); val Gray900 = Color(0xFF111827)
    val Slate50 = Color(0xFFF8FAFC); val Slate400 = Color(0xFF94A3B8); val Slate500 = Color(0xFF64748B)
    /** Tailwind v1 greys, as Sidebar.tsx writes them (`#4a5568`, `#718096`, `#a0aec0`). */
    val Pewter700 = Color(0xFF4A5568); val Pewter600 = Color(0xFF718096); val Pewter500 = Color(0xFFA0AEC0)

    // Tailwind hues
    val AmberTint = Color(0xFFFEF9EC); val Amber50 = Color(0xFFFFFBEB); val Amber100 = Color(0xFFFEF3C7); val Amber200 = Color(0xFFFDE68A); val Amber300 = Color(0xFFFCD34D)
    val Amber400 = Color(0xFFFBBF24); val Amber500 = Color(0xFFF59E0B); val Amber600 = Color(0xFFD97706); val Amber700 = Color(0xFFB45309)
    val Amber800 = Color(0xFF92400E); val Amber900 = Color(0xFF78350F)
    val Red50 = Color(0xFFFEF2F2); val Red100 = Color(0xFFFEE2E2); val Red200 = Color(0xFFFECACA); val Red300 = Color(0xFFFCA5A5)
    val Red400 = Color(0xFFF87171); val Red500 = Color(0xFFEF4444); val Red600 = Color(0xFFDC2626); val Red700 = Color(0xFFB91C1C); val Red800 = Color(0xFF991B1B)
    val Emerald50 = Color(0xFFECFDF5); val Emerald200 = Color(0xFFA7F3D0); val Emerald300 = Color(0xFF6EE7B7); val Emerald500 = Color(0xFF10B981)
    val Emerald600 = Color(0xFF059669); val Emerald700 = Color(0xFF047857); val Emerald800 = Color(0xFF065F46)
    val Green50 = Color(0xFFF0FDF4); val Emerald400 = Color(0xFF34D399); val Green500 = Color(0xFF22C55E); val Green600 = Color(0xFF16A34A)
    val Blue50 = Color(0xFFEFF6FF); val Blue200 = Color(0xFFBFDBFE); val Blue400 = Color(0xFF60A5FA); val Blue500 = Color(0xFF3B82F6)
    val Blue600 = Color(0xFF2563EB); val Blue700 = Color(0xFF1D4ED8)
    val Violet50 = Color(0xFFF5F3FF); val Violet200 = Color(0xFFDDD6FE); val Violet600 = Color(0xFF7C3AED)
}

/**
 * A status look — the web's tinted callouts (toasts, banners, inline
 * errors): a pale fill, a hairline, readable text, and a solid accent for
 * the dot / icon badge. Light and dark variants clear 4.5:1 for the text.
 */
@Immutable
data class Tone(val bg: Color, val border: Color, val text: Color, val accent: Color)

@Immutable
data class NeemaTones(
    val success: Tone, val warning: Tone, val error: Tone, val info: Tone,
    /** Neema's own moss "all good" look (the "Back online" bar). */
    val moss: Tone,
)

private val LightTones = NeemaTones(
    success = Tone(Palette.Emerald50, Palette.Emerald200, Palette.Emerald700, Palette.Emerald500),
    warning = Tone(Palette.Amber50, Palette.Amber200, Palette.Amber700, Palette.Amber500),
    error = Tone(Palette.Red50, Palette.Red200, Palette.Red700, Palette.Red500),
    info = Tone(Palette.Blue50, Palette.Blue200, Palette.Blue700, Palette.Blue500),
    moss = Tone(Color(0xFFF1F8EB), Color(0xFFCDE5BB), Color(0xFF3F7A22), Palette.Moss600),
)

private val DarkTones = NeemaTones(
    success = Tone(Color(0xCC022C22), Palette.Emerald800, Palette.Emerald300, Palette.Emerald500),
    warning = Tone(Color(0xCC451A03), Palette.Amber800, Palette.Amber300, Palette.Amber500),
    error = Tone(Color(0xCC450A0A), Palette.Red800, Palette.Red300, Palette.Red500),
    info = Tone(Color(0xCC172554), Palette.Blue700, Palette.Blue200, Palette.Blue500),
    moss = Tone(Color(0xFF12230B), Color(0xFF2F5A1A), Palette.Willow400, Palette.Moss600),
)

/**
 * The phone chrome around every view (MobileNav.tsx's header and bottom
 * bar, the bell's panel): white by day, the Prussian surface by night.
 * Icon and label inks are the Neema sage, darkened from the web's
 * gray-400 so they clear 3:1 (icons) and 4.5:1 (labels).
 */
@Immutable
data class NeemaChrome(
    val bar: Color, val barLine: Color,
    /** "Neema" in the header. */
    val title: Color,
    /** The view name after the dot, and inactive tab labels / icons. */
    val subtitle: Color,
    val icon: Color,
    /** The active tab: amber ink by day (readable on white), amber by night. */
    val active: Color,
    val separator: Color,
)

private val LightChrome = NeemaChrome(
    bar = Color.White, barLine = Palette.Gray100, title = Palette.Gray900, subtitle = Palette.Sage500,
    icon = Palette.Sage500, active = Brand.AmberInk, separator = Palette.Gray300,
)

private val DarkChrome = NeemaChrome(
    bar = Palette.Prussian900, barLine = Palette.Prussian800, title = Color.White, subtitle = Palette.Gray400,
    icon = Palette.Gray400, active = Brand.Amber, separator = Palette.Gray600,
)

/**
 * White or ink for text on [bg], a colour chosen at run time (a role's, a
 * tag's): ink only where white fails 4.5:1 and ink passes it (amber, lime,
 * sky, pale hues); white otherwise, as the web prints it.
 */
fun contentOn(bg: Color, ink: Color = Palette.Ink): Color {
    val l = bg.luminance()
    val onWhite = 1.05f / (l + 0.05f)
    val onInk = (l + 0.05f) / (ink.luminance() + 0.05f)
    return if (onWhite < 4.5f && onInk >= 4.5f) ink else Color.White
}

/**
 * Manrope, the web's UI sans (globals.css `--font-sans`, loaded at 400–800 in
 * layout.tsx), bundled as static instances of the OFL variable font
 * (assets/licenses/Manrope-OFL.txt). Every text style in the theme uses it,
 * so any `Text` that takes its style from the theme is in Manrope; a raw
 * `TextStyle(...)` handed to `style =` / `textStyle =` must name it (or merge
 * onto `LocalTextStyle.current`), or it falls back to the system sans.
 */
val NeemaFont: FontFamily = FontFamily(
    Font(R.font.manrope_regular, FontWeight.Normal),
    Font(R.font.manrope_medium, FontWeight.Medium),
    Font(R.font.manrope_semibold, FontWeight.SemiBold),
    Font(R.font.manrope_bold, FontWeight.Bold),
    Font(R.font.manrope_extrabold, FontWeight.ExtraBold),
)

/** Tabular (monospaced) figures, for amounts and counts that line up in columns. */
val TabularNums = TextStyle(fontFamily = NeemaFont, fontFeatureSettings = "tnum")

/**
 * This text size, grown with the system font scale only up to [maxScale].
 * For dense chrome that must stay inside a fixed bar (tab labels, count
 * badges); body text should always scale freely.
 */
@Composable
fun TextUnit.scaledAtMost(maxScale: Float): TextUnit {
    val fs = LocalDensity.current.fontScale
    return if (fs <= maxScale) this else (value * maxScale / fs).sp
}

/** A text size that ignores the font scale — for an emoji or glyph drawn inside a fixed-size tile. */
@Composable
fun Dp.asFixedSp(): TextUnit = with(LocalDensity.current) { this@asFixedSp.toSp() }

/** Brand channel colours (lib/channels.tsx). */
object ChannelColors {
    val WhatsApp = Color(0xFF25D366)
    val Messenger = Color(0xFF0084FF)
    val Facebook = Color(0xFF1877F2)
    val Instagram = Color(0xFFE1306C)
    val TikTok = Color(0xFF010101)
    val Email = Color(0xFF6366F1)
    val Sms = Color(0xFF64748B)
    val Web = Color(0xFF589B31)
}

private val NeemaType = Typography(
    headlineSmall = TextStyle(fontFamily = NeemaFont, fontWeight = FontWeight.ExtraBold, fontSize = 22.sp),
    titleLarge = TextStyle(fontFamily = NeemaFont, fontWeight = FontWeight.Bold, fontSize = 20.sp),
    titleMedium = TextStyle(fontFamily = NeemaFont, fontWeight = FontWeight.Bold, fontSize = 16.sp),
    titleSmall = TextStyle(fontFamily = NeemaFont, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
    bodyLarge = TextStyle(fontFamily = NeemaFont, fontSize = 15.sp, lineHeight = 21.sp),
    bodyMedium = TextStyle(fontFamily = NeemaFont, fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontFamily = NeemaFont, fontSize = 12.sp, lineHeight = 16.sp),
    labelLarge = TextStyle(fontFamily = NeemaFont, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
    labelMedium = TextStyle(fontFamily = NeemaFont, fontWeight = FontWeight.SemiBold, fontSize = 12.sp),
    labelSmall = TextStyle(fontFamily = NeemaFont, fontWeight = FontWeight.SemiBold, fontSize = 11.sp),
    // The M3 styles the theme doesn't restate still get the family.
    displayLarge = Typography().displayLarge.copy(fontFamily = NeemaFont),
    displayMedium = Typography().displayMedium.copy(fontFamily = NeemaFont),
    displaySmall = Typography().displaySmall.copy(fontFamily = NeemaFont),
    headlineLarge = Typography().headlineLarge.copy(fontFamily = NeemaFont),
    headlineMedium = Typography().headlineMedium.copy(fontFamily = NeemaFont),
)

@Composable
fun NeemaTheme(dark: Boolean, content: @Composable () -> Unit) {
    val c = if (dark) DarkNeema else LightNeema
    // Dialogs (surfaceContainerHigh) and sheets (surfaceContainerLow) sit on
    // var(--bg2) like ui.tsx's Modal: white by day, prussian-900 by night.
    val scheme = if (dark) darkColorScheme(
        primary = c.gold, onPrimary = c.bg, primaryContainer = c.goldDim, onPrimaryContainer = c.gold2,
        secondary = c.blue, onSecondary = Color.White,
        tertiary = Brand.Amber, onTertiary = Color.White,
        background = c.bg, onBackground = c.text, surface = c.bg2, onSurface = c.text,
        surfaceVariant = c.bg4, onSurfaceVariant = c.textMid, surfaceContainer = c.bg2,
        surfaceContainerHigh = c.bg2, surfaceContainerLow = c.bg2, surfaceContainerHighest = c.border,
        outline = c.border2, outlineVariant = c.border, error = c.red, onError = Color.White,
    ) else lightColorScheme(
        primary = c.gold, onPrimary = Color.White, primaryContainer = c.bg3, onPrimaryContainer = c.gold2,
        secondary = c.blue, onSecondary = Color.White,
        tertiary = Brand.Amber, onTertiary = Color.White,
        background = c.surface, onBackground = c.text, surface = c.bg2, onSurface = c.text,
        surfaceVariant = c.bg3, onSurfaceVariant = c.textMid, surfaceContainer = Color.White,
        surfaceContainerHigh = c.bg2, surfaceContainerLow = c.bg2, surfaceContainerHighest = c.bg3,
        outline = c.border, outlineVariant = c.hairline, error = c.red, onError = Color.White,
    )
    CompositionLocalProvider(LocalNeemaColors provides c) {
        MaterialTheme(colorScheme = scheme, typography = NeemaType, content = content)
    }
}
