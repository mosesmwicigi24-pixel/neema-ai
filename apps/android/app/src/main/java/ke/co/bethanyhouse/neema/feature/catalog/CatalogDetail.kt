package ke.co.bethanyhouse.neema.feature.catalog

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaMono
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt

/**
 * Tap a card for the whole product: every variant with its KES and USD price
 * and all aliases. Read-only, like everything on this screen.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ProductSheet(item: CatalogItem, onDismiss: () -> Unit) {
    val c = Neema.colors
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.bg2) {
        ProductDetail(item)
    }
}

/** The sheet's body (rendered on its own in screenshot tests). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ProductDetail(item: CatalogItem) {
    val c = Neema.colors
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Box(Modifier.size(96.dp).clip(RoundedCornerShape(12.dp)).background(categoryBrush(item.rawCategory))) {
                ProductThumb(item, glyphSize = 40)
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(item.name, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = c.text)
                Text("${glyph(item.rawCategory)} ${item.category}", fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(top = 2.dp))
                Spacer(Modifier.height(6.dp))
                StockBadge(item)
            }
        }
        Spacer(Modifier.height(14.dp))
        Text(unbroken(priceText(item)), fontSize = 20.sp, fontWeight = FontWeight.ExtraBold, color = c.gold2, style = ke.co.bethanyhouse.neema.feature.reports.tabular)
        val unit = item.unit?.takeIf { it.isNotBlank() }
        if (unit != null) Text("per $unit", fontSize = 12.sp, color = c.muted)
        if (item.priceUsd != null || item.priceKes != null) {
            Text(
                listOfNotNull(item.priceKes?.let { Fmt.currency(it) }, item.priceUsd?.let { usd(it) }).joinToString("  ·  "),
                fontSize = 12.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp),
            )
        }
        if (!item.description.isNullOrBlank()) {
            Text(item.description, fontSize = 13.sp, color = c.text, modifier = Modifier.padding(top = 12.dp))
        }

        if (item.variants.isNotEmpty()) {
            Spacer(Modifier.height(16.dp))
            Text("${item.variants.size} VARIANTS", fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp, color = c.muted)
            Spacer(Modifier.height(6.dp))
            item.variants.forEach { v ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(v.label ?: v.name ?: v.sku ?: "—", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = c.text)
                        val attrs = v.attributes.entries.joinToString(" · ") { "${it.key}: ${it.value}" }
                        if (attrs.isNotEmpty()) Text(attrs, fontSize = 11.sp, color = c.muted)
                        if (!v.sku.isNullOrBlank()) Text(v.sku, fontSize = 10.sp, fontFamily = NeemaMono, color = faint())
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        Text(v.priceKes?.let { Fmt.currency(it) } ?: "—", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                        v.priceUsd?.let { Text(usd(it), fontSize = 11.sp, color = c.textDim) }
                    }
                }
                HorizontalDivider(color = c.bg3)
            }
        }

        if (item.aliases.isNotEmpty()) {
            Spacer(Modifier.height(16.dp))
            Text("ALIASES", fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp, color = c.muted)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                item.aliases.forEach { AliasChip(it) }
            }
        }

        Spacer(Modifier.height(16.dp))
        Row {
            Text(item.sku, fontSize = 11.sp, fontFamily = NeemaMono, color = faint(), modifier = Modifier.weight(1f))
            item.hubProductId?.let { Text("#$it", fontSize = 11.sp, fontFamily = NeemaMono, color = faint()) }
        }
        item.productType?.let { Text("Type: $it", fontSize = 11.sp, color = c.muted) }
        if (item.updatedAt != null) Text("Updated ${Fmt.timeAgo(item.updatedAt)}", fontSize = 11.sp, color = c.muted)

        if (item.isHub) {
            Spacer(Modifier.height(16.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.Lock, null, tint = c.muted, modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(6.dp))
                Text("Maintained in the hub — to change this product, edit it in the hub.", fontSize = 12.sp, color = c.muted)
            }
        }
    }
}
