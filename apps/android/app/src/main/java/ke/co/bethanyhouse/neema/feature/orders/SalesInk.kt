package ke.co.bethanyhouse.neema.feature.orders

import androidx.compose.ui.graphics.Color

/**
 * The sales views' literal colours that core's `Palette` does not name yet —
 * Tailwind hues the Orders / Leads / Deals views use (sky, green, violet,
 * orange, yellow, slate) and the handful of hex values DealsView.tsx and
 * OrdersView.tsx write inline. Every value is the web's own; everything the
 * core palette already names is taken from there (`Palette.*`,
 * `ChannelColors.*`). Kept in this one file so the screens carry no raw
 * `Color(0x…)`, and so core can adopt them wholesale.
 */
internal object SalesInk {
    // Tailwind hues missing from Palette.
    val Sky50 = Color(0xFFF0F9FF); val Sky200 = Color(0xFFBAE6FD); val Sky400 = Color(0xFF38BDF8); val Sky700 = Color(0xFF0369A1)
    val Green200 = Color(0xFFBBF7D0); val Green400 = Color(0xFF4ADE80); val Green700 = Color(0xFF15803D)
    val Violet500 = Color(0xFF8B5CF6); val Violet700 = Color(0xFF6D28D9)
    val Orange50 = Color(0xFFFFF7ED); val Orange200 = Color(0xFFFED7AA); val Orange500 = Color(0xFFF97316); val Orange700 = Color(0xFFC2410C)
    val Yellow50 = Color(0xFFFEFCE8); val Yellow200 = Color(0xFFFEF08A); val Yellow500 = Color(0xFFEAB308); val Yellow700 = Color(0xFFA16207)
    val Slate600 = Color(0xFF475569); val Slate800 = Color(0xFF1E293B)
    val Red950 = Color(0xFF450A0A)

    /** OrdersView / LeadsView `CH_BG.messenger` (lib/channels.tsx, and so `ChannelColors`, use #0084ff). */
    val Messenger = Color(0xFF0099FF)

    /** LeadsView's `#igGrad`, bottom-left → top-right. */
    val InstagramGradient = arrayOf(
        0f to Color(0xFFF09433), 0.25f to Color(0xFFE6683C), 0.5f to Color(0xFFDC2743),
        0.75f to Color(0xFFCC2366), 1f to Color(0xFFBC1888),
    )

    // DealsView.tsx inline hex.
    /** The page (`bg-[#f6f7f2]`), a shade off the shell's parchment. */
    val DealsPage = Color(0xFFF6F7F2)
    /** A queue row that needs approval: fill and hairline. */
    val NeedsBg = Color(0xFFFDF6E9); val NeedsBorder = Color(0xFFF0DDB0)
    /** A scheduled queue row: fill and hairline. */
    val QueuedBg = Color(0xFFF8FAF6); val QueuedBorder = Color(0xFFE8EDE4)
    /** The deal card's "Won" button. */
    val WonBg = Color(0xFFE9F6DF)

    // OrdersView.tsx inline hex.
    /** "Open in hub ↗" (`border-[#cfe3bd]`). */
    val HubLinkBorder = Color(0xFFCFE3BD)
    /** Android only: the order open in the wide tablet's side pane. */
    val PaneHighlight = Color(0xFFF7FBF2)
}
