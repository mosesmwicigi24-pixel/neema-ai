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

    // Tailwind shades and inbox literals (ConversationsView, CustomerSidebar) — was feature/conversations Hue
    val Sky100 = Color(0xFFE0F2FE); val Sky200 = Color(0xFFBAE6FD); val Sky300 = Color(0xFF7DD3FC)
    val Sky400 = Color(0xFF38BDF8); val Sky700 = Color(0xFF0369A1); val Violet100 = Color(0xFFEDE9FE)
    val Violet500 = Color(0xFF8B5CF6); val Violet700 = Color(0xFF6D28D9); val Purple100 = Color(0xFFF3E8FF)
    val Purple300 = Color(0xFFD8B4FE); val Indigo50 = Color(0xFFEEF2FF); val Indigo100 = Color(0xFFE0E7FF)
    val Indigo200 = Color(0xFFC7D2FE); val Indigo300 = Color(0xFFA5B4FC); val Indigo700 = Color(0xFF4338CA)
    val Blue100 = Color(0xFFDBEAFE); val Blue300 = Color(0xFF93C5FD); val Blue800 = Color(0xFF1E40AF)
    val Blue950 = Color(0xFF172554); val Green100 = Color(0xFFDCFCE7); val Green200 = Color(0xFFBBF7D0)
    val Green300 = Color(0xFF86EFAC); val Green400 = Color(0xFF4ADE80); val Green700 = Color(0xFF15803D)
    val Emerald100 = Color(0xFFD1FAE5); val Emerald900 = Color(0xFF064E3B); val Teal100 = Color(0xFFCCFBF1)
    val Teal300 = Color(0xFF5EEAD4); val Lime50 = Color(0xFFF7FEE7); val Lime300 = Color(0xFFBEF264)
    val Lime800 = Color(0xFF3F6417); val Orange50 = Color(0xFFFFF7ED); val Orange100 = Color(0xFFFFEDD5)
    val Orange200 = Color(0xFFFED7AA); val Orange300 = Color(0xFFFDBA74); val Orange500 = Color(0xFFF97316)
    val Orange600 = Color(0xFFEA580C); val Orange700 = Color(0xFFC2410C); val Slate100 = Color(0xFFF1F5F9)
    val Slate600 = Color(0xFF475569); val Slate800 = Color(0xFF1E293B); val Gray800 = Color(0xFF1F2937)
    val Amber950 = Color(0xFF451A03); val Red950 = Color(0xFF450A0A); val BubbleGreen = Color(0xFF2AD113)
    val BubbleInk = Color(0xFF0A2E05); val LivePill = Color(0xFFFFF3CD); val LivePillInk = Color(0xFF856404)
    val ActiveRow = Color(0xFFFDF6E9); val UnreadEdge = Color(0xFFFCD98A); val PickedRow = Color(0xFFEEF6E5)
    val StoneGreen = Color(0xFFF5F6F3); val ForestInk = Color(0xFF3A5C28); val SageRing = Color(0xFFDDE8D5)
    val SagePale = Color(0xFFC5D5BC); val SageDeep = Color(0xFF3D5A30); val SageDetail = Color(0xFF8FA383)
    val SageCaption = Color(0xFF5F6F57); val SageRim = Color(0xFFCFDAC6); val SageDash = Color(0xFFC7CEC0)
    val SageField = Color(0xFFE5E8E2); val SageFieldBg = Color(0xFFF6F7F5); val SageRule = Color(0xFFF2F4EF)
    val SageQuote = Color(0xFFF2F7EE); val SageStrip = Color(0xFFFBFCFA); val SageBanner = Color(0xFFFAFBF8)
    val SageResult = Color(0xFFF8FAF6); val SageResultRim = Color(0xFFE8EDE4); val SageButton = Color(0xFFEEF2E8)
    val MossNight = Color(0xFF7FC25A); val MossBright = Color(0xFF86C95E); val MossWash = Color(0xFFE9F6DF)
    val MossRim = Color(0xFFD6E9C2); val MossTint = Color(0xFFF0F9E8); val ForestText = Color(0xFF1A2E0F)
    val CoolGray = Color(0xFFF1F3F5); val WhatsAppDeep = Color(0xFF1DA851); val MessengerSky = Color(0xFF0099FF)
    val InstaOrange = Color(0xFFF09433); val InstaCoral = Color(0xFFE6683C); val InstaRed = Color(0xFFDC2743)
    val InstaMagenta = Color(0xFFCC2366); val InstaPurple = Color(0xFFBC1888); val PipeGold = Color(0xFFC89B3C)
    val PipeGoldSolid = Color(0xFFA97C14); val PipeGoldInk = Color(0xFF8A6D1F); val PipeGoldWash = Color(0xFFFDF8EC)
    val PipeGoldRim = Color(0xFFE3CF9B); val PipeLost = Color(0xFFF4CCCC); val PipeLostIcon = Color(0xFFEFA3A3)
    val PipeLostText = Color(0xFFE08A8A)
    // Analytics / Catalog / Team / Profile / Settings literals — was feature/reports AreaPalette
    val Yellow50 = Color(0xFFFEFCE8); val Sky50 = Color(0xFFF0F9FF); val Rose50 = Color(0xFFFFF1F2)
    val Pink50 = Color(0xFFFDF2F8); val Teal50 = Color(0xFFF0FDFA); val Cyan50 = Color(0xFFECFEFF)
    val Purple50 = Color(0xFFFAF5FF); val Purple200 = Color(0xFFE9D5FF); val Purple500 = Color(0xFFA855F7)
    val Purple700 = Color(0xFF7E22CE); val SproutWash = Color(0xFFEAF5DD); val DangerWash = Color(0xFFFFF5F5)
    val PipeChipFill = Color(0xFFFDF8EC); val PipeChipLine = Color(0xFFE3CF9B); val PipeChipInk = Color(0xFF8A6D1F)
    val MessengerTile = Color(0xFF0099FF); val MpesaGreen = Color(0xFF00A651); val SlackAubergine = Color(0xFF4A154B)
    val SheetsGreen = Color(0xFF0F9D58)
    // Orders / Leads / Deals literals — was feature/orders SalesInk (Messenger here is CH_BG's #0099ff, not ChannelColors')
    val Yellow200 = Color(0xFFFEF08A); val Yellow500 = Color(0xFFEAB308); val Yellow700 = Color(0xFFA16207)
    val Messenger = Color(0xFF0099FF); val DealsPage = Color(0xFFF6F7F2); val NeedsBg = Color(0xFFFDF6E9)
    val NeedsBorder = Color(0xFFF0DDB0); val QueuedBg = Color(0xFFF8FAF6); val QueuedBorder = Color(0xFFE8EDE4)
    val WonBg = Color(0xFFE9F6DF); val HubLinkBorder = Color(0xFFCFE3BD); val PaneHighlight = Color(0xFFF7FBF2)

    /** Instagram's gradient, first stop to last (SettingsView's tile). */
    val InstagramGradient = listOf(
        Color(0xFFF09433), Color(0xFFE6683C), Color(0xFFDC2743), Color(0xFFCC2366), Color(0xFFBC1888),
    )
    /** LeadsView's `#igGrad`, bottom-left → top-right, as brush stops. */
    val InstagramGradientStops = arrayOf(
        0f to Color(0xFFF09433), 0.25f to Color(0xFFE6683C), 0.5f to Color(0xFFDC2743),
        0.75f to Color(0xFFCC2366), 1f to Color(0xFFBC1888),
    )

    /**
     * The call screens' own colours (was feature/calls CallInk): CallsView.tsx
     * and CallStage.tsx style themselves inline with a WhatsApp-dark palette
     * that is neither Tailwind nor Neema's. Translucent variants are these at
     * the web's rgba() alpha; WhatsApp green itself is `ChannelColors.WhatsApp`.
     */
    object Call {
        // CallsView.tsx — the call-log console.
        val Green = Color(0xFF2AD17F)
        val Red = Color(0xFFF2555A)
        val Amber = Color(0xFFF5A623)
        val Muted = Color(0xFF7F9B8B)
        val Dim = Color(0xFF6B8577)
        val Text = Color(0xFFE9EDEF)
        val Soft = Color(0xFFCFE9D9)
        val Sage = Color(0xFF9FB3A8)
        /** The console card's night fill (and the ink on its green buttons). */
        val Ink = Color(0xFF0B1410)
        /** The glow at the top of the console card's radial gradient. */
        val Glow = Color(0xFF123626)
        /** "Transcribing…", the readiness bell. */
        val Gold = Color(0xFFF5C451)
        /** The missed-count badge's text. */
        val MissedText = Color(0xFFFF8A8D)
        /** `avatarColor`'s six discs. */
        val Avatars = listOf(
            Color(0xFF3B6EA5), Color(0xFFA5417D), Color(0xFFB5892F), Color(0xFF3C8C5A), Color(0xFF8A4FC4), Color(0xFFB24A4A),
        )

        // CallStage.tsx — the take-over call card.
        val StageSubText = Color(0xFF8AA89A)
        val StagePillText = Color(0xFFA8E6C4)
        val StageRed = Color(0xFFE24B4A)
        val StageAmber = Color(0xFFEF9F27)
        val StageLabel = Color(0xFF8696A0)
        val StageGlow = Color(0xFF0E5C3A)
        val StageInk = Color(0xFF06110B)
        /** The card's glass (`rgba(11,20,26,0.6)` at full strength). */
        val StageGlass = Color(0xFF0B141A)
        /** The initial on the green avatar disc. */
        val StageInitial = Color(0xFF04220F)
        /** Mute / speaker when off. */
        val StageControl = Color(0xFF1F2C33)
        /** "Call ended" / the callback note. */
        val StageEnded = Color(0xFFA8C7B6)
    }
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

/**
 * DM Mono, the web's `--font-mono` (globals.css; loaded at 400 and 500 in
 * layout.tsx), bundled from the OFL release (assets/licenses/DMMono-OFL.txt).
 * Use it wherever the web writes `font-mono` / `var(--font-mono)` — phone
 * numbers, SKUs, order refs, WhatsApp ```code``` — instead of
 * `FontFamily.Monospace`, which is the device's own (Droid Sans Mono or a
 * vendor font). Bold asks are served by the Medium cut, as the web's
 * browser does with only 400/500 loaded (a synthesised bold on top).
 */
val NeemaMono: FontFamily = FontFamily(
    Font(R.font.dm_mono_regular, FontWeight.Normal),
    Font(R.font.dm_mono_medium, FontWeight.Medium),
)

/** Monospaced text in DM Mono (`font-mono`): merge onto a style or pass as `style =`. */
val MonoText = TextStyle(fontFamily = NeemaMono)

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
