package ke.co.bethanyhouse.neema.feature.reports

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.ui.components.Panel
import ke.co.bethanyhouse.neema.core.ui.theme.Neema

/** A cell of a report table: plain text, or any composable (a badge, a dot). */
typealias Cell = @Composable () -> Unit

/** How many lines a [textCell] may take: one in a table row, two in a phone card (a phone number must not be cut). */
val LocalCellLines = compositionLocalOf { 1 }

fun textCell(s: String): Cell = {
    Text(s, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurface, maxLines = LocalCellLines.current, overflow = TextOverflow.Ellipsis)
}

/** Tabular figures, so totals and counts line up like the web's `tabular-nums`. */
const val TABULAR = "tnum"

/** The current text style with [TABULAR] figures. */
val tabular: TextStyle @Composable get() = androidx.compose.material3.LocalTextStyle.current.merge(TextStyle(fontFeatureSettings = TABULAR))

/**
 * A headline figure (the web's `text-2xl font-bold tabular-nums`) that is
 * never cut: on a narrow card or at a large font scale it steps down in size
 * until the whole amount fits on one line, instead of "KES 98,7…".
 */
@Composable
fun BigNumber(text: String, color: Color, modifier: Modifier = Modifier, max: TextUnit = 22.sp, min: TextUnit = 12.sp) {
    BasicText(
        text, modifier,
        style = TextStyle(fontSize = max, fontWeight = FontWeight.Bold, color = color, fontFeatureSettings = TABULAR),
        maxLines = 1, softWrap = false,
        autoSize = TextAutoSize.StepBased(minFontSize = min, maxFontSize = max, stepSize = 1.sp),
    )
}

/**
 * Columns for a grid of cards: [max] when each cell keeps at least
 * [minCell] (scaled with the user's font size), else two, else one. So a
 * 360dp phone at 130% keeps two KPI cards a row, and at 200% gets one card
 * per row instead of labels chopped to "Pendin…".
 */
@Composable
fun gridColumns(width: Dp, max: Int, gap: Dp = 12.dp, minCell: Dp = 120.dp, minWideCell: Dp = 160.dp): Int {
    val scale = LocalDensity.current.fontScale.coerceAtLeast(1f)
    fun cell(n: Int) = (width - gap * (n - 1)) / n
    return when {
        max > 2 && cell(max) >= minWideCell * scale -> max
        max >= 2 && cell(2) >= minCell * scale -> 2
        else -> 1
    }
}

/**
 * A panel's title with a figure on the right (the web's `flex justify-between`).
 * When both can't share a line — a narrow phone at a large font — the figure
 * drops under the title rather than squeezing it into a word per line.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PanelHeader(title: @Composable () -> Unit, trailing: @Composable () -> Unit, modifier: Modifier = Modifier) {
    FlowRow(
        modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
        verticalArrangement = Arrangement.spacedBy(2.dp), itemVerticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.padding(end = 8.dp)) { title() }
        trailing()
    }
}

/** The web's StatBox: a KPI card with a coloured left edge. */
@Composable
fun StatBox(label: String, value: String, sub: String?, accent: Color, modifier: Modifier = Modifier) {
    val c = Neema.colors
    Row(
        modifier.height(IntrinsicSize.Min).clip(RoundedCornerShape(12.dp)).background(c.bg2)
            .border(1.dp, c.hairline, RoundedCornerShape(12.dp)),
    ) {
        Box(Modifier.width(4.dp).fillMaxHeight().background(accent))
        Column(Modifier.padding(14.dp)) {
            Text(label.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp, color = c.muted, maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 14.sp)
            Spacer(Modifier.height(6.dp))
            BigNumber(value, c.text)
            if (sub != null) Text(sub, fontSize = 11.sp, color = c.muted, maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 15.sp)
        }
    }
}

data class BarPoint(val label: String, val value: Double)

/**
 * The web's MiniBar, on a Canvas: bar height ∝ value, a 3dp floor for any
 * non-zero day, opacity rising with the value. Tapping a bar shows its
 * "label: value" (the web's hover title).
 */
@Composable
fun MiniBar(data: List<BarPoint>, color: Color, format: (Double) -> String = { it.toLong().toString() }) {
    val c = Neema.colors
    var picked by remember(data) { mutableStateOf<Int?>(null) }
    val max = (data.maxOfOrNull { it.value } ?: 0.0).coerceAtLeast(1.0)
    Column {
        Text(
            picked?.let { "${data[it].label}: ${format(data[it].value)}" } ?: " ",
            fontSize = 11.sp, color = c.textDim, modifier = Modifier.height(16.dp),
        )
        Canvas(
            Modifier.fillMaxWidth().height(72.dp).pointerInput(data) {
                detectTapGestures { pos ->
                    if (data.isEmpty()) return@detectTapGestures
                    val i = (pos.x / (size.width / data.size)).toInt().coerceIn(0, data.size - 1)
                    picked = if (picked == i) null else i
                }
            },
        ) {
            if (data.isEmpty()) return@Canvas
            val gap = 4.dp.toPx()
            val slot = size.width / data.size
            val w = slot - gap
            data.forEachIndexed { i, d ->
                if (d.value <= 0) return@forEachIndexed
                val ratio = (d.value / max).toFloat()
                val h = (size.height * ratio).coerceAtLeast(3.dp.toPx())
                val r = minOf(4.dp.toPx(), h / 2, w / 2)
                val x = i * slot + gap / 2
                drawPath(
                    Path().apply {
                        addRoundRect(
                            RoundRect(
                                Rect(Offset(x, size.height - h), Size(w, h)),
                                topLeft = CornerRadius(r), topRight = CornerRadius(r),
                            ),
                        )
                    },
                    color = color.copy(alpha = 0.7f + ratio * 0.3f),
                )
            }
        }
        AxisLabels(data.map { it.label }, fontSize = 9.sp) { _ -> c.muted }
    }
}

