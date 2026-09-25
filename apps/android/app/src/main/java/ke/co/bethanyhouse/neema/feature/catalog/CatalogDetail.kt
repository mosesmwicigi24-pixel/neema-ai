package ke.co.bethanyhouse.neema.feature.catalog

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt

/**
 * Tap a card for the whole product: every variant with its KES and USD price,
 * all aliases, and — for local rows an agent may manage — edit / stock / delete.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
internal fun ProductSheet(
    item: CatalogItem, manageable: Boolean, busy: Boolean,
    onDismiss: () -> Unit, onEdit: () -> Unit, onToggle: () -> Unit, onDelete: () -> Unit,
) {
    val c = Neema.colors
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = c.bg2) {
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
            Text(priceText(item), fontSize = 20.sp, fontWeight = FontWeight.ExtraBold, color = c.gold2)
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
                            if (!v.sku.isNullOrBlank()) Text(v.sku, fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.border)
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
                Text(item.sku, fontSize = 11.sp, fontFamily = FontFamily.Monospace, color = c.border, modifier = Modifier.weight(1f))
                item.hubProductId?.let { Text("#$it", fontSize = 11.sp, fontFamily = FontFamily.Monospace, color = c.border) }
            }
            item.productType?.let { Text("Type: $it", fontSize = 11.sp, color = c.muted) }
            if (item.updatedAt != null) Text("Updated ${Fmt.timeAgo(item.updatedAt)}", fontSize = 11.sp, color = c.muted)

            Spacer(Modifier.height(16.dp))
            if (manageable) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onEdit, enabled = !busy, modifier = Modifier.weight(1f)) { Text("Edit") }
                    OutlinedButton(onClick = onToggle, enabled = !busy, modifier = Modifier.weight(1.4f)) {
                        Text(if (item.inStock) "Mark out of stock" else "Mark in stock", maxLines = 1)
                    }
                    OutlinedButton(onClick = onDelete, enabled = !busy, modifier = Modifier.weight(1f)) { Text("Delete", color = c.red) }
                }
            } else if (item.isHub) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Lock, null, tint = c.muted, modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Maintained in the hub — to change this product, edit it in the hub.", fontSize = 12.sp, color = c.muted)
                }
            }
        }
    }
}

/** Add / edit a local catalog item (POST / PATCH /admin/catalog). */
@Composable
internal fun CatalogEditor(
    title: String, initial: CatalogDraft, categories: List<String>, busy: Boolean,
    onDismiss: () -> Unit, onSave: (CatalogDraft) -> Unit,
) {
    var d by remember { mutableStateOf(initial) }
    var error by remember { mutableStateOf<String?>(null) }
    var catMenu by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(title) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(d.name, { d = d.copy(name = it) }, label = { Text("Name *") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(d.sku, { d = d.copy(sku = it) }, label = { Text("SKU") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        d.price, { d = d.copy(price = it) }, label = { Text("Price (KES) *") }, singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(d.unit, { d = d.copy(unit = it) }, label = { Text("Unit") }, singleLine = true, modifier = Modifier.weight(1f))
                }
                Box {
                    OutlinedTextField(
                        d.category, { d = d.copy(category = it) }, label = { Text("Category") }, singleLine = true,
                        trailingIcon = if (categories.isNotEmpty()) ({ TextButton(onClick = { catMenu = true }) { Text("Pick") } }) else null,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    DropdownMenu(expanded = catMenu, onDismissRequest = { catMenu = false }) {
                        categories.forEach { cat ->
                            DropdownMenuItem(text = { Text("${glyph(cat)} $cat") }, onClick = { d = d.copy(category = cat); catMenu = false })
                        }
                    }
                }
                OutlinedTextField(d.description, { d = d.copy(description = it) }, label = { Text("Description") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(
                    d.aliases, { d = d.copy(aliases = it) }, label = { Text("Aliases") },
                    supportingText = { Text("Comma-separated — other names customers use") }, modifier = Modifier.fillMaxWidth(),
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("In stock", modifier = Modifier.weight(1f))
                    Switch(d.inStock, { d = d.copy(inStock = it) })
                }
                error?.let { Text(it, color = Neema.colors.red, fontSize = 12.sp) }
            }
        },
        confirmButton = {
            TextButton(enabled = !busy, onClick = {
                error = when {
                    d.name.isBlank() -> "Name is required"
                    d.price.trim().toDoubleOrNull() == null -> "Price must be a valid number"
                    else -> null
                }
                if (error == null) onSave(d)
            }) { Text(if (busy) "Saving…" else "Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text("Cancel") } },
    )
}
