package ke.co.bethanyhouse.neema.feature.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.reports.friendlyError
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** One row of GET /admin/client-crashes (routers/admin.py client_crash_list). */
@Serializable
data class ClientCrashReport(
    val id: String = "",
    val kind: String = "crash",
    val at: String? = null,
    @SerialName("received_at") val receivedAt: String? = null,
    @SerialName("agent_name") val agentName: String? = null,
    val summary: String = "",
    val trace: String = "",
    val thread: String? = null,
    @SerialName("app_version") val appVersion: String? = null,
    val build: String? = null,
    val device: String? = null,
    val sdk: Int? = null,
)

/**
 * The Android app's crash reports, as the server keeps them: what failed, on
 * which device and build, and the full trace — selectable, with a Copy that
 * puts it on the clipboard to send on. Loaded on tap only (admins: the
 * server's manage_settings), so Settings itself never waits on it.
 */
@Composable
internal fun CrashReportsCard(dash: DashboardViewModel) {
    val c = Neema.colors
    val scope = rememberCoroutineScope()
    var reports by remember { mutableStateOf<List<ClientCrashReport>?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    val clipboard = LocalClipboardManager.current

    fun load() {
        if (loading) return
        loading = true; error = null
        scope.launch {
            try {
                reports = dash.api.http.get<List<ClientCrashReport>>("/admin/client-crashes?limit=20")
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                error = "Couldn't load the crash reports. ${friendlyError(e)}"
            } finally { loading = false }
        }
    }

    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.bg2)
            .border(1.dp, if (c.isDark) c.hairline else c.bg4, RoundedCornerShape(12.dp)).padding(20.dp),
    ) {
        Text("App crash reports", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text)
        Text(
            "When the Android app closes on someone, it sends what went wrong here. Copy a report and send it on to get it fixed.",
            fontSize = 12.sp, color = c.textDim, lineHeight = 18.sp, modifier = Modifier.padding(top = 4.dp),
        )
        Spacer(Modifier.height(12.dp))
        TextButton(onClick = ::load, enabled = !loading) {
            Text(if (loading) "Loading…" else if (reports == null) "Show crash reports" else "Refresh")
        }
        error?.let { Text(it, fontSize = 12.sp, color = c.red) }
        val list = reports
        if (list != null && list.isEmpty()) Text("No crash reports — nothing has closed on anyone.", fontSize = 12.sp, color = c.textDim)
        list?.forEach { r ->
            val expanded = open == r.id
            Column(
                Modifier.fillMaxWidth().padding(top = 8.dp).clip(RoundedCornerShape(8.dp)).background(c.bg)
                    .clickable(role = Role.Button) { open = if (expanded) null else r.id }.padding(12.dp),
            ) {
                Text(r.summary.ifBlank { r.kind }, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = c.text, maxLines = if (expanded) 6 else 2)
                Text(
                    listOfNotNull(
                        (r.at ?: r.receivedAt)?.let { Fmt.timeAgo(it) },
                        r.agentName, r.device, r.sdk?.let { "Android API $it" }, r.build?.let { "build $it" },
                        if (r.kind != "crash") r.kind else null,
                    ).joinToString(" · "),
                    fontSize = 11.sp, color = c.muted,
                )
                if (expanded) {
                    Spacer(Modifier.height(8.dp))
                    SelectionContainer {
                        Text(
                            r.trace, fontSize = 11.sp, fontFamily = FontFamily.Monospace, color = c.textDim, lineHeight = 14.sp,
                            modifier = Modifier.heightIn(max = 320.dp).verticalScroll(rememberScrollState()).horizontalScroll(rememberScrollState()),
                        )
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TextButton(onClick = {
                            val text = buildString {
                                appendLine(r.summary)
                                appendLine(listOfNotNull(r.at, r.device, r.sdk?.let { "API $it" }, r.appVersion, r.build).joinToString(" · "))
                                append(r.trace)
                            }
                            clipboard.setText(AnnotatedString(text))
                            dash.toast("Crash report copied")
                        }) { Text("Copy report") }
                        Spacer(Modifier.width(4.dp))
                    }
                }
            }
        }
    }
}
