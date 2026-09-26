package ke.co.bethanyhouse.neema.feature.reports

import androidx.compose.ui.graphics.Color

/**
 * The few colours the web hard-codes in Analytics / Catalog / Team / Profile /
 * Settings that core's `Palette` doesn't name yet — each written ONCE, here,
 * by its web name, instead of inline `Color(0x…)` in the screens. Everything
 * else in these screens uses `Palette.*`, `Neema.colors` or `Neema.tones`.
 *
 * Pending a move into core/ui/theme `Palette` (same names): once there, these
 * become `Palette.X` and this file goes.
 */
internal object AreaPalette {
    // Tailwind hues Palette lacks (CatalogView's catColors -50 tints, the
    // chart's hover green-400, amber-950, ProfileView's purple admin badge).
    val Yellow50 = Color(0xFFFEFCE8)
    val Orange50 = Color(0xFFFFF7ED)
    val Sky50 = Color(0xFFF0F9FF)
    val Rose50 = Color(0xFFFFF1F2)
    val Pink50 = Color(0xFFFDF2F8)
    val Teal50 = Color(0xFFF0FDFA)
    val Cyan50 = Color(0xFFECFEFF)
    val Indigo50 = Color(0xFFEEF2FF)
    val Purple50 = Color(0xFFFAF5FF)
    val Purple100 = Color(0xFFF3E8FF)
    val Purple200 = Color(0xFFE9D5FF)
    val Purple300 = Color(0xFFD8B4FE)
    val Purple500 = Color(0xFFA855F7)
    val Purple700 = Color(0xFF7E22CE)
    val Green400 = Color(0xFF4ADE80)
    val Amber950 = Color(0xFF451A03)

    /** CatalogView's source banner fill, `bg-[#eaf5dd]`. */
    val SproutWash = Color(0xFFEAF5DD)
    /** The danger button / Disconnect fill, `#fff5f5` (AgentsView SBtn, SettingsView). */
    val DangerWash = Color(0xFFFFF5F5)

    // The pipeline's gold (CustomerSidebar.tsx PIPE_GOLD and its chips), which
    // Settings' custom-stage chips and Add button share.
    val PipeGold = Color(0xFFC89B3C)
    val PipeGoldSolid = Color(0xFFA97C14)
    val PipeChipFill = Color(0xFFFDF8EC)
    val PipeChipLine = Color(0xFFE3CF9B)
    val PipeChipInk = Color(0xFF8A6D1F)

    // SettingsView's integration tiles (the platforms' own brand colours).
    val MessengerTile = Color(0xFF0099FF)
    val MpesaGreen = Color(0xFF00A651)
    val SlackAubergine = Color(0xFF4A154B)
    val SheetsGreen = Color(0xFF0F9D58)
    /** Instagram's gradient, first stop to last. */
    val InstagramGradient = listOf(
        Color(0xFFF09433), Color(0xFFE6683C), Color(0xFFDC2743), Color(0xFFCC2366), Color(0xFFBC1888),
    )
}
