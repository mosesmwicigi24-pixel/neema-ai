package ke.co.bethanyhouse.neema.feature.settings

import ke.co.bethanyhouse.neema.core.util.AppClock

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.automirrored.outlined.Chat
import androidx.compose.material.icons.outlined.Email
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.TableChart
import androidx.compose.material.icons.outlined.Tag
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Campaign
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.ui.components.ConfirmDialog
import ke.co.bethanyhouse.neema.core.ui.components.Panel
import ke.co.bethanyhouse.neema.core.ui.components.Pill
import ke.co.bethanyhouse.neema.core.ui.components.SearchField
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import java.time.LocalDate
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import ke.co.bethanyhouse.neema.feature.agents.SideBySide
import ke.co.bethanyhouse.neema.feature.agents.isCramped
import ke.co.bethanyhouse.neema.feature.agents.onGold
import ke.co.bethanyhouse.neema.core.ui.components.neemaSwitchColors
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import androidx.compose.ui.graphics.SolidColor

private val Amber700 = Palette.Amber700

/**
 * What starts open on Settings — a date picker ("ends" / "starts"), the
 * end-offer confirmation, the product picker. Only screenshot tests set it.
 */
data class SettingsPreview(
    val datePicker: String? = null,
    val confirmEnd: Boolean = false,
    val skuPicker: Boolean = false,
    val newStage: String = "",
    /** Initial scroll offset in px, to render a lower part of the page. */
    val scroll: Int = 0,
)

val LocalSettingsPreview = staticCompositionLocalOf { SettingsPreview() }

/** Port of SettingsView.tsx — platform configuration. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(dash: DashboardViewModel) {
    // No permission gate — page.tsx renders SettingsView for anyone. The nav
    // lists Settings only with manage_settings, but the account menu's
    // Settings entry and ?view=settings open it for everyone. Every card
    // loads; a save by someone who isn't an admin gets the server's 403 and
    // the web's "(admin only)" words (crm.py checks role admin / superuser,
    // not manage_settings).
    val vm: SettingsViewModel = viewModel { SettingsViewModel(dash) }
    // Unsaved standing orders, offer and local fields come back after Android restarts the app.
    ke.co.bethanyhouse.neema.feature.reports.KeepUiState(vm)
    ke.co.bethanyhouse.neema.feature.reports.TrackShown(vm.life)
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val c = Neema.colors
    val startScroll = LocalSettingsPreview.current.scroll

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize().background(c.bg)) {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            // The web's grid is one column on phones, two otherwise.
            val twoCols = maxWidth >= 720.dp
            Column(Modifier.fillMaxSize().verticalScroll(ke.co.bethanyhouse.neema.feature.reports.rememberKeptScrollState("settings.page", startScroll)).padding(16.dp)) {
                Text("Settings", style = MaterialTheme.typography.headlineSmall, color = c.text)
                Text("Platform configuration and integrations", fontSize = 12.sp, color = c.textDim)
                Spacer(Modifier.height(18.dp))

                val cards: List<@Composable () -> Unit> = listOf(
                    { StandingOrdersCard(vm) },
                    { TranslationCard(vm) },
                    { OfferCard(vm, dash) },
                    { PipelineStagesCard(vm) },
                    { BusinessCard(vm) },
                    { AiCard(vm) },
                )
                if (twoCols) {
                    // Two balanced columns: the tall offer form sits under standing orders on the
                    // left; the four shorter cards stack on the right (alternating left the right
                    // column half empty).
                    val left = setOf(0, 2)
                    Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                            cards.filterIndexed { i, _ -> i in left }.forEach { it() }
                        }
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                            cards.filterIndexed { i, _ -> i !in left }.forEach { it() }
                        }
                    }
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) { cards.forEach { it() } }
                }
                Spacer(Modifier.height(14.dp))
                IntegrationsCard(vm, twoCols)
                Spacer(Modifier.height(14.dp))
                DangerZoneCard(vm)
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

// ── Building blocks (SectionCard / Field / SmallInput) ─────────────────────────

/** The web's SectionCard: white, rounded-xl, #cee6b2 border, p-5, title block mb-4. */
@Composable
private fun SectionCard(title: String, description: String? = null, content: @Composable ColumnScope.() -> Unit) {
    val c = Neema.colors
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.bg2)
            .border(1.dp, if (c.isDark) c.hairline else c.bg4, RoundedCornerShape(12.dp)).padding(20.dp),
    ) {
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text)
        if (description != null) {
            Text(description, fontSize = 12.sp, color = c.textDim, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp))
        }
        Spacer(Modifier.height(16.dp))
        content()
    }
}

/** Tailwind stone-600, the web's field-label colour. */
private val Stone600 = Palette.Stone600

