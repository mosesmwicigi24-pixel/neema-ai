package ke.co.bethanyhouse.neema.core.crash

import android.content.Intent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * After the app closed on someone: what happened, with Share (WhatsApp, email,
 * anything) and Copy — the exact trace reaches the people who fix it, whoever
 * was using the app, admin or not, online or not. Shown once per crash.
 */
@Composable
fun CrashNotice() {
    var report by remember { mutableStateOf(CrashVault.unseenFatal()) }
    val r = report ?: return
    val ctx = LocalContext.current
    val clipboard = LocalClipboardManager.current
    val text = remember(r) { CrashVault.asText(r) }
    fun done() { CrashVault.seen(); report = null }
    AlertDialog(
        onDismissRequest = ::done,
        title = { Text("Neema closed unexpectedly") },
        text = {
            Column(Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState())) {
                Text("Last time, the app closed because of a problem. Share this report so it can be fixed — it says exactly what went wrong.")
                Text(r.summary.ifBlank { r.kind }, fontFamily = FontFamily.Monospace, fontSize = 12.sp, lineHeight = 16.sp)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                runCatching {
                    val send = Intent(Intent.ACTION_SEND).setType("text/plain")
                        .putExtra(Intent.EXTRA_SUBJECT, "Neema crash report")
                        .putExtra(Intent.EXTRA_TEXT, text)
                    ctx.startActivity(Intent.createChooser(send, "Share the crash report").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
                done()
            }) { Text("Share report") }
        },
        dismissButton = {
            Column {
                TextButton(onClick = { runCatching { clipboard.setText(AnnotatedString(text)) }; done() }) { Text("Copy") }
                TextButton(onClick = ::done) { Text("Close") }
            }
        },
    )
}
