package ke.co.bethanyhouse.neema.feature.reports

import androidx.compose.foundation.Canvas
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
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.ui.components.Panel
import ke.co.bethanyhouse.neema.core.ui.theme.Neema

/** A cell of a report table: plain text, or any composable (a badge, a dot). */
typealias Cell = @Composable () -> Unit

fun textCell(s: String): Cell = { Text(s, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurface, maxLines = 1, overflow = TextOverflow.Ellipsis) }

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
            Text(label.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(6.dp))
            Text(value, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = c.text, maxLines = 1)
            if (sub != null) Text(sub, fontSize = 11.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
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
                drawRoundRect(
                    color = color.copy(alpha = 0.7f + ratio * 0.3f),
                    topLeft = Offset(i * slot + gap / 2, size.height - h),
                    size = Size(w, h),
                    cornerRadius = CornerRadius(3.dp.toPx()),
                )
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
            data.forEach { d ->
                Text(d.label, fontSize = 9.sp, color = c.muted, modifier = Modifier.weight(1f), textAlign = TextAlign.Center, maxLines = 1)
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
            color = c.textDim, modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
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
            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                rows.forEach { row ->
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(c.bg).padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        ProvideTextStyle(TextStyle(fontWeight = FontWeight.Bold)) { row.firstOrNull()?.invoke() }
                        // The other columns as a two-up grid of small label over value.
                        row.drop(1).withIndex().chunked(2).forEach { pair ->
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                pair.forEach { (j, cell) ->
                                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                        Text(cols.getOrElse(j + 1) { "" }.uppercase(), fontSize = 9.sp, fontWeight = FontWeight.Bold, color = c.muted, letterSpacing = 0.5.sp, maxLines = 1)
                                        cell()
                                    }
                                }
                                if (pair.size == 1) Spacer(Modifier.weight(1f))
                            }
                        }
                    }
                }
            }
        }
    }
}
