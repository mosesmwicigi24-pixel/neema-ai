package ke.co.bethanyhouse.neema.feature.agents

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import ke.co.bethanyhouse.neema.core.ui.theme.Brand
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

/**
 * Where the Team screen opens: a tab, a dialog ("create", "edit:<id>",
 * "pw:<id>", "del:<id>", "assign:<id>", "role:create", "role:<id>",
 * "delrole:<id>") and what is already typed in it. Only screenshot tests set
 * this — a JVM render cannot tap its way into a dialog.
 */
data class TeamPreview(
    val tab: String? = null,
    val dialog: String? = null,
    val typed: Map<String, String> = emptyMap(),
    /** First grid item shown, to render further down the list. */
    val scrollItem: Int = 0,
)

val LocalTeamPreview = staticCompositionLocalOf { TeamPreview() }

/**
 * SBtn variants from AgentsView.tsx (Primary / Danger / Ghost / Default), plus
 * the shared Btn variants ProfileView.tsx uses: Amber (Btn "primary",
 * bg-amber-500), Secondary (white, gray-700 text, gray-200 border) and
 * Outline (transparent, gray-700 text, gray-300 border).
 */
enum class BtnVariant { Primary, Danger, Ghost, Default, Amber, Secondary, Outline }

/** SBtn danger by day: #fff5f5 fill, #c0392b text, #fecaca border. */
private val DangerFillLight = ke.co.bethanyhouse.neema.feature.reports.AreaPalette.DangerWash
private val DangerBorderLight = Palette.Red200

/** (fill, content, border) for [variant] on the current theme. */
@Composable
fun btnColors(variant: BtnVariant): Triple<Color, Color, Color> {
    val c = Neema.colors
    return when (variant) {
        // By night the moss brightens (#84c13e): white on it is 2:1, so the theme's deep on-primary instead.
        BtnVariant.Primary -> Triple(c.gold, onGold(), c.gold2)
        BtnVariant.Danger -> if (c.isDark) Triple(c.redDim, c.red, c.red.copy(alpha = 0.3f))
            else Triple(DangerFillLight, c.red, DangerBorderLight)
        BtnVariant.Ghost -> Triple(Color.Transparent, c.textDim, c.border)
        BtnVariant.Default -> Triple(c.bg2, c.gold2, c.border)
        // White on amber-500 is 2.1:1; the brand navy on it reads at 7:1.
        BtnVariant.Amber -> Triple(Brand.Amber, Brand.Navy, Brand.Amber)
        BtnVariant.Secondary -> Triple(c.bg2, c.text, c.hairline)
        BtnVariant.Outline -> Triple(Color.Transparent, c.text, if (c.isDark) c.border else Palette.Gray300)
    }
}

/** Text/icons on a [NeemaColors.gold] fill: white by day, the theme's deep on-primary by night. */
@Composable
fun onGold(): Color = if (Neema.colors.isDark) MaterialTheme.colorScheme.onPrimary else Color.White

/** Whichever of white or the brand text colour reads better on [fill] (a role colour, say). */
fun contentOn(fill: Color): Color {
    fun contrast(a: Color, b: Color): Float {
        val la = a.luminance(); val lb = b.luminance()
        return (maxOf(la, lb) + 0.05f) / (minOf(la, lb) + 0.05f)
    }
    val white = contrast(Color.White, fill)
    // White stays unless it falls under 3:1 — the role chips are the web's white-on-colour.
    return if (white >= 3f || white >= contrast(Palette.Ink, fill)) Color.White else Palette.Ink
}

/** True when [width] holds fewer than [minDp] dp of text at the current font scale. */
@Composable
fun isCramped(width: Dp, minDp: Dp): Boolean = width / LocalDensity.current.fontScale < minDp

/**
 * Two fields side by side, each [minEach] wide at font scale 1; when they
 * would be narrower (a 360dp phone, a large font) they stack instead.
 * [second] null leaves the right half empty, as the web's two-column grid does.
 */
@Composable
fun SideBySide(
    first: @Composable (Modifier) -> Unit,
    second: (@Composable (Modifier) -> Unit)?,
    modifier: Modifier = Modifier,
    minEach: Dp = 130.dp,
    spacing: Dp = 12.dp,
) {
    BoxWithConstraints(modifier.fillMaxWidth()) {
        if (isCramped((maxWidth - spacing) / 2, minEach)) {
            Column { first(Modifier.fillMaxWidth()); second?.invoke(Modifier.fillMaxWidth()) }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(spacing)) {
                first(Modifier.weight(1f))
                if (second != null) second(Modifier.weight(1f)) else Spacer(Modifier.weight(1f))
            }
        }
    }
}