/**
 * Day labels under a bar chart, one slot per bar. When a slot is too narrow
 * for a three-letter day (14 bars on a small phone, or a large font), only
 * every 2nd / 3rd label is drawn — always including the last (today) — so
 * no label is chopped to "Mo" or "We" and they never run together.
 */
@Composable
fun AxisLabels(
    labels: List<String>, fontSize: TextUnit, modifier: Modifier = Modifier,
    fontWeight: (Int) -> FontWeight = { FontWeight.Normal }, color: (Int) -> Color,
) {
    if (labels.isEmpty()) return
    // A plain Layout (not BoxWithConstraints): the chart sits in rows sized
    // by IntrinsicSize.Min, which a SubcomposeLayout can't answer.
    androidx.compose.ui.layout.Layout(
        content = {
            labels.forEachIndexed { i, label ->
                Text(label, fontSize = fontSize, fontWeight = fontWeight(i), color = color(i), maxLines = 1, softWrap = false)
            }
        },
        modifier = modifier.fillMaxWidth().padding(top = 4.dp),
    ) { measurables, constraints ->
        val loose = androidx.compose.ui.unit.Constraints()
        val placeables = measurables.map { it.measure(loose) }
        val width = if (constraints.hasBoundedWidth) constraints.maxWidth else placeables.sumOf { it.width }
        val slot = width.toFloat() / labels.size
        // Every label drawn must clear its neighbours by 4dp.
        val need = (placeables.maxOf { it.width } + 4.dp.toPx())
        val every = kotlin.math.ceil(need / slot).toInt().coerceAtLeast(1)
        val height = placeables.maxOf { it.height }
        layout(width, height) {
            placeables.forEachIndexed { i, p ->
                if ((labels.lastIndex - i) % every != 0) return@forEachIndexed
                val x = (slot * i + (slot - p.width) / 2).toInt().coerceIn(0, (width - p.width).coerceAtLeast(0))
                p.placeRelative(x, 0)
            }
        }
    }
}

/**
 * The web's Table. On a wide screen it is a real table; on a phone each row
 * becomes a card — the first column as its title, the rest as label/value lines.
 */
@Composable
fun ReportTable(
    header: String,
    cols: List<String>,
    rows: List<List<Cell>>,
    wide: Boolean,
    emptyText: String = "No data",
) {
    val c = Neema.colors
    Panel(Modifier.fillMaxWidth(), padding = PaddingValues(0.dp)) {
        Text(
            header.uppercase(), fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp,
            color = c.textDim, lineHeight = 16.sp, modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
        )
        HorizontalDivider(color = c.bg3)
        if (rows.isEmpty()) {
            Text(emptyText, color = c.muted, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp))
            return@Panel
        }
        if (wide) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp)) {
                cols.forEach { col ->
                    Text(col.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp, color = c.muted, modifier = Modifier.weight(1f), maxLines = 1)
                }
            }
            HorizontalDivider(color = c.bg3)
            rows.forEach { row ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    row.forEach { cell -> Box(Modifier.weight(1f)) { cell() } }
                }
                HorizontalDivider(color = c.bg)
            }
        } else {
            // Two label/value pairs a line where they fit; one when the font is
            // large, so a phone number or a date is never cut.
            val scale = LocalDensity.current.fontScale
            BoxWithConstraints(Modifier.fillMaxWidth()) {
            val perLine = if (maxWidth / scale.coerceAtLeast(1f) >= 240.dp) 2 else 1
            CompositionLocalProvider(LocalCellLines provides 2) {
            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                rows.forEach { row ->
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(c.bg2)
                            // White like the web's table rows, so the -50 badge tints still read.
                            .border(1.dp, if (c.isDark) c.hairline else c.bg3, RoundedCornerShape(10.dp)).padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        ProvideTextStyle(TextStyle(fontWeight = FontWeight.Bold)) { row.firstOrNull()?.invoke() }
                        // The other columns as a two-up grid of small label over value.
                        row.drop(1).withIndex().chunked(perLine).forEach { pair ->
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                pair.forEach { (j, cell) ->
                                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                        Text(cols.getOrElse(j + 1) { "" }.uppercase(), fontSize = 9.sp, fontWeight = FontWeight.Bold, color = c.muted, letterSpacing = 0.5.sp, maxLines = 1)
                                        cell()
                                    }
                                }
                                if (pair.size < perLine) Spacer(Modifier.weight(1f))
                            }
                        }
                    }
                }
            }
            }
            }
        }
    }
}
