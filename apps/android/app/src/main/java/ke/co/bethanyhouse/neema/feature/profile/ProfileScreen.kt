package ke.co.bethanyhouse.neema.feature.profile

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.ImeAction
import ke.co.bethanyhouse.neema.feature.agents.isCramped
import ke.co.bethanyhouse.neema.feature.agents.contentOn
import ke.co.bethanyhouse.neema.core.ui.components.neemaSwitchColors
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.feature.reports.AreaPalette
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
import ke.co.bethanyhouse.neema.feature.agents.InputStyle
import ke.co.bethanyhouse.neema.feature.agents.LabeledInput
import ke.co.bethanyhouse.neema.feature.agents.PermissionCatalog
import ke.co.bethanyhouse.neema.feature.agents.TeamButton
import ke.co.bethanyhouse.neema.feature.agents.hexColor

/**
 * The web's #9ccd65 secondary text reads at 1.9:1 on white, and is unreadable
 * by night: the theme's secondary green by day and the muted grey-green by
 * night keep the quiet tone at a legible contrast.
 */
private val ke.co.bethanyhouse.neema.core.ui.theme.NeemaColors.faint: Color get() = if (isDark) muted else textDim

/** A permission you hold: the web's #2c4e18 on #f0f9ec. */
private val HasPermText = Palette.Moss800

/**
 * The role chip beside your name: `capitalize`d DB role; admin in purple
 * (purple-100 / purple-700 / purple-200 border), anyone else in the pale
 * greens (#e6f3d8 / #427425 / #cee6b2 border).
 */