/** The web's SmallInput by day: #f3f9ec fill, #b5da8b border. */
@Composable
private fun smallInputColors(): TextFieldColors {
    val c = Neema.colors
    return OutlinedTextFieldDefaults.colors(
        unfocusedContainerColor = c.bg, focusedContainerColor = c.bg, errorContainerColor = c.bg, disabledContainerColor = c.bg,
        unfocusedBorderColor = c.border, focusedBorderColor = c.gold, cursorColor = c.gold,
    )
}

/** The web's textarea and select: white with a stone-200 hairline. */
@Composable
private fun plainFieldColors(): TextFieldColors {
    val c = Neema.colors
    return OutlinedTextFieldDefaults.colors(
        unfocusedBorderColor = if (c.isDark) c.border else c.hairline, focusedBorderColor = c.gold, cursorColor = c.gold,
        disabledBorderColor = if (c.isDark) c.border else c.hairline,
    )
}

@Composable
private fun Field(label: String, hint: String? = null, hintColor: Color? = null, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(modifier.padding(bottom = 12.dp)) {
        Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.let { if (it.isDark) it.textMid else Stone600 })
        Spacer(Modifier.height(5.dp))
        content()
        if (hint != null) Text(hint, fontSize = 11.sp, lineHeight = 15.sp, color = hintColor ?: Neema.colors.muted, modifier = Modifier.padding(top = 3.dp))
    }
}

