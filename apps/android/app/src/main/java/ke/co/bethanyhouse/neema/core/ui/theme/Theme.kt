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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

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
}

/** Brand channel colours (lib/channels.tsx). */
object ChannelColors {
    val WhatsApp = Color(0xFF25D366)
    val Messenger = Color(0xFF0084FF)
    val Facebook = Color(0xFF1877F2)
    val Instagram = Color(0xFFE1306C)
    val TikTok = Color(0xFF010101)
    val Email = Color(0xFF6366F1)
    val Sms = Color(0xFF64748B)
}

private val NeemaType = Typography(
    headlineSmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.ExtraBold, fontSize = 22.sp),
    titleLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 20.sp),
    titleMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 16.sp),
    titleSmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
    bodyLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 15.sp, lineHeight = 21.sp),
    bodyMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 12.sp, lineHeight = 16.sp),
    labelLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
    labelMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 12.sp),
    labelSmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 11.sp),
)

@Composable
fun NeemaTheme(dark: Boolean, content: @Composable () -> Unit) {
    val c = if (dark) DarkNeema else LightNeema
    val scheme = if (dark) darkColorScheme(
        primary = c.gold, onPrimary = Color(0xFF04220F), primaryContainer = c.goldDim, onPrimaryContainer = c.gold2,
        secondary = c.blue, onSecondary = Color.White,
        background = c.bg, onBackground = c.text, surface = c.bg2, onSurface = c.text,
        surfaceVariant = c.bg4, onSurfaceVariant = c.textMid, surfaceContainer = c.bg2,
        surfaceContainerHigh = c.bg4, surfaceContainerLow = c.bg3, surfaceContainerHighest = c.border,
        outline = c.border2, outlineVariant = c.border, error = c.red, onError = Color.White,
    ) else lightColorScheme(
        primary = c.gold, onPrimary = Color.White, primaryContainer = c.bg3, onPrimaryContainer = c.gold2,
        secondary = c.blue, onSecondary = Color.White,
        background = c.surface, onBackground = c.text, surface = c.bg2, onSurface = c.text,
        surfaceVariant = c.bg3, onSurfaceVariant = c.textMid, surfaceContainer = Color.White,
        surfaceContainerHigh = Color(0xFFF1F5EC), surfaceContainerLow = c.surface, surfaceContainerHighest = c.bg3,
        outline = c.border, outlineVariant = c.hairline, error = c.red, onError = Color.White,
    )
    CompositionLocalProvider(LocalNeemaColors provides c) {
        MaterialTheme(colorScheme = scheme, typography = NeemaType, content = content)
    }
}