@Composable
private fun BaseRoleBadge(role: String) {
    val c = Neema.colors
    val admin = role == "admin"
    val (fill, text, edge) = when {
        admin && c.isDark -> Triple(AreaPalette.Purple500.copy(alpha = 0.2f), AreaPalette.Purple300, AreaPalette.Purple500.copy(alpha = 0.4f))
        admin -> Triple(AreaPalette.Purple100, AreaPalette.Purple700, AreaPalette.Purple200)
        c.isDark -> Triple(c.goldDim, c.gold2, c.border)
        else -> Triple(c.bg3, c.gold2, c.bg4)
    }
    Text(
        role.replaceFirstChar { it.uppercase() }, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = text, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(fill).border(1.dp, edge, RoundedCornerShape(50))
            .padding(horizontal = 8.dp, vertical = 2.dp),
    )
}

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
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
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
        val loadError by vm.loadError.collectAsStateWithLifecycle()
        Box(Modifier.fillMaxSize().background(c.bg).padding(16.dp), contentAlignment = Alignment.Center) {
            val why = loadError
            if (why == null) Text("Loading profile…", fontSize = 14.sp, color = c.faint)
            else ke.co.bethanyhouse.neema.feature.reports.LoadProblem(
                title = "Couldn't load your profile", message = why,
                retrying = refreshing, onRetry = vm::refresh, modifier = Modifier.widthIn(max = 480.dp),
            )
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
      BoxWithConstraints(Modifier.fillMaxSize()) {
        // A 360dp phone at a large font: the header stacks, the tiles go one per line, the permission grid one column.
        val compact = isCramped(minOf(maxWidth, 720.dp) - 32.dp, 300.dp)
        val stackTiles = isCramped(minOf(maxWidth, 720.dp) - 32.dp, 260.dp)
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
                Panel(Modifier.fillMaxWidth(), padding = PaddingValues(20.dp)) {
                    val editButton = @Composable {
                        TeamButton(if (editMode) "Cancel" else "Edit", { editMode = !editMode }, small = true,
                            variant = if (editMode) BtnVariant.Outline else BtnVariant.Secondary)
                    }
                    val details = @Composable { m: Modifier ->
                        Column(m) {
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(agent.name, fontSize = 16.sp, fontWeight = FontWeight.Bold, color = c.text,
                                    modifier = Modifier.align(Alignment.CenterVertically))
                                Box(Modifier.align(Alignment.CenterVertically)) { BaseRoleBadge(agent.role) }
                            }
                            teamRow?.roleName?.let { rn ->
                                Spacer(Modifier.height(4.dp))
                                RoleChip(rn, hexColor(teamRow.roleColor))
                            }
                            Text(agent.email, fontSize = 14.sp, color = c.faint, modifier = Modifier.padding(top = 2.dp))
                            Text(
                                buildString {
                                    append("Joined ${if (agent.createdAt != null) Fmt.date(agent.createdAt) else "—"}")
                                    if (agent.lastSeenAt != null) append(" · Last active ${Fmt.date(agent.lastSeenAt)}")
                                },
                                fontSize = 12.sp, color = c.faint, modifier = Modifier.padding(top = 4.dp),
                            )
                        }
                    }
                    if (compact) {
                        // Avatar and Edit on one line, the name and details under them at full width.
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Avatar(agent.name, agent.avatarUrl, size = 56.dp)
                            Spacer(Modifier.weight(1f))
                            editButton()
                        }
                        Spacer(Modifier.height(12.dp))
                        details(Modifier.fillMaxWidth())
                    } else {
                        Row(verticalAlignment = Alignment.Top) {
                            Avatar(agent.name, agent.avatarUrl, size = 56.dp)
                            Spacer(Modifier.width(16.dp))
                            details(Modifier.weight(1f))
                            Spacer(Modifier.width(8.dp))
                            editButton()
                        }
                    }
                    if (editMode) {
                        Spacer(Modifier.height(20.dp))
                        HorizontalDivider(color = c.bg3)
                        Spacer(Modifier.height(16.dp))
                        EditProfileForm(
                            initialName = agent.name, initialEmail = agent.email, agentId = agent.id, saving = saving,
                            onSave = { n, e -> vm.saveProfile(n, e) { editMode = false } },
                            onCancel = { editMode = false },
                        )
                    }
                }

                // ── Stats ───────────────────────────────────────────────────
                val tiles = listOf<@Composable (Modifier) -> Unit>(
                    { m -> StatTile("Active chats", agent.activeConvs.toString(), m) },
                    { m ->
                        StatTile(
                            "Status", if (available) "Online" else "Away", m,
                            accent = if (available) c.gold else c.muted,
                            hint = if (!available && agent.lastSeenAt != null) "Seen ${Fmt.timeAgo(agent.lastSeenAt)}" else null,
                        )
                    },
                    { m -> StatTile("Permissions", "${permKeys.count { k -> PermissionCatalog.ALL.any { it.key == k } }}/${PermissionCatalog.ALL.size}", m) },
                )
                if (stackTiles) {
                    // Three abreast would cut "Active chats" and "20/20" short at this size.
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { tiles.forEach { it(Modifier.fillMaxWidth()) } }
                } else {
                    // One height for the three tiles, even when Status carries a "Seen …" line.
                    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        tiles.forEach { it(Modifier.weight(1f).fillMaxHeight()) }
                    }
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
                Panel(Modifier.fillMaxWidth(), padding = PaddingValues(20.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Password", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                            Text("Change your login password", fontSize = 12.sp, color = c.faint)
                        }
                        Spacer(Modifier.width(8.dp))
                        TeamButton(if (changingPassword) "Cancel" else "Change", { changingPassword = !changingPassword }, small = true,
                            variant = BtnVariant.Secondary)
                    }
                    if (changingPassword) {
                        Spacer(Modifier.height(16.dp))
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
                    val perRow = if (compact) 1 else 2
                    PermissionCatalog.ALL.chunked(perRow).forEach { pair ->
                        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min).padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            pair.forEach { p ->
                                val has = p.key in permKeys
                                Row(
                                    Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(8.dp))
                                        .background(if (has) c.goldDim else c.bg)
                                        .border(1.dp, if (has) c.border else c.bg4, RoundedCornerShape(8.dp))
                                        .padding(10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Box(Modifier.size(6.dp).clip(CircleShape).background(if (has) c.gold else Palette.Stone300))
                                    Spacer(Modifier.width(8.dp))
                                    Text(p.label, fontSize = 12.sp, color = if (has) (if (c.isDark) c.gold2 else HasPermText) else c.faint)
                                }
                            }
                            if (pair.size < perRow) Spacer(Modifier.weight(1f))
                        }
                    }
                }

                // ── Account (the sidebar's account menu) ────────────────────
                ProfileCard("Account") {
                    // Sidebar.tsx's account menu offers Settings to everyone; the server refuses a non-admin's saves.
                    LinkRow(Icons.Outlined.Settings, "Settings", "Platform configuration and integrations") { dash.navigate(ViewId.Settings) }
                    Spacer(Modifier.height(4.dp))
                    LinkRow(Icons.Outlined.Info, "App version", "Neema for Android ${BuildConfig.VERSION_NAME}", chevron = false) {}
                    Spacer(Modifier.height(12.dp))
                    Button(
                        onClick = { confirmSignOut = true },
                        colors = ButtonDefaults.buttonColors(containerColor = c.redDim, contentColor = c.red),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
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

@OptIn(ExperimentalLayoutApi::class)
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
    LabeledInput("Full Name", name, { name = it }, style = InputStyle.Form)
    LabeledInput("Email", email, { email = it }, keyboardType = KeyboardType.Email, style = InputStyle.Form)
    LabeledInput("Department", department, { department = it }, placeholder = "Sales, Support…", style = InputStyle.Form,
        imeAction = ImeAction.Done)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        TeamButton(if (saving) "Saving…" else "Save Changes", { onSave(name, email) }, variant = BtnVariant.Amber, enabled = !saving)
        TeamButton("Cancel", onCancel, variant = BtnVariant.Outline)
    }
}

