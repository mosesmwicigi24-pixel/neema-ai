package ke.co.bethanyhouse.neema.feature.profile

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.NotificationsActive
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.BuildConfig
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.ConfirmDialog
import ke.co.bethanyhouse.neema.core.ui.components.Panel
import ke.co.bethanyhouse.neema.core.ui.components.Pill
import ke.co.bethanyhouse.neema.core.ui.components.StatTile
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.agents.BtnVariant
import ke.co.bethanyhouse.neema.feature.agents.LabeledInput
import ke.co.bethanyhouse.neema.feature.agents.PermissionCatalog
import ke.co.bethanyhouse.neema.feature.agents.TeamButton
import ke.co.bethanyhouse.neema.feature.agents.hexColor

/** The web's #9ccd65 secondary text; on the dark theme that stand-in is unreadable, so the muted grey-green instead. */
private val ke.co.bethanyhouse.neema.core.ui.theme.NeemaColors.faint: Color get() = if (isDark) muted else border2

/** Which parts of Profile start open — set only by screenshot tests, which cannot tap. */
data class ProfilePreview(
    val editMode: Boolean = false,
    val changingPassword: Boolean = false,
    val confirmSignOut: Boolean = false,
    val typed: Map<String, String> = emptyMap(),
    /** Initial scroll offset in px, to render a lower part of the page. */
    val scroll: Int = 0,
)

val LocalProfilePreview = staticCompositionLocalOf { ProfilePreview() }

