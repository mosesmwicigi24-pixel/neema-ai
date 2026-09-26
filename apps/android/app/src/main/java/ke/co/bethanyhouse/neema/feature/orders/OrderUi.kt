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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.Icon
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.model.OrderItem
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import java.util.Locale

/**
 * A Tailwind-style tone (text / tint / border / dot) — the web's
 * `text-amber-700 bg-amber-50 border-amber-200` badges. In dark mode the pale
 * tint would glare, so [Badge] swaps it for a translucent wash of the text colour.
 */
data class Tone(val text: Color, val bg: Color, val border: Color, val dot: Color)

object Tones {
    val Amber = Tone(Palette.Amber700, Palette.Amber50, Palette.Amber200, Palette.Amber400)
    val Blue = Tone(Palette.Blue700, Palette.Blue50, Palette.Blue200, Palette.Blue400)
    val Emerald = Tone(Palette.Emerald700, Palette.Emerald50, Palette.Emerald200, Palette.Emerald400)
    val Red = Tone(Palette.Red700, Palette.Red50, Palette.Red200, Palette.Red400)
    val Sky = Tone(SalesInk.Sky700, SalesInk.Sky50, SalesInk.Sky200, SalesInk.Sky400)
    val Green = Tone(SalesInk.Green700, Palette.Green50, SalesInk.Green200, SalesInk.Green400)
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

/**
 * The phone line under an order's name, or null when it would only repeat
 * the name. The API sends no `contact_name` (admin.py `list_orders`), so the
 * name shown is the formatted phone itself and the web prints it twice; the
 * line appears only when a real name sits above it.
 */
fun phoneLine(order: Order, displayedName: String): String? =
    ke.co.bethanyhouse.neema.core.util.Fmt.formatPhone(order.waId).takeIf { it.isNotEmpty() && it != displayedName }

/**
 * OrdersView's `filtered`:the status filter, then a search over the name
 * (`contact_name ?? wa_id`), the phone and the id.
 */
fun filterOrders(orders: List<Order>, filter: String, search: String): List<Order> {
    val q = search.lowercase(Locale.ROOT)
    return orders.filter { o ->
        if (filter != "all" && o.status != filter) return@filter false
        if (q.isNotEmpty()) {
            o.customerName.lowercase(Locale.ROOT).contains(q) || o.waId.contains(q) || o.id.lowercase(Locale.ROOT).contains(q)
        } else true
    }
}

/** One page of [list] (1-based), without copying the rest of it. */
fun <T> pageOf(list: List<T>, page: Int, size: Int): List<T> {
    val from = ((page - 1) * size).coerceIn(0, list.size)
    return list.subList(from, minOf(from + size, list.size)).toList()
}

/** The header's and the status cards' figures, from one pass over the orders. */
@androidx.compose.runtime.Immutable
data class OrderStats(
    /** Orders per status (every one of [ORDER_STATUSES], zero included). */
    val counts: Map<String, Int>,
    /** Money per status (`o.total || o.subtotal`), for the card under each count. */
    val revenueBy: Map<String, Double>,
    /** "Total Revenue": everything but the cancelled. */
    val revenue: Double,
)

/**
 * OrdersView's `statusCounts`, per-status revenue and `totalRevenue` in a
 * single pass — the web filters the whole list once per status card on every
 * render, which a thousand orders make felt.
 */
fun orderStats(orders: List<Order>): OrderStats {
    val counts = HashMap<String, Int>()
    val money = HashMap<String, Double>()
    var revenue = 0.0
    for (o in orders) {
        counts[o.status] = (counts[o.status] ?: 0) + 1
        val a = o.amount
        money[o.status] = (money[o.status] ?: 0.0) + a
        if (o.status != "cancelled") revenue += a
    }
    return OrderStats(
        counts = ORDER_STATUSES.associateWith { counts[it] ?: 0 },
        revenueBy = ORDER_STATUSES.associateWith { money[it] ?: 0.0 },
        revenue = revenue,
    )
}

/**
 * How many status cards sit side by side: the web's four (`md:grid-cols-4`)
 * from 600dp, but only while each card still holds its label and a revenue
 * figure like "KES 1,284,750" whole at the user's font size — at 200% text on
 * an upright tablet four cards broke "Confirmed" across two lines, so it goes
 * two-up there. One column when even two can't fit the words.
 */
fun statusColumns(width: Dp, gutter: Dp, fontScale: Float): Int {
    val four = (width - gutter * 2 - 36.dp) / 4
    return when {
        width >= 600.dp && four >= 90.dp * fontScale + 28.dp -> 4
        width / fontScale < 240.dp -> 1
        else -> 2
    }
}

/** The pager's numbered buttons: at most five, windowed around [page]. */
fun pageWindow(page: Int, totalPages: Int): List<Int> = (0 until minOf(totalPages, 5)).map { i ->
    when {
        totalPages <= 5 -> i + 1
        page <= 3 -> i + 1
        page >= totalPages - 2 -> totalPages - 4 + i
        else -> page - 2 + i
    }
}

/** `i.qty || i.quantity || 1`. */
val OrderItem.effectiveQty: Double get() = if (qty > 0) qty else 1.0

/**
 * The line's unit price. The rows the agent writes today (agent/tools.py
 * `create_order`, from the cart) carry `unit_price` and no `unit`/`total`;
 * older rows carry `unit` + `total`. The web reads only `unit`, so a current
 * order's lines print "KES NaN". This takes `unit`, else the line total over
 * its quantity (the modern `unit_price` needs [OrderItem] to decode it — see
 * the round-3 report).
 */
val OrderItem.effectiveUnit: Double
    get() = when {
        unit > 0 -> unit
        total > 0 -> total / effectiveQty
        else -> 0.0
    }

/** Whether the row says what this line costs (a legacy `unit`/`total`). */
val OrderItem.priceKnown: Boolean get() = unit > 0 || total > 0

/** The line's money: its `total` when the row has one, else unit × qty (the web's formula). */
val OrderItem.lineTotal: Double get() = if (total > 0) total else effectiveUnit * effectiveQty

/** The order's money: `o.total || o.subtotal`. */
val Order.amount: Double get() = if (total != 0.0) total else subtotal

/**
 * Money and counts line up in columns: tabular (fixed-width) figures, so
 * "KES 1,284,750" over "KES 99,999" aligns digit for digit.
 */
val Tabular = TextStyle(fontFeatureSettings = "tnum")

/**
 * A figure that must never break inside itself ("KES" on one line, the digits
 * on the next): the spaces become no-break spaces.
 */
fun String.unbroken(): String = replace(' ', '\u00A0')

/**
 * How much room there is for text at the user's font size: the width in
 * "1.0-scale" dp. A 411dp phone at 200% text has the room of a 205dp one.
 */
@Composable
fun textRoom(width: Dp): Dp = width / androidx.compose.ui.platform.LocalDensity.current.fontScale

@Composable
fun toneBg(t: Tone): Color = if (Neema.colors.isDark) t.dot.copy(alpha = 0.14f) else t.bg

@Composable
fun toneBorder(t: Tone): Color = if (Neema.colors.isDark) t.dot.copy(alpha = 0.35f) else t.border

@Composable
fun toneText(t: Tone): Color = if (Neema.colors.isDark) t.dot else t.text

/** A small bordered status badge (the list's `text-[10px] rounded border` chips). */
@Composable
fun Badge(
    text: String,
    tone: Tone,
    modifier: Modifier = Modifier,
    fontSize: Int = 10,
    radius: Dp = 4.dp,
    hPad: Dp = 6.dp,
    vPad: Dp = 2.dp,
) {
    Text(
        text,
        modifier = modifier
            .clip(RoundedCornerShape(radius))
            .background(toneBg(tone))
            .border(1.dp, toneBorder(tone), RoundedCornerShape(radius))
            .padding(horizontal = hPad, vertical = vPad),
        color = toneText(tone), fontSize = fontSize.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
    )
}

/** CH_BG — the orders (and leads) list's flat channel colours. */
internal val CH_BG = mapOf(
    "whatsapp" to ChannelColors.WhatsApp,
    "messenger" to SalesInk.Messenger,
    "instagram" to ChannelColors.Instagram,
    "facebook" to ChannelColors.Facebook,
    "email" to Palette.Indigo500,
    "sms" to Palette.Moss600,
)

/** ChannelPill — a solid pill with the channel's mark and name, white on brand colour. */
@Composable
fun OrderChannelPill(channel: String?) {
    val ch = (channel?.ifBlank { null } ?: "whatsapp").lowercase(Locale.ROOT)
    val bg = CH_BG[ch] ?: Palette.Willow600
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(bg).padding(horizontal = 6.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ChannelGlyphs.forOrder(ch)?.let {
            Icon(it, contentDescription = null, tint = Color.White, modifier = Modifier.size(10.dp))
            Spacer(Modifier.width(4.dp))
        }
        Text(ch.replaceFirstChar { it.titlecase(Locale.ROOT) }, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Medium)
    }
}

/**
 * The web's compact search input: a fixed-height white box with a 1px
 * `#b5da8b` border and the magnifier inside on the left (Orders: `h-9`,
 * 16px text, rounded-xl; Leads: `h-8`, 14px text, rounded-lg).
 */
@Composable
fun CompactSearchField(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    height: Dp = 36.dp,
    radius: Dp = 12.dp,
    fontSize: Int = 16,
    iconSize: Dp = 16.dp,
    iconStart: Dp = 12.dp,
    textStart: Dp = 36.dp,
    iconTint: Color = Palette.Stone300,
) {
    val c = Neema.colors
    val shape = RoundedCornerShape(radius)
    val style = TextStyle(fontSize = fontSize.sp, color = c.text)
    BasicTextField(
        value = value, onValueChange = onChange, singleLine = true, textStyle = style,
        cursorBrush = SolidColor(c.gold),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        modifier = modifier.heightIn(min = height).clip(shape).background(c.bg2).border(1.dp, c.border, shape),
        decorationBox = { inner ->
            Box(Modifier.fillMaxWidth().heightIn(min = height), contentAlignment = Alignment.CenterStart) {
                Icon(
                    Icons.Default.Search, contentDescription = null,
                    tint = if (c.isDark) c.muted else iconTint,
                    modifier = Modifier.padding(start = iconStart).size(iconSize),
                )
                Box(Modifier.padding(start = textStart, end = 12.dp, top = 4.dp, bottom = 4.dp)) {
                    if (value.isEmpty()) {
                        Text(placeholder, style = style.copy(color = c.muted), maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    }
                    inner()
                }
            }
        },
    )
}

/**
 * Two blocks side by side when both fit at their natural width (the web's
 * `flex justify-between`), else stacked full-width — so a large font or a
 * narrow phone never squeezes the first into a letter-per-line column.
 * [end] is told which layout it is in, so it can re-arrange itself.
 */
@Composable
fun SideOrStacked(
    modifier: Modifier = Modifier,
    gap: Dp = 12.dp,
    start: @Composable () -> Unit,
    end: @Composable (stacked: Boolean) -> Unit,
) {
    androidx.compose.ui.layout.SubcomposeLayout(modifier) { cs ->
        val gapPx = gap.roundToPx()
        val s = subcompose("start", start).first()
        val eSide = subcompose("endSide") { end(false) }.first()
        val need = s.maxIntrinsicWidth(androidx.compose.ui.unit.Constraints.Infinity) +
            eSide.maxIntrinsicWidth(androidx.compose.ui.unit.Constraints.Infinity) + gapPx
        val loose = cs.copy(minWidth = 0, minHeight = 0)
        if (need <= cs.maxWidth) {
            val e = eSide.measure(loose)
            val sp = s.measure(loose.copy(maxWidth = (cs.maxWidth - e.width - gapPx).coerceAtLeast(0)))
            layout(cs.maxWidth, maxOf(sp.height, e.height)) {
                sp.place(0, 0)
                e.place(cs.maxWidth - e.width, 0)
            }
        } else {
            val sp = s.measure(loose)
            val e = subcompose("endStacked") { end(true) }.first().measure(loose.copy(minWidth = cs.maxWidth))
            layout(cs.maxWidth, sp.height + gapPx + e.height) {
                sp.place(0, 0)
                e.place(0, sp.height + gapPx)
            }
        }
    }
}
