package ke.co.bethanyhouse.neema.core.ui.theme

import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/**
 * The dashboard's own outline icons (heroicons paths from
 * app/dashboard/page.tsx and the sidebar), so the app shows exactly the
 * shapes the web does. Stroked in the current content colour.
 */
object WebIcons {
    /**
     * SVG lets arc flags run together ("a2 2 0 012-2" = flags 0,1 then x=2);
     * Compose's parser doesn't, so re-emit every arc with explicit separators.
     */
    internal fun expandArcFlags(d: String): String {
        val out = StringBuilder()
        var i = 0
        var cmd = ' '
        var argIndex = 0
        fun skipSep() { while (i < d.length && (d[i] == ' ' || d[i] == ',')) i++ }
        fun readNumber(): String {
            val start = i
            if (i < d.length && (d[i] == '-' || d[i] == '+')) i++
            var seenDot = false
            while (i < d.length) {
                val ch = d[i]
                if (ch.isDigit()) i++
                else if (ch == '.' && !seenDot) { seenDot = true; i++ }
                else if ((ch == 'e' || ch == 'E') && i + 1 < d.length) {
                    i++; if (d[i] == '-' || d[i] == '+') i++
                } else break
            }
            return d.substring(start, i)
        }
        while (true) {
            skipSep()
            if (i >= d.length) break
            val ch = d[i]
            if (ch.isLetter()) { cmd = ch; argIndex = 0; out.append(ch).append(' '); i++; continue }
            val isArc = cmd == 'a' || cmd == 'A'
            val slot = argIndex % 7
            val token = if (isArc && (slot == 3 || slot == 4)) { i++; ch.toString() } else readNumber()
            out.append(token).append(' ')
            argIndex++
        }
        return out.toString().trim()
    }

    private fun icon(name: String, width: Float = 1.8f, vararg paths: String): ImageVector =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
            paths.forEach { d ->
                addPath(
                    pathData = addPathNodes(expandArcFlags(d)),
                    fill = null,
                    stroke = SolidColor(Color.Black),
                    strokeLineWidth = width,
                    strokeLineCap = StrokeCap.Round,
                    strokeLineJoin = StrokeJoin.Round,
                )
            }
        }.build()

    val Inbox = icon("inbox", 1.8f, "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z")
    val Logo = icon("logo", 2.5f, "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z")
    val Calls = icon("calls", 1.8f, "M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z")
    val Orders = icon("orders", 1.8f, "M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4")
    val Reports = icon("reports", 1.8f, "M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z")
    val Deals = icon("deals", 1.8f, "M13 10V3L4 14h7v7l9-11h-7z")
    val Leads = icon("leads", 1.8f, "M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9")
    val Analytics = icon("analytics", 1.8f, "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z")
    val Catalog = icon("catalog", 1.8f, "M4 6h16M4 10h16M4 14h16M4 18h16")
    val Team = icon("team", 1.8f, "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z")
    val Settings = icon("settings", 1.8f, "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z", "M15 12a3 3 0 11-6 0 3 3 0 016 0z")
    val Profile = icon("profile", 1.8f, "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z")
    val Bell = icon("bell", 2f, "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9")
    val Moon = icon("moon", 2f, "M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z")
    val Sun = icon("sun", 2f, "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z")
    val Collapse = icon("collapse", 2f, "M11 19l-7-7 7-7m8 14l-7-7 7-7")
    val Expand = icon("expand", 2f, "M13 5l7 7-7 7M5 5l7 7-7 7")
    val ChevronUp = icon("chevron_up", 2f, "M5 15l7-7 7 7")
    val Logout = icon("logout", 2f, "M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1")
    val More = icon("more", 2f, "M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z")
    val Menu = icon("menu", 2f, "M4 6h16M4 12h16M4 18h16")
}