@Composable
private fun PasswordForm(saving: Boolean, onSubmit: (String, String) -> Unit) {
    val typed = LocalProfilePreview.current.typed
    var pw by rememberSaveable { mutableStateOf(typed["password"] ?: "") }
    var confirm by rememberSaveable { mutableStateOf(typed["confirm"] ?: "") }
    LabeledInput("New Password", pw, { pw = it }, placeholder = "Minimum 8 characters", password = true, style = InputStyle.Form)
    LabeledInput("Confirm Password", confirm, { confirm = it }, password = true, style = InputStyle.Form, imeAction = ImeAction.Done)
    TeamButton(if (saving) "Changing…" else "Change Password", { onSubmit(pw, confirm) }, variant = BtnVariant.Amber, enabled = !saving)
}

/** Your custom role, in its colour, with whichever text colour reads on it. */
@Composable
private fun RoleChip(name: String, fill: Color) {
    Text(
        name, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = contentOn(fill), maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(fill).padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@Composable
private fun ProfileCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Panel(Modifier.fillMaxWidth(), padding = PaddingValues(20.dp)) {
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.text)
        Spacer(Modifier.height(16.dp))
        content()
    }
}

@Composable
private fun ToggleRow(label: String, desc: String, checked: Boolean, onToggle: () -> Unit) {
    val c = Neema.colors
    // The whole row is the switch: one target, read by TalkBack as "label, switch, on".
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).toggleable(checked, role = Role.Switch) { onToggle() },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = c.text)
            Text(desc, fontSize = 12.sp, color = c.faint, lineHeight = 16.sp)
        }
        Spacer(Modifier.width(12.dp))
        Switch(checked = checked, onCheckedChange = null, colors = neemaSwitchColors())
    }
}

@Composable
private fun LinkRow(icon: ImageVector, label: String, desc: String, chevron: Boolean = true, onClick: () -> Unit) {
    val c = Neema.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(RoundedCornerShape(10.dp))
            .clickable(enabled = chevron, role = Role.Button, onClick = onClick).padding(vertical = 8.dp),
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
