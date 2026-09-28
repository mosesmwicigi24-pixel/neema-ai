package ke.co.bethanyhouse.neema.core.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Dp

/**
 * Tabs that share a row: each gets at least its own label's width, and the
 * spare room is shared out so they fill [availableWidth] — equal widths when
 * every label fits an equal share, else content widths plus an equal share of
 * the slack. Only when the labels truly don't fit does the row run wider than
 * [availableWidth] (put it in a horizontalScroll): a narrow tablet pane keeps
 * every tab visible instead of hiding the last ones off the edge.
 */
@Composable
fun FitRow(availableWidth: Dp, spacing: Dp, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Layout(content, modifier) { measurables, constraints ->
        val gap = spacing.roundToPx()
        val avail = availableWidth.roundToPx()
        val n = measurables.size.coerceAtLeast(1)
        val natural = measurables.map { it.maxIntrinsicWidth(Constraints.Infinity) }
        val widths = fitWidths(natural, avail - gap * (n - 1))
        val maxH = if (constraints.hasBoundedHeight) constraints.maxHeight else Constraints.Infinity
        val placeables = measurables.mapIndexed { i, m -> m.measure(Constraints(widths[i], widths[i], 0, maxH)) }
        val h = placeables.maxOfOrNull { it.height } ?: 0
        val w = widths.sum() + gap * (n - 1).coerceAtLeast(0)
        layout(w, h) {
            var x = 0
            placeables.forEach { p -> p.placeRelative(x, (h - p.height) / 2); x += p.width + gap }
        }
    }
}

/** The widths children of [natural] widths get in [room] px (pure, unit-tested). */
fun fitWidths(natural: List<Int>, room: Int): List<Int> {
    if (natural.isEmpty()) return natural
    val total = natural.sum()
    if (total >= room) return natural
    val even = room / natural.size
    if (natural.all { it <= even }) return natural.map { even }
    val extra = (room - total) / natural.size
    return natural.map { it + extra }
}