@Composable
private fun SmallInput(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String? = null,
    keyboardType: KeyboardType = KeyboardType.Text,
    secret: Boolean = false,
    isError: Boolean = false,
    modifier: Modifier = Modifier,
) {
    OutlinedTextField(
        value = value, onValueChange = onChange, singleLine = true,
        placeholder = placeholder?.let { { Text(it, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Neema.colors.muted) } },
        keyboardOptions = KeyboardOptions(keyboardType = if (secret) KeyboardType.Password else keyboardType),
        visualTransformation = if (secret) androidx.compose.ui.text.input.PasswordVisualTransformation()
        else androidx.compose.ui.text.input.VisualTransformation.None,
        isError = isError,
        shape = RoundedCornerShape(10.dp),
        textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
        colors = smallInputColors(),
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
private fun SaveButton(label: String, saving: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    Button(
        onClick = onClick, enabled = enabled && !saving,
        shape = RoundedCornerShape(8.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Neema.colors.gold, contentColor = onGold()),
    ) {
        if (saving) {
            CircularProgressIndicator(Modifier.size(14.dp), color = LocalContentColor.current, strokeWidth = 2.dp)
            Spacer(Modifier.width(6.dp))
        }
        Text(if (saving) "Saving…" else label, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
    }
}

// ── Standing orders ───────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StandingOrdersCard(vm: SettingsViewModel) {
    val text by vm.directives.collectAsStateWithLifecycle()
    val max by vm.maxChars.collectAsStateWithLifecycle()
    val loaded by vm.directivesLoaded.collectAsStateWithLifecycle()
    val saving by vm.savingDirectives.collectAsStateWithLifecycle()
    SectionCard(
        "Standing Orders",
        "Live steering — Neema reads this before every reply. Emphasis only; pricing & payment rules always win.",
    ) {
        CardLoadProblem(vm, "directives", "Couldn't load the standing orders")
        OutlinedTextField(
            value = text, onValueChange = vm::setDirectives, enabled = loaded,
            minLines = 4, maxLines = 10,
            placeholder = {
                Text(
                    "e.g. \"Push copes this week — Easter is close. Quote 3-week lead times on made-to-order. " +
                        "Mention the new Ladies Princess Cassock to lady customers.\"",
                    fontSize = 13.sp, color = Neema.colors.muted,
                )
            },
            shape = RoundedCornerShape(8.dp),
            textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
            colors = plainFieldColors(),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(6.dp))
        // The counter left, Save right; at a large font the button drops under the counter.
        FlowRow(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text("${text.length}/$max", fontSize = 11.sp,
                color = if (text.length >= max) Amber700 else Neema.colors.muted,
                modifier = Modifier.align(Alignment.CenterVertically).padding(end = 12.dp))
            SaveButton("Save standing orders", saving, enabled = loaded, onClick = vm::saveDirectives)
        }
    }
}

/**
 * A live card whose read failed: the reason and a Retry for that card alone.
 * Answers whether it is showing (so the card can skip its "Loading…").
 */
@Composable
private fun CardLoadProblem(vm: SettingsViewModel, card: String, title: String): Boolean {
    val errors by vm.loadErrors.collectAsStateWithLifecycle()
    val why = errors[card] ?: return false
    ke.co.bethanyhouse.neema.feature.reports.LoadProblem(
        title = title, message = why, onRetry = { vm.retry(card) },
        modifier = Modifier.padding(bottom = 10.dp),
    )
    return true
}

// ── Translation ───────────────────────────────────────────────────────────────

@Composable
private fun TranslationCard(vm: SettingsViewModel) {
    val state by vm.translation.collectAsStateWithLifecycle()
    val c = Neema.colors
    fun money(v: Double) = if (v > 0 && v < 0.01) "under $0.01" else "$" + "%.2f".format(v)
    SectionCard(
        "Translation for the team",
        "Shows an English line under any message that is not English or Swahili — in both directions, so you can " +
            "follow a whole conversation. Customers never see it.",
    ) {
        if (CardLoadProblem(vm, "translation", "Couldn't load the translation setting")) return@SectionCard
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                val s = state
                Text(if (s == null) "Loading…" else if (s.enabled) "On" else "Off", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                Text(
                    when {
                        s == null -> " "
                        s.calls30d > 0 -> "${money(s.spend30dUsd)} over the last 30 days · ${s.calls30d} call${if (s.calls30d == 1) "" else "s"}"
                        else -> "Nothing spent in the last 30 days"
                    },
                    fontSize = 11.sp, color = c.muted,
                )
            }
            Spacer(Modifier.width(8.dp))
            Switch(colors = neemaSwitchColors(),
                checked = state?.enabled == true, onCheckedChange = { vm.toggleTranslation() }, enabled = state != null,
                modifier = Modifier.semantics { contentDescription = "Translation for the team" },
            )
        }
        if (state != null && state?.enabled == false) {
            Text(
                "Translations already saved stay visible — turning this off only stops new ones being bought.",
                fontSize = 11.sp, color = c.muted, modifier = Modifier.padding(top = 12.dp),
            )
        }
    }
}

// ── Offer ─────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun OfferCard(vm: SettingsViewModel, dash: DashboardViewModel) {
    val state by vm.offer.collectAsStateWithLifecycle()
    val draft by vm.draft.collectAsStateWithLifecycle()
    val saving by vm.savingOffer.collectAsStateWithLifecycle()
    val catalog by dash.catalog.collectAsStateWithLifecycle()
    val c = Neema.colors
    val preview = LocalSettingsPreview.current
    var confirmEnd by rememberSaveable(key = ke.co.bethanyhouse.neema.feature.reports.keptKey("settings.endOffer")) { mutableStateOf(preview.confirmEnd) }
    var skuPicker by rememberSaveable(key = ke.co.bethanyhouse.neema.feature.reports.keptKey("settings.skuPicker")) { mutableStateOf(preview.skuPicker) }

    SectionCard(
        "Offer running now",
        "A discount you have given. Neema states it outright — the offer's name, the old price, the new one, and when it ends — and stops the day it expires.",
    ) {
        val s = state
        if (s == null) {
            if (!CardLoadProblem(vm, "offer", "Couldn't load the offer")) Text("Loading…", fontSize = 12.sp, color = c.muted)
            return@SectionCard
        }
        val campaign = s.campaign
        if (campaign != null) {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                modifier = Modifier.padding(bottom = 8.dp),
            ) {
                Pill(if (s.running) "Running" else "Not running", if (s.running) c.green else Amber700, Modifier.align(Alignment.CenterVertically))
                Text("${campaign.name} · ${campaign.percent.toInt()}% off", fontSize = 12.sp, color = c.textMid,
                    modifier = Modifier.align(Alignment.CenterVertically))
            }
        }
        if (s.says.isNotBlank()) {
            Text(
                androidx.compose.ui.text.buildAnnotatedString {
                    append("Neema says: ")
                    pushStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.SemiBold)); append(s.says); pop()
                },
                fontSize = 12.sp, color = c.text,
                modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp).clip(RoundedCornerShape(8.dp))
                    .background(c.bg).border(1.dp, c.bg4, RoundedCornerShape(8.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
            )
        }
        if (campaign != null && !s.running) {
            val startsLater = campaign.startsOn?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.isAfter(AppClock.today()) == true
            Text(
                if (startsLater) "This offer starts on ${Fmt.date(campaign.startsOn)} — it is saved, and Neema begins mentioning it that day."
                else "This offer has passed its end date — it is saved, but Neema is not mentioning it.",
                fontSize = 11.sp, color = Amber700, modifier = Modifier.padding(bottom = 12.dp),
            )
        }

        Field("Offer name", "What the customer hears it called.") {
            SmallInput(draft.name, { v -> vm.editDraft { it.copy(name = v) } }, placeholder = "Harvest Offer")
        }

        val max = s.maxPercent.toInt().takeIf { it > 0 } ?: 70
        val pct = draft.percent
        val pctBad = pct < 1 || pct > max
        SideBySide(
            { m ->
                Field("Discount %", "1–$max", hintColor = if (pctBad) c.red else null, modifier = m) {
                    SmallInput(
                        if (pct == pct.toLong().toDouble()) pct.toLong().toString() else pct.toString(),
                        { v -> vm.editDraft { it.copy(percent = v.filter { ch -> ch.isDigit() }.take(3).toDoubleOrNull() ?: 0.0) } },  // whole percent: the server keeps int(percent)
                        keyboardType = KeyboardType.Number, isError = pctBad,
                    )
                }
            },
            { m ->
                Field("Last day", "Inclusive — it runs through this date.", modifier = m) {
                    DateButton("ends", draft.endsOn.ifBlank { null }, "Pick a date") { d -> vm.editDraft { it.copy(endsOn = d ?: "") } }
                }
            },
        )
        Field("First day (optional)", "Leave empty to start straight away.") {
            DateButton("starts", draft.startsOn, "Starts now", clearable = true) { d -> vm.editDraft { it.copy(startsOn = d) } }
        }

        Field("Applies to") {
            ke.co.bethanyhouse.neema.feature.agents.SelectField(
                null,
                listOf("all" to "Everything in the catalogue", "category" to "Certain categories", "products" to "Certain products"),
                draft.scope, { v -> vm.editDraft { it.copy(scope = v) } },
            )
        }

        if (draft.scope == "category") {
            Field("Categories", "As they appear in the hub. e.g. gowns, cassocks") {
                CategoryPicker(
                    known = catalog.map { it.category }.filter { it.isNotBlank() }.distinct().sortedBy { it.lowercase() },
                    selected = draft.categories,
                    onChange = { list -> vm.editDraft { it.copy(categories = list) } },
                )
            }
        }
        if (draft.scope == "products") {
            Field("Product SKUs", "Only these items get the offer.") {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    draft.skus.forEach { sku ->
                        val name = productNameFor(catalog, sku)
                        InputChip(
                            selected = true, onClick = {},
                            colors = InputChipDefaults.inputChipColors(
                                selectedContainerColor = if (c.isDark) c.goldDim else c.bg3, selectedLabelColor = c.gold2, selectedTrailingIconColor = c.gold2,
                            ),
                            border = InputChipDefaults.inputChipBorder(
                                enabled = true, selected = true, selectedBorderColor = c.border, borderColor = c.border,
                            ),
                            label = { Text(if (name != null) "$sku · $name" else sku, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            trailingIcon = {
                                Icon(Icons.Default.Close, "Remove $sku", Modifier.size(16.dp).clickable(role = Role.Button) {
                                    vm.editDraft { it.copy(skus = it.skus - sku) }
                                })
                            },
                        )
                    }
                    AssistChip(onClick = { skuPicker = true }, label = { Text("Choose products") },
                        leadingIcon = { Icon(Icons.Default.Add, null, Modifier.size(16.dp)) })
                }
                Spacer(Modifier.height(6.dp))
                AddTextRow("Or type a SKU") { sku -> vm.editDraft { d -> if (d.skus.any { it.equals(sku, true) }) d else d.copy(skus = d.skus + sku) } }
            }
        }

        Text(
            "Orders still reach the hub at the list price with the offer noted on them — a person applies it before payment.",
            fontSize = 11.sp, color = c.muted, lineHeight = 15.sp, modifier = Modifier.padding(bottom = 12.dp),
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SaveButton(if (campaign != null) "Update offer" else "Start offer", saving) { vm.saveOffer(draft) }
            if (campaign != null) {
                OutlinedButton(onClick = { confirmEnd = true }, enabled = !saving, shape = RoundedCornerShape(10.dp)) {
                    Text("End it now", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = c.textMid)
                }
            }
        }
    }

    if (confirmEnd) {
        ConfirmDialog(
            title = "End this offer?",
            message = "Neema stops mentioning “${state?.campaign?.name ?: "it"}” from her next reply. You can start a new offer any time.",
            confirmLabel = "End it now",
            destructive = true,
            onConfirm = { vm.saveOffer(null) },
            onDismiss = { confirmEnd = false },
        )
    }
    if (skuPicker) {
        SkuPickerDialog(catalog, draft.skus, onDismiss = { skuPicker = false }) { picked ->
            vm.editDraft { it.copy(skus = picked) }
            skuPicker = false
        }
    }
}