/**
 * Port of ProfileView.tsx plus the account menu from Sidebar.tsx (identity,
 * Settings link, theme, Sign out) and the Android-only device settings:
 * background connection, system notification settings, app version.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(dash: DashboardViewModel) {
    val vm: ProfileViewModel = viewModel { ProfileViewModel(dash) }
    val me by dash.me.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    val session by dash.session.collectAsStateWithLifecycle()
    val dark by dash.dark.collectAsStateWithLifecycle()
    val backgroundLive by dash.container.prefs.backgroundLive.collectAsStateWithLifecycle()
    val saving by vm.saving.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val notifs by vm.notifs.collectAsStateWithLifecycle()
    val availableOverride by vm.availableOverride.collectAsStateWithLifecycle()
    val c = Neema.colors
    val context = LocalContext.current

    // The team row carries the custom role and its permissions (GET /admin/agents
    // joins custom_roles; /me is the bare agent), so permissions come from it.
    val teamRow = agents.find { it.id == me?.id }
        ?: agents.find { it.email.equals(session?.email, ignoreCase = true) }
    val agent = me ?: teamRow
    LaunchedEffect(agent?.isAvailable) { vm.reconcile(agent?.isAvailable) }

    if (agent == null) {
        Box(Modifier.fillMaxSize().background(c.bg), contentAlignment = Alignment.Center) {
            Text("Loading profile…", fontSize = 14.sp, color = c.faint)
        }
        return
    }

    val permKeys = Perms.of(teamRow ?: agent)
    val available = availableOverride ?: agent.isAvailable
    val preview = LocalProfilePreview.current
    var editMode by rememberSaveable { mutableStateOf(preview.editMode) }
    var changingPassword by rememberSaveable { mutableStateOf(preview.changingPassword) }
    var confirmSignOut by rememberSaveable { mutableStateOf(preview.confirmSignOut) }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize().background(c.bg)) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState(preview.scroll)).padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // The web caps this page at max-w-2xl; tablets keep that reading width.
            Column(Modifier.widthIn(max = 720.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Column {
                    Text("Profile", style = MaterialTheme.typography.headlineSmall, color = c.text)
                    Text("Manage your account and preferences", fontSize = 13.sp, color = c.faint)
                }

                // ── Profile card ────────────────────────────────────────────
                Panel(Modifier.fillMaxWidth(), padding = PaddingValues(18.dp)) {
                    Row(verticalAlignment = Alignment.Top) {
                        Avatar(agent.name, agent.avatarUrl, size = 56.dp)
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(agent.name, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = c.text, modifier = Modifier.weight(1f, fill = false))
                                Spacer(Modifier.width(8.dp))
                                Pill(
                                    agent.role.replaceFirstChar { it.uppercase() },
                                    if (agent.role == "admin") (if (c.isDark) Color(0xFFC084FC) else Color(0xFF7E22CE)) else c.gold2,
                                )
                            }
                            teamRow?.roleName?.let { rn ->
                                Spacer(Modifier.height(4.dp))
                                Pill(rn, hexColor(teamRow.roleColor), filled = true)
                            }
                            Text(agent.email, fontSize = 13.sp, color = c.faint, modifier = Modifier.padding(top = 2.dp))
                            Text(
                                buildString {
                                    append("Joined ${if (agent.createdAt != null) Fmt.date(agent.createdAt) else "—"}")
                                    if (agent.lastSeenAt != null) append(" · Last active ${Fmt.date(agent.lastSeenAt)}")
                                },
                                fontSize = 12.sp, color = c.faint, modifier = Modifier.padding(top = 4.dp),
                            )
                        }
                        TeamButton(if (editMode) "Cancel" else "Edit", { editMode = !editMode }, small = true,
                            variant = if (editMode) BtnVariant.Ghost else BtnVariant.Default)
                    }
                    if (editMode) {
                        Spacer(Modifier.height(14.dp))
                        HorizontalDivider(color = c.bg3)
                        Spacer(Modifier.height(14.dp))
                        EditProfileForm(
                            initialName = agent.name, initialEmail = agent.email, agentId = agent.id, saving = saving,
                            onSave = { n, e -> vm.saveProfile(n, e) { editMode = false } },
                            onCancel = { editMode = false },
                        )
                    }
                }

                // ── Stats ───────────────────────────────────────────────────
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    StatTile("Active chats", agent.activeConvs.toString(), Modifier.weight(1f))
                    StatTile(
                        "Status", if (available) "Online" else "Away", Modifier.weight(1f),
                        accent = if (available) c.gold else c.muted,
                        hint = if (!available && agent.lastSeenAt != null) "Seen ${Fmt.timeAgo(agent.lastSeenAt)}" else null,
                    )
                    StatTile("Permissions", "${permKeys.count { k -> PermissionCatalog.ALL.any { it.key == k } }}/${PermissionCatalog.ALL.size}", Modifier.weight(1f))
                }

                // ── Availability ────────────────────────────────────────────
                ProfileCard("Availability") {
                    ToggleRow(
                        "Available",
                        if (available) "You're online — the team sees you as available and chats can be transferred to you."
                        else "You're away — shown as offline to the team.",
                        available,
                    ) { vm.setAvailable(agent.id, !available) }
                }

                // ── Password ────────────────────────────────────────────────
                Panel(Modifier.fillMaxWidth(), padding = PaddingValues(18.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Password", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                            Text("Change your login password", fontSize = 12.sp, color = c.faint)
                        }
                        TeamButton(if (changingPassword) "Cancel" else "Change", { changingPassword = !changingPassword }, small = true)
                    }
                    if (changingPassword) {
                        Spacer(Modifier.height(14.dp))
                        PasswordForm(saving) { pw, confirm -> vm.changePassword(pw, confirm) { changingPassword = false } }
                    }
                }

                // ── Appearance ──────────────────────────────────────────────
                ProfileCard("Appearance") {
                    ToggleRow("Dark Mode", "Switch to dark theme", dark) { dash.setDark(!dark) }
                }

                // ── Notifications ───────────────────────────────────────────
                ProfileCard("Notifications") {
                    NOTIF_PREFS.forEachIndexed { i, p ->
                        if (i > 0) Spacer(Modifier.height(14.dp))
                        ToggleRow(p.label, p.desc, notifs[p.key] ?: p.default) { vm.toggleNotif(p.key) }
                    }
                    Spacer(Modifier.height(14.dp))
                    HorizontalDivider(color = c.bg3)
                    Spacer(Modifier.height(14.dp))
                    ToggleRow(
                        "Stay connected in background",
                        "Keeps alerts and incoming calls arriving when the app is closed. Android shows a small " +
                            "ongoing notification while this is on; turn it off to save battery — you'll then only " +
                            "hear about new chats and calls while Neema is open.",
                        backgroundLive,
                    ) { dash.container.prefs.setBackgroundLive(!backgroundLive) }
                    Spacer(Modifier.height(8.dp))
                    LinkRow(Icons.Outlined.NotificationsActive, "System notification settings", "Sounds, pop-ups and which alerts Android shows") {
                        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                            .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        runCatching { context.startActivity(intent) }
                    }
                }

                // ── Permissions ─────────────────────────────────────────────
                ProfileCard("Your Permissions") {
                    PermissionCatalog.ALL.chunked(2).forEach { pair ->
                        Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            pair.forEach { p ->
                                val has = p.key in permKeys
                                Row(
                                    Modifier.weight(1f).clip(RoundedCornerShape(8.dp))
                                        .background(if (has) c.goldDim else c.bg)
                                        .border(1.dp, if (has) c.border else c.bg4, RoundedCornerShape(8.dp))
                                        .padding(10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Box(Modifier.size(6.dp).clip(CircleShape).background(if (has) c.gold else Color(0xFFD6D3D1)))
                                    Spacer(Modifier.width(8.dp))
                                    Text(p.label, fontSize = 12.sp, color = if (has) c.gold2 else c.faint)
                                }
                            }
                            if (pair.size == 1) Spacer(Modifier.weight(1f))
                        }
                    }
                }

                // ── Account (the sidebar's account menu) ────────────────────
                ProfileCard("Account") {
                    if (dash.can(Perms.MANAGE_SETTINGS)) {
                        LinkRow(Icons.Outlined.Settings, "Settings", "Platform configuration and integrations") { dash.navigate(ViewId.Settings) }
                        Spacer(Modifier.height(4.dp))
                    }
                    LinkRow(Icons.Outlined.Info, "App version", "Neema for Android ${BuildConfig.VERSION_NAME}", chevron = false) {}
                    Spacer(Modifier.height(12.dp))
                    Button(
                        onClick = { confirmSignOut = true },
                        colors = ButtonDefaults.buttonColors(containerColor = c.redDim, contentColor = c.red),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.AutoMirrored.Outlined.Logout, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("Sign out", fontWeight = FontWeight.SemiBold)
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }

    if (confirmSignOut) {
        ConfirmDialog(
            title = "Sign out?",
            message = "You'll stop receiving chats, alerts and calls on this device until you sign in again.",
            confirmLabel = "Sign out",
            destructive = true,
            onConfirm = { dash.logout() },
            onDismiss = { confirmSignOut = false },
        )
    }
}

@Composable
private fun EditProfileForm(
    initialName: String,
    initialEmail: String,
    agentId: String,
    saving: Boolean,
    onSave: (String, String) -> Unit,
    onCancel: () -> Unit,
) {
    var name by rememberSaveable(agentId) { mutableStateOf(initialName) }
    var email by rememberSaveable(agentId) { mutableStateOf(initialEmail) }
    // The web shows a Department field but never sends it (PATCH /me has no
    // such column); it is kept for parity and stays on this form only.
    var department by rememberSaveable(agentId) { mutableStateOf("") }
    LabeledInput("Full Name", name, { name = it })
    LabeledInput("Email", email, { email = it }, keyboardType = KeyboardType.Email)
    LabeledInput("Department", department, { department = it }, placeholder = "Sales, Support…")
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        TeamButton(if (saving) "Saving…" else "Save Changes", { onSave(name, email) }, variant = BtnVariant.Primary, enabled = !saving)
        TeamButton("Cancel", onCancel, variant = BtnVariant.Ghost)
    }
}

@Composable
private fun PasswordForm(saving: Boolean, onSubmit: (String, String) -> Unit) {
    val typed = LocalProfilePreview.current.typed
    var pw by rememberSaveable { mutableStateOf(typed["password"] ?: "") }
    var confirm by rememberSaveable { mutableStateOf(typed["confirm"] ?: "") }
    LabeledInput("New Password", pw, { pw = it }, placeholder = "Minimum 8 characters", password = true)
    LabeledInput("Confirm Password", confirm, { confirm = it }, password = true)
    TeamButton(if (saving) "Changing…" else "Change Password", { onSubmit(pw, confirm) }, variant = BtnVariant.Primary, enabled = !saving)
}

@Composable
private fun ProfileCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Panel(Modifier.fillMaxWidth(), padding = PaddingValues(18.dp)) {
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.text)
        Spacer(Modifier.height(14.dp))
        content()
    }
}

@Composable
private fun ToggleRow(label: String, desc: String, checked: Boolean, onToggle: () -> Unit) {
    val c = Neema.colors
    Row(Modifier.fillMaxWidth().clickable(onClick = onToggle), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = c.text)
            Text(desc, fontSize = 12.sp, color = c.faint, lineHeight = 16.sp)
        }
        Spacer(Modifier.width(12.dp))
        Switch(checked = checked, onCheckedChange = { onToggle() })
    }
}

@Composable
private fun LinkRow(icon: ImageVector, label: String, desc: String, chevron: Boolean = true, onClick: () -> Unit) {
    val c = Neema.colors
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable(enabled = chevron, onClick = onClick).padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = c.textDim, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(label, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = c.text)
            Text(desc, fontSize = 12.sp, color = c.faint)
        }
        if (chevron) Icon(Icons.Outlined.ChevronRight, null, tint = c.muted)
    }
}