@Composable
fun TeamButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: BtnVariant = BtnVariant.Default,
    small: Boolean = false,
    enabled: Boolean = true,
    leading: (@Composable () -> Unit)? = null,
) {
    val (bg, fg, border) = btnColors(variant)
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        // Small buttons sit in a row with 34dp icon buttons (the card footers); a large font may grow them.
        modifier = if (small) modifier.heightIn(min = 34.dp) else modifier.heightIn(min = 40.dp),
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, border),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = bg, contentColor = fg,
            disabledContainerColor = bg.copy(alpha = 0.5f), disabledContentColor = fg.copy(alpha = 0.5f),
        ),
        contentPadding = if (small) PaddingValues(horizontal = 10.dp, vertical = 4.dp) else PaddingValues(horizontal = 14.dp, vertical = 8.dp),
    ) {
        if (leading != null) { leading(); Spacer(Modifier.width(5.dp)) }
        Text(text, fontSize = if (small) 12.sp else 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

/**
 * Which web input a [LabeledInput] reproduces: [Team] is AgentsView's
 * SmallInput (green label, #f3f9ec fill, #b5da8b border); [Form] is the
 * shared InputField ProfileView uses (UPPERCASE tracked grey label, grey-50
 * fill, grey-200 border).
 */
enum class InputStyle { Team, Form }

/** SmallInput / InputField: a labelled single-line field. */
@Composable
fun LabeledInput(
    label: String?,
    value: String,
    onChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String? = null,
    password: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
    isError: Boolean = false,
    supporting: String? = null,
    maxLength: Int? = null,
    style: InputStyle = InputStyle.Team,
    /** Next moves to the following field; the form's last field says Done and closes the keyboard. */
    imeAction: ImeAction = ImeAction.Next,
) {
    val c = Neema.colors
    val form = style == InputStyle.Form
    Column(modifier.fillMaxWidth().padding(bottom = if (form) 12.dp else 10.dp)) {
        if (label != null) {
            if (form) {
                Text(label.uppercase(), fontSize = 12.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.6.sp, color = c.muted)
            } else {
                Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.textDim)
            }
            Spacer(Modifier.height(6.dp))
        }
        val fill = if (form) c.surface else c.bg
        val edge = if (form) c.hairline else c.border
        OutlinedTextField(
            value = value,
            onValueChange = { v -> onChange(if (maxLength != null) v.take(maxLength) else v) },
            singleLine = true,
            placeholder = placeholder?.let { { Text(it, fontSize = 14.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis) } },
            visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = if (password) KeyboardType.Password else keyboardType, imeAction = imeAction),
            isError = isError,
            supportingText = supporting?.let { { Text(it, fontSize = 11.sp) } },
            shape = RoundedCornerShape(10.dp),
            textStyle = LocalTextStyle.current.copy(fontSize = 14.sp, color = c.text),
            colors = OutlinedTextFieldDefaults.colors(
                unfocusedContainerColor = fill, focusedContainerColor = fill, errorContainerColor = fill,
                unfocusedBorderColor = edge,
                focusedBorderColor = if (form) Brand.Amber else c.gold,
                cursorColor = if (form) Brand.Amber else c.gold,
            ),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

/** A native-select look-alike: read-only field that opens a menu. */
@Composable
fun SelectField(
    label: String?,
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    /** The field's fill; null = the surface behind it. */
    container: Color? = null,
) {
    var open by remember { mutableStateOf(false) }
    Column(modifier.fillMaxWidth()) {
        if (label != null) {
            Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.textDim)
            Spacer(Modifier.height(4.dp))
        }
        Box {
            OutlinedButton(
                onClick = { open = true },
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                shape = RoundedCornerShape(10.dp),
                border = BorderStroke(1.dp, Neema.colors.border),
                colors = ButtonDefaults.outlinedButtonColors(
                    containerColor = container ?: Color.Transparent, contentColor = Neema.colors.text,
                ),
            ) {
                Text(options.find { it.first == selected }?.second ?: selected, Modifier.weight(1f), fontSize = 14.sp,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
                Icon(Icons.Default.ArrowDropDown, null)
            }
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                options.forEach { (key, text) ->
                    DropdownMenuItem(text = { Text(text) }, onClick = { onSelect(key); open = false })
                }
            }
        }
    }
}

/**
 * The web's Modal: a titled card with a scrolling body and a button row.
 * Wider than an AlertDialog so the role editor's permission grid fits a phone.
 * It lays itself out inside the system bars and above the keyboard (the body
 * scrolls, the title and buttons stay), and the buttons wrap onto a second
 * line rather than squeeze at a large font.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FormDialog(
    title: String,
    onDismiss: () -> Unit,
    buttons: @Composable RowScope.() -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = Neema.colors.bg2,
            modifier = Modifier.windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(16.dp).widthIn(max = 560.dp).fillMaxWidth(),
        ) {
            Column(Modifier.padding(20.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(14.dp))
                Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()), content = content)
                Spacer(Modifier.height(14.dp))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    content = buttons,
                )
            }
        }
    }
}
