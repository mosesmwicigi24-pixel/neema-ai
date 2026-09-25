package ke.co.bethanyhouse.neema.feature.orders

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.Box
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import java.util.Locale

/**
 * A Tailwind-style tone (text / tint / border / dot) — the web's
 * `text-amber-700 bg-amber-50 border-amber-200` badges. In dark mode the pale
 * tint would glare, so [Badge] swaps it for a translucent wash of the text colour.
 */
data class Tone(val text: Color, val bg: Color, val border: Color, val dot: Color)

object Tones {
    val Amber = Tone(Color(0xFFB45309), Color(0xFFFFFBEB), Color(0xFFFDE68A), Color(0xFFFBBF24))
    val Blue = Tone(Color(0xFF1D4ED8), Color(0xFFEFF6FF), Color(0xFFBFDBFE), Color(0xFF60A5FA))
    val Emerald = Tone(Color(0xFF047857), Color(0xFFECFDF5), Color(0xFFA7F3D0), Color(0xFF34D399))
    val Red = Tone(Color(0xFFB91C1C), Color(0xFFFEF2F2), Color(0xFFFECACA), Color(0xFFF87171))
    val Sky = Tone(Color(0xFF0369A1), Color(0xFFF0F9FF), Color(0xFFBAE6FD), Color(0xFF38BDF8))
    val Green = Tone(Color(0xFF15803D), Color(0xFFF0FDF4), Color(0xFFBBF7D0), Color(0xFF4ADE80))
}

/** Our own triage statuses, in the web's order (OrderStatus). */
val ORDER_STATUSES = listOf("pending", "confirmed", "delivered", "cancelled")

data class StatusMeta(val label: String, val tone: Tone)

/** STATUS_META */
val STATUS_META: Map<String, StatusMeta> = mapOf(
    "pending" to StatusMeta("Pending", Tones.Amber),
    "confirmed" to StatusMeta("Confirmed", Tones.Blue),
    "delivered" to StatusMeta("Delivered", Tones.Emerald),
    "cancelled" to StatusMeta("Cancelled", Tones.Red),
)

/** STATUS_ACTIONS — the moves open from each status. */
val STATUS_ACTIONS: Map<String, List<String>> = mapOf(
    "pending" to listOf("confirmed", "cancelled"),
    "confirmed" to listOf("delivered", "cancelled"),
    "delivered" to emptyList(),
    "cancelled" to emptyList(),
)

fun statusMeta(status: String): StatusMeta = STATUS_META[status] ?: STATUS_META.getValue("pending")

/** Where the hub lives, for "Open in hub" links (NEXT_PUBLIC_HUB_URL's default). */
const val HUB_URL = "https://hub.bethanyhouse.co.ke"

/**
 * The link into the hub for one order: /handoff/orders/{id}, carrying the
 * order's public token in the URL FRAGMENT — a fragment never reaches a server
 * or a log, so a colleague with a hub login lands on the admin page and one
 * without lands on the customer's view of the same order.
 *
 * Null when the order was never pushed: a link to a hub order that does not
 * exist is worse than no link.
 */
fun hubOrderHref(order: Order): String? {
    val id = order.hubOrderId ?: return null
    val base = "${HUB_URL.trimEnd('/')}/handoff/orders/$id"
    return order.hubPublicToken?.takeIf { it.isNotBlank() }?.let { "$base#v=$it" } ?: base
}

/** The hub's own word for this order's state — "Completed" when it is done. */
fun hubMeta(order: Order): StatusMeta? {
    val s = order.hubStatus.orEmpty().lowercase(Locale.ROOT)
    if (order.hubOrderId == null || s.isEmpty()) return null
    return when (s) {
        "confirmed", "processing" -> StatusMeta("Confirmed", Tones.Amber)
        "shipped" -> StatusMeta("Shipped", Tones.Sky)
        "delivered", "completed" -> StatusMeta("Completed", Tones.Green)
        "cancelled", "voided" -> StatusMeta("Cancelled", Tones.Red)
        else -> null
    }
}

/** The order's money: `o.total || o.subtotal`. */
val Order.amount: Double get() = if (total != 0.0) total else subtotal

@Composable
fun toneBg(t: Tone): Color = if (Neema.colors.isDark) t.dot.copy(alpha = 0.14f) else t.bg

@Composable
fun toneBorder(t: Tone): Color = if (Neema.colors.isDark) t.dot.copy(alpha = 0.35f) else t.border

@Composable
fun toneText(t: Tone): Color = if (Neema.colors.isDark) t.dot else t.text

/** A small bordered status badge (the list's `text-[10px] rounded border` chips). */
@Composable
fun Badge(text: String, tone: Tone, modifier: Modifier = Modifier, fontSize: Int = 10) {
    Text(
        text,
        modifier = modifier
            .clip(RoundedCornerShape(4.dp))
            .background(toneBg(tone))
            .border(1.dp, toneBorder(tone), RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
        color = toneText(tone), fontSize = fontSize.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
    )
}

/** CH_BG — the orders list's flat channel colours. */
private val CH_BG = mapOf(
    "whatsapp" to Color(0xFF25D366),
    "messenger" to Color(0xFF0099FF),
    "instagram" to Color(0xFFE1306C),
    "facebook" to Color(0xFF1877F2),
    "email" to Color(0xFF4D66B3),
    "sms" to Color(0xFF589B31),
)

/** ChannelPill — a solid pill with the channel's name, white on brand colour. */
@Composable
fun OrderChannelPill(channel: String?) {
    val ch = (channel?.ifBlank { null } ?: "whatsapp").lowercase(Locale.ROOT)
    val bg = CH_BG[ch] ?: Color(0xFF699A32)
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(bg).padding(horizontal = 6.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(5.dp).clip(CircleShape).background(Color.White))
        Spacer(Modifier.width(4.dp))
        Text(ch.replaceFirstChar { it.titlecase(Locale.ROOT) }, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Medium)
    }
}