private fun productNameFor(catalog: List<CatalogItem>, sku: String): String? {
    catalog.forEach { item ->
        if (item.sku.equals(sku, true)) return item.name
        item.variants.forEach { v -> if (v.sku.equals(sku, true)) return v.label ?: v.name ?: item.name }
    }
    return null
}

/** Chips for the catalogue's categories, plus any typed category the catalogue doesn't list. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CategoryPicker(known: List<String>, selected: List<String>, onChange: (List<String>) -> Unit) {
    val all = (known + selected.filter { s -> known.none { it.equals(s, true) } })
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        all.forEach { cat ->
            val on = selected.any { it.equals(cat, true) }
            FilterChip(
                selected = on,
                onClick = { onChange(if (on) selected.filterNot { it.equals(cat, true) } else selected + cat) },
                label = { Text(cat, fontSize = 12.sp) },
                leadingIcon = if (on) ({ Icon(Icons.Default.Check, null, Modifier.size(16.dp)) }) else null,
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = Neema.colors.let { if (it.isDark) it.goldDim else it.bg3 }, selectedLabelColor = Neema.colors.gold2,
                    selectedLeadingIconColor = Neema.colors.gold,
                ),
                border = FilterChipDefaults.filterChipBorder(
                    enabled = true, selected = on,
                    borderColor = Neema.colors.border, selectedBorderColor = Neema.colors.border,
                ),
            )
        }
    }
    if (known.isEmpty()) {
        Text("The catalogue hasn't loaded — type the categories instead.", fontSize = 11.sp, color = Neema.colors.muted)
    }
    Spacer(Modifier.height(6.dp))
    AddTextRow("Add a category") { v -> if (selected.none { it.equals(v, true) }) onChange(selected + v) }
}

@Composable
private fun AddTextRow(placeholder: String, onAdd: (String) -> Unit) {
    var text by rememberSaveable { mutableStateOf("") }
    fun submit() { text.trim().takeIf { it.isNotEmpty() }?.let { onAdd(it); text = "" } }
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = text, onValueChange = { text = it }, singleLine = true,
            placeholder = { Text(placeholder, fontSize = 13.sp, color = Neema.colors.muted, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { submit() }),
            shape = RoundedCornerShape(10.dp),
            textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.width(6.dp))
        FilledTonalButton(onClick = { submit() }, enabled = text.isNotBlank(), shape = RoundedCornerShape(10.dp)) { Text("Add", maxLines = 1) }
    }
}

/** Search the catalogue and tick products (and their variants) for the offer. */
@Composable
private fun SkuPickerDialog(catalog: List<CatalogItem>, selected: List<String>, onDismiss: () -> Unit, onDone: (List<String>) -> Unit) {
    val c = Neema.colors
    var query by rememberSaveable(key = ke.co.bethanyhouse.neema.feature.reports.keptKey("settings.skuPicker.query")) { mutableStateOf("") }
    var picked by rememberSaveable(key = ke.co.bethanyhouse.neema.feature.reports.keptKey("settings.skuPicker.picked")) { mutableStateOf(selected) }
    // One row per sellable SKU: the product itself, then each variant that has its own.
    val rows = remember(catalog) {
        catalog.flatMap { item ->
            val own = if (item.sku.isNotBlank()) listOf(Triple(item.sku, item.name, item.category)) else emptyList()
            own + item.variants.mapNotNull { v -> v.sku?.takeIf { it.isNotBlank() && it != item.sku }?.let { Triple(it, v.label ?: v.name ?: item.name, item.category) } }
        }.distinctBy { it.first.lowercase() }
    }
    val q = query.trim().lowercase()
    val shown = if (q.isEmpty()) rows else rows.filter { (sku, name, cat) ->
        sku.lowercase().contains(q) || name.lowercase().contains(q) || cat.lowercase().contains(q)
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Choose products") },
        text = {
            Column {
                SearchField(query, { query = it }, placeholder = "Search name or SKU…")
                Spacer(Modifier.height(8.dp))
                Text("${picked.size} selected", fontSize = 11.sp, color = c.muted)
                if (rows.isEmpty()) {
                    Text("The catalogue hasn't loaded yet — type SKUs on the form instead.", fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(top = 12.dp))
                } else if (shown.isEmpty()) {
                    Text("No products match “$query”.", fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(top = 12.dp))
                }
                LazyColumn(Modifier.heightIn(max = 380.dp)) {
                    items(shown, key = { it.first }) { (sku, name, cat) ->
                        val on = picked.any { it.equals(sku, true) }
                        Row(
                            Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(role = Role.Checkbox) {
                                picked = if (on) picked.filterNot { it.equals(sku, true) } else picked + sku
                            }.padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(checked = on, onCheckedChange = null)
                            Spacer(Modifier.width(8.dp))
                            Column(Modifier.weight(1f)) {
                                Text(name, fontSize = 13.sp, color = c.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text("$sku · $cat", fontSize = 11.sp, color = c.muted, maxLines = 1)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { onDone(picked) }) { Text("Done") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** A date field that opens the Material date picker; values are YYYY-MM-DD. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DateButton(id: String, value: String?, emptyLabel: String, clearable: Boolean = false, onPick: (String?) -> Unit) {
    val startOpen = LocalSettingsPreview.current.datePicker == id
    var open by rememberSaveable(key = ke.co.bethanyhouse.neema.feature.reports.keptKey("settings.date.$id")) { mutableStateOf(startOpen) }
    val c = Neema.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedButton(
            onClick = { open = true },
            shape = RoundedCornerShape(10.dp),
            modifier = Modifier.weight(1f).heightIn(min = 52.dp),
            contentPadding = PaddingValues(horizontal = 12.dp),
        ) {
            Icon(Icons.Outlined.CalendarMonth, null, Modifier.size(18.dp), tint = c.textDim)
            Spacer(Modifier.width(8.dp))
            Text(
                value?.let { Fmt.date(it) } ?: emptyLabel,
                fontSize = 14.sp, color = if (value != null) c.text else c.muted,
                modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        if (clearable && value != null) {
            IconButton(onClick = { onPick(null) }) { Icon(Icons.Default.Close, "Clear date") }
        }
    }
    if (open) {
        val state = rememberDatePickerState(initialSelectedDateMillis = isoDateToUtcMillis(value))
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { ms -> onPick(utcMillisToIsoDate(ms)) }
                    open = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { open = false }) { Text("Cancel") } },
        ) { DatePicker(state) }
    }
}

// ── Pipeline stages ───────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PipelineStagesCard(vm: SettingsViewModel) {
    val stages by vm.stages.collectAsStateWithLifecycle()
    val saving by vm.savingStages.collectAsStateWithLifecycle()
    val c = Neema.colors
    val startStage = LocalSettingsPreview.current.newStage
    remember(vm) { if (startStage.isNotEmpty()) vm.newStage.value = startStage }
    // Held by the ViewModel: it outlives a rotation, and a save still on the wire when the phone turns still clears it.
    val newStage by vm.newStage.collectAsStateWithLifecycle()
    SectionCard(
        "Pipeline stages",
        "Your own stage labels, shown between Proposal and Won in every lead pipeline. Up to $PIPELINE_CUSTOM_MAX; the built-in stages stay fixed.",
    ) {
        val list = stages
        if (list == null) {
            if (!CardLoadProblem(vm, "stages", "Couldn't load the pipeline stages")) Text("Loading…", fontSize = 12.sp, color = c.muted)
            return@SectionCard
        }
        // The typed label is cleared only once the server has kept it; a failed save leaves it to retry.
        fun add() { val sent = newStage; vm.addStage(sent) { if (vm.newStage.value == sent) vm.newStage.value = "" } }
        // The order a lead moves through, customs in place.
        Text(
            (CANONICAL_BEFORE + list + listOf("Won")).joinToString(" → ") + " / Lost",
            fontSize = 11.sp, color = c.textMid, modifier = Modifier.padding(bottom = 10.dp),
        )
        if (list.isEmpty()) {
            Text("No custom stages yet.", fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(bottom = 8.dp))
        } else {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(bottom = 8.dp)) {
                list.forEach { s ->
                    Row(
                        Modifier.clip(RoundedCornerShape(6.dp)).background(if (c.isDark) Palette.PipeGold.copy(alpha = 0.15f) else Palette.PipeChipFill)
                            .border(1.dp, if (c.isDark) Palette.PipeGold.copy(alpha = 0.4f) else Palette.PipeChipLine, RoundedCornerShape(6.dp)).padding(start = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(s, fontSize = 12.sp, color = if (c.isDark) Palette.PipeChipLine else Palette.PipeChipInk)
                        // 32dp drawn; Compose widens the touch area to 48dp.
                        IconButton(onClick = { vm.removeStage(s) }, enabled = !saving, modifier = Modifier.size(32.dp)) {
                            Icon(Icons.Default.Close, "Remove $s", Modifier.size(14.dp), tint = c.muted)
                        }
                    }
                }
            }
        }
        if (list.size < PIPELINE_CUSTOM_MAX) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = newStage, onValueChange = { vm.newStage.value = it.take(PIPELINE_LABEL_MAX) }, singleLine = true,
                    placeholder = { Text("Stage label (e.g. Sampling)…", fontSize = 13.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { add() }),
                    shape = RoundedCornerShape(10.dp),
                    textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
                    supportingText = { Text("${newStage.length}/$PIPELINE_LABEL_MAX", fontSize = 10.sp) },
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(6.dp))
                Button(
                    onClick = { add() },
                    enabled = newStage.isNotBlank() && !saving,
                    shape = RoundedCornerShape(10.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Palette.PipeGoldSolid, contentColor = Color.White),
                ) { Text("Add", maxLines = 1) }
            }
        } else {
            Text("That's the most custom stages — remove one to add another.", fontSize = 11.sp, color = c.muted)
        }
    }
}

// ── Business / AI (local-only on the web) ─────────────────────────────────────

@Composable
private fun BusinessCard(vm: SettingsViewModel) {
    val biz by vm.biz.collectAsStateWithLifecycle()
    val saving by vm.savingBiz.collectAsStateWithLifecycle()
    SectionCard("Business", "Core platform details") {
        // The web's two-column grid; on a narrow phone or at a large font the fields stack.
        SideBySide(
            { m -> Field("Business Name", modifier = m) { SmallInput(biz.businessName, { v -> vm.biz.value = biz.copy(businessName = v) }, "Bethany House") } },
            { m -> Field("Currency", modifier = m) { SmallInput(biz.currency, { v -> vm.biz.value = biz.copy(currency = v) }, "KES") } },
        )
        SideBySide(
            { m -> Field("WhatsApp Number", modifier = m) { SmallInput(biz.waNumber, { v -> vm.biz.value = biz.copy(waNumber = v) }, "+254...", KeyboardType.Phone) } },
            { m -> Field("Timezone", modifier = m) { SmallInput(biz.timezone, { v -> vm.biz.value = biz.copy(timezone = v) }, "Africa/Nairobi") } },
        )
        SideBySide(
            { m -> Field("Open Hours", "Shown to customers", modifier = m) { SmallInput(biz.openHours, { v -> vm.biz.value = biz.copy(openHours = v) }, "08:00–18:00") } },
            null,
        )
        SaveButton("Save", saving, onClick = vm::saveBiz)
    }
}

@Composable
private fun AiCard(vm: SettingsViewModel) {
    val ai by vm.ai.collectAsStateWithLifecycle()
    val saving by vm.savingAi.collectAsStateWithLifecycle()
    val c = Neema.colors
    SectionCard("AI Configuration", "How the AI handles conversations") {
        SideBySide(
            { m ->
                Field("Escalation Threshold", "Messages before escalating", modifier = m) {
                    SmallInput(ai.autoInterceptThreshold, { v -> vm.ai.value = ai.copy(autoInterceptThreshold = v.filter(Char::isDigit)) }, keyboardType = KeyboardType.Number)
                }
            },
            { m ->
                Field("Response Delay (ms)", "Typing simulation", modifier = m) {
                    SmallInput(ai.responseDelayMs, { v -> vm.ai.value = ai.copy(responseDelayMs = v.filter(Char::isDigit)) }, keyboardType = KeyboardType.Number)
                }
            },
        )
        Field("Escalation Keywords", "Comma-separated trigger words") {
            SmallInput(ai.escalationKeywords, { v -> vm.ai.value = ai.copy(escalationKeywords = v) }, "refund, complaint, manager")
        }
        HorizontalDivider(color = c.bg3)
        Row(
            Modifier.fillMaxWidth()
                .toggleable(ai.draftApproval, role = Role.Switch) { vm.ai.value = ai.copy(draftApproval = it) }
                .padding(vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("Require draft approval", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = c.text)
                Text("AI drafts need agent approval before sending", fontSize = 11.sp, color = c.muted)
            }
            Spacer(Modifier.width(8.dp))
            Switch(checked = ai.draftApproval, onCheckedChange = null, colors = neemaSwitchColors())
        }
        HorizontalDivider(color = c.bg3)
        Spacer(Modifier.height(12.dp))
        SaveButton("Save AI Settings", saving, onClick = vm::saveAi)
    }
}

// ── Integrations ──────────────────────────────────────────────────────────────

private data class PlatformIcon(val icon: ImageVector?, val bg: Brush, val text: String? = null)

private fun platformIcon(key: String): PlatformIcon = when (key) {
    "whatsapp" -> PlatformIcon(Icons.AutoMirrored.Outlined.Chat, SolidColor(ChannelColors.WhatsApp))
    "messenger" -> PlatformIcon(Icons.Outlined.Forum, SolidColor(Palette.MessengerTile))
    "instagram" -> PlatformIcon(
        Icons.Outlined.PhotoCamera,
        Brush.linearGradient(Palette.InstagramGradient),
    )
    "mpesa" -> PlatformIcon(null, SolidColor(Palette.MpesaGreen), "M-PESA")
    "email" -> PlatformIcon(Icons.Outlined.Email, SolidColor(Palette.Indigo500))
    "slack" -> PlatformIcon(Icons.Outlined.Tag, SolidColor(Palette.SlackAubergine))
    else -> PlatformIcon(Icons.Outlined.TableChart, SolidColor(Palette.SheetsGreen))
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun IntegrationsCard(vm: SettingsViewModel, twoCols: Boolean) {
    val integrations by vm.integrations.collectAsStateWithLifecycle()
    val config by vm.integConfig.collectAsStateWithLifecycle()
    var expanded by rememberSaveable(key = ke.co.bethanyhouse.neema.feature.reports.keptKey("settings.integration")) { mutableStateOf<String?>(null) }
    val c = Neema.colors
    SectionCard("Integrations", "Connected platforms and services") {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            integrations.forEach { integ ->
                val isExpanded = expanded == integ.key
                val icon = platformIcon(integ.key)
                val cfg = config[integ.key] ?: emptyMap()
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).border(1.dp, if (c.isDark) c.hairline else c.bg3, RoundedCornerShape(12.dp))) {
                  BoxWithConstraints(Modifier.fillMaxWidth()) {
                    // Too narrow for name and buttons abreast (a phone at a large font): the buttons go under the name.
                    val stacked = isCramped(maxWidth, 330.dp)
                    val actions = @Composable {
                        if (integ.fields.isNotEmpty()) {
                            SmallPillButton(if (isExpanded) "Close" else "Configure", c.gold, if (isExpanded) c.bg3 else c.bg2, c.border) {
                                expanded = if (isExpanded) null else integ.key
                            }
                        }
                        if (integ.connected) SmallPillButton(
                            "Disconnect", c.red,
                            if (c.isDark) c.redDim else Palette.DangerWash, if (c.isDark) c.red.copy(alpha = 0.3f) else Palette.Red200,
                        ) { vm.toggleIntegration(integ.key) }
                        else SmallPillButton("Connect", c.gold, c.goldDim, c.border) { vm.toggleIntegration(integ.key) }
                    }
                  Column {
                    Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(36.dp).clip(RoundedCornerShape(12.dp)).background(icon.bg), contentAlignment = Alignment.Center) {
                            if (icon.icon != null) Icon(icon.icon, null, tint = Color.White, modifier = Modifier.size(20.dp))
                            // A logo, not text: it keeps its size inside the 36dp tile at any font scale.
                            else Text(icon.text ?: "", color = Color.White, fontSize = with(androidx.compose.ui.platform.LocalDensity.current) { 7.dp.toSp() }, fontWeight = FontWeight.Bold, maxLines = 1)
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(integ.name, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = c.text, maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 16.sp)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(Modifier.size(6.dp).clip(CircleShape).background(if (integ.connected) c.gold else Palette.Stone300))
                                Spacer(Modifier.width(5.dp))
                                Text(if (integ.connected) "Connected" else "Not connected", fontSize = 11.sp, fontWeight = FontWeight.Medium,
                                    color = if (integ.connected) c.gold else c.muted, maxLines = 1)
                                Text(" · ${integ.description}", fontSize = 11.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        if (!stacked) {
                            Spacer(Modifier.width(6.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) { actions() }
                        }
                    }
                    if (stacked) {
                        FlowRow(
                            Modifier.padding(start = 60.dp, end = 12.dp, bottom = 10.dp),
                            horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) { actions() }
                    }
                  }
                  }
                    if (isExpanded) {
                        HorizontalDivider(color = c.bg3)
                        Column(Modifier.fillMaxWidth().background(c.bg).padding(14.dp)) {
                            val perRow = if (twoCols) 2 else 1
                            integ.fields.chunked(perRow).forEach { row ->
                                // (perRow is 2 only on the two-column layout, where the card is wide enough.)
                                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                    row.forEach { f ->
                                        Field(f.label, modifier = Modifier.weight(1f)) {
                                            SmallInput(cfg[f.key] ?: "", { v -> vm.setConfig(integ.key, f.key, v) }, f.placeholder, secret = f.secret)
                                        }
                                    }
                                    if (row.size < perRow) Spacer(Modifier.weight(1f))
                                }
                            }
                            Button(
                                onClick = { vm.saveIntegConfig(integ.key); expanded = null },
                                shape = RoundedCornerShape(8.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = c.gold, contentColor = Color.White),
                            ) { Text("Save Configuration", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = onGold()) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SmallPillButton(text: String, fg: Color, bg: Color, border: Color, onClick: () -> Unit) {
    // 32dp drawn (the web's px-2.5 py-1.5); Compose widens the touch area to 48dp.
    Text(
        text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = fg, maxLines = 1,
        modifier = Modifier.heightIn(min = 32.dp).clip(RoundedCornerShape(8.dp)).background(bg).border(1.dp, border, RoundedCornerShape(8.dp))
            .clickable(role = Role.Button, onClick = onClick).wrapContentHeight(Alignment.CenterVertically)
            .padding(horizontal = 10.dp, vertical = 7.dp),
    )
}

// ── Danger zone ───────────────────────────────────────────────────────────────

@Composable
private fun DangerZoneCard(vm: SettingsViewModel) {
    val c = Neema.colors
    val light = !c.isDark
    val rowFill = if (light) Palette.Red50 else c.redDim
    val rowEdge = if (light) Palette.Red100 else c.red.copy(alpha = 0.2f)
    val labelColor = if (light) Palette.Red800 else c.red
    val subColor = if (light) Palette.Red500 else c.red.copy(alpha = 0.75f)
    val btnFill = if (light) Palette.Red100 else c.red.copy(alpha = 0.12f)
    val btnText = if (light) Palette.Red700 else c.red
    val btnEdge = if (light) Palette.Red200 else c.red.copy(alpha = 0.3f)
    SectionCard("Danger Zone", "Irreversible actions. Proceed with caution.") {
        listOf(
            Triple("Clear conversation history", "Permanently delete messages older than 90 days", "Clear"),
            Triple("Reset AI memory", "Clear all customer facts and session history", "Reset"),
        ).forEach { (label, sub, action) ->
            Row(
                Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(RoundedCornerShape(8.dp)).background(rowFill)
                    .border(1.dp, rowEdge, RoundedCornerShape(8.dp)).padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = labelColor)
                    Text(sub, fontSize = 11.sp, color = subColor)
                }
                Spacer(Modifier.width(8.dp))
                SmallPillButton(action, btnText, btnFill, btnEdge, vm::dangerAction)
            }
        }
    }
}
