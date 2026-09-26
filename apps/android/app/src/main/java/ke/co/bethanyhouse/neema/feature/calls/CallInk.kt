package ke.co.bethanyhouse.neema.feature.calls

import androidx.compose.ui.graphics.Color

/**
 * The call screens' own colours: CallsView.tsx and CallStage.tsx style
 * themselves inline with a WhatsApp-dark palette that is not Tailwind and not
 * Neema's, so core's `Palette` has no names for them. Every value is the
 * web's literal; translucent variants are these at the web's rgba() alpha
 * (`CallInk.Red.copy(alpha = 0.16f)` is `rgba(242,85,90,0.16)` to the bit),
 * and WhatsApp green itself is `ChannelColors.WhatsApp`. Kept in this one file
 * so the screens carry no raw `Color(0x…)`, and so core can adopt them.
 */
internal object CallInk {
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
