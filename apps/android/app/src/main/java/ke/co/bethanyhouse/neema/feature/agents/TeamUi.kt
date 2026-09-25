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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import ke.co.bethanyhouse.neema.core.ui.theme.Neema

/** SBtn variants from AgentsView.tsx. */
enum class BtnVariant { Primary, Danger, Ghost, Default }

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
    val c = Neema.colors
    val (bg, fg, border) = when (variant) {
        BtnVariant.Primary -> Triple(c.gold, Color.White, c.gold2)
        BtnVariant.Danger -> Triple(c.redDim, c.red, c.red.copy(alpha = 0.3f))
        BtnVariant.Ghost -> Triple(Color.Transparent, c.textDim, c.border)
        BtnVariant.Default -> Triple(c.bg2, c.gold2, c.border)
    }
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = if (small) 32.dp else 40.dp),
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

/** SmallInput: a labelled single-line field. */
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
) {
    Column(modifier.fillMaxWidth().padding(bottom = 10.dp)) {
        if (label != null) {
            Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.textDim)
            Spacer(Modifier.height(4.dp))
        }
        OutlinedTextField(
            value = value,
            onValueChange = { v -> onChange(if (maxLength != null) v.take(maxLength) else v) },
            singleLine = true,
            placeholder = placeholder?.let { { Text(it, fontSize = 13.sp) } },
            visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = if (password) KeyboardType.Password else keyboardType),
            isError = isError,
            supportingText = supporting?.let { { Text(it, fontSize = 11.sp) } },
            shape = RoundedCornerShape(10.dp),
            textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
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
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.onSurface),
            ) {
                Text(options.find { it.first == selected }?.second ?: selected, Modifier.weight(1f), fontSize = 14.sp)
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
 */
@Composable
fun FormDialog(
    title: String,
    onDismiss: () -> Unit,
    buttons: @Composable RowScope.() -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = Neema.colors.bg2,
            modifier = Modifier.padding(16.dp).widthIn(max = 560.dp).fillMaxWidth(),
        ) {
            Column(Modifier.padding(20.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(14.dp))
                Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()), content = content)
                Spacer(Modifier.height(14.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically, content = buttons)
            }
        }
    }
}
