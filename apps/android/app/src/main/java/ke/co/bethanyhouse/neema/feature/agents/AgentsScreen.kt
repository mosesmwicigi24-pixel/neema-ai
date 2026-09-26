package ke.co.bethanyhouse.neema.feature.agents

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.ui.layout.SubcomposeLayout
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Dp
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Key
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.VerifiedUser
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CustomRole
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.EmptyState
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.core.ui.components.Pill
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.core.util.Fmt

/** Port of AgentsView.tsx — the Team screen: agents, custom roles, and the dialogs that edit both. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentsScreen(dash: DashboardViewModel) {
    // The nav hides Team without manage_agents; this guards a stale deep link.
    if (!dash.can(Perms.MANAGE_AGENTS)) {
        EmptyState(
            title = "No access to Team",
            subtitle = "Managing agents needs the “Manage agents” permission.",
            icon = Icons.Outlined.Lock,
        )
        return
    }

    val vm: AgentsViewModel = viewModel { AgentsViewModel(dash) }
    ke.co.bethanyhouse.neema.feature.reports.TrackShown(vm.life)
    // "Last seen 4m ago" keeps counting between polls instead of freezing at first paint.
    var now by remember { mutableLongStateOf(AppClock.now()) }
    LaunchedEffect(Unit) {
        while (true) { kotlinx.coroutines.delay(60_000); now = AppClock.now() }
    }
    val agents by dash.agents.collectAsStateWithLifecycle()
    val roles by vm.roles.collectAsStateWithLifecycle()
    val rolesLoading by vm.rolesLoading.collectAsStateWithLifecycle()
    val saving by vm.saving.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val availability by vm.availability.collectAsStateWithLifecycle()
    LaunchedEffect(agents) { vm.reconcile(agents) }

    val canRoles = dash.can(Perms.MANAGE_ROLES)
    val preview = LocalTeamPreview.current
    fun opened(kind: String): String? = preview.dialog?.takeIf { it.startsWith("$kind:") }?.substringAfter(':')
    var tabChoice by rememberSaveable { mutableStateOf(preview.tab ?: "agents") }
    val tab = if (canRoles) tabChoice else "agents"

    // Which dialog is open, by id, so it survives rotation and resets on leaving the screen.
    var createOpen by rememberSaveable { mutableStateOf(preview.dialog == "create") }
    var editId by rememberSaveable { mutableStateOf(opened("edit")) }
    var pwId by rememberSaveable { mutableStateOf(opened("pw")) }
    var delId by rememberSaveable { mutableStateOf(opened("del")) }
    var assignId by rememberSaveable { mutableStateOf(opened("assign")) }
    /** "create", a role id, or null. */
    var roleModal by rememberSaveable { mutableStateOf(opened("role")) }
    var delRoleId by rememberSaveable { mutableStateOf(opened("delrole")) }

    fun agentById(id: String?) = id?.let { i -> agents.find { it.id == i } }
    fun roleById(id: String?) = id?.let { i -> roles.find { it.id == i } }
    val onlineCount = agents.count { availability[it.id] ?: it.isAvailable }
    val c = Neema.colors

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize().background(c.bg)) {
      BoxWithConstraints(Modifier.fillMaxSize()) {
        // The web's grid: one column on phones, two from sm, three from lg — here
        // as many 320dp columns as fit, never more than three.
        val columns = ((maxWidth - 32.dp + 12.dp) / (320.dp + 12.dp)).toInt().coerceIn(1, 3)
        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
            state = rememberLazyListState(preview.scrollItem),
        ) {
            // Header
            item(key = "header") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Team", style = MaterialTheme.typography.headlineSmall, color = c.text)
                        Row {
                            Text("${agents.size} agents · ", fontSize = 14.sp, color = c.textDim)
                            Text("$onlineCount online", fontSize = 14.sp, color = c.gold)
                        }
                    }
                    if (tab == "agents") {
                        TeamButton("Add Agent", { createOpen = true }, variant = BtnVariant.Primary,
                            leading = { Icon(Icons.Default.Add, null, Modifier.size(16.dp)) })
                    } else {
                        TeamButton("New Role", { roleModal = "create" }, variant = BtnVariant.Primary,
                            leading = { Icon(Icons.Default.Add, null, Modifier.size(16.dp)) })
                    }
                }
            }
            // Tabs
            item(key = "tabs") {
                val tabs = if (canRoles) listOf("agents", "roles") else listOf("agents")
                // The web's tabs: left-aligned labels, a 2dp underline on the active one, over a hairline.
                Box(Modifier.fillMaxWidth()) {
                    HorizontalDivider(Modifier.align(Alignment.BottomStart), color = c.bg4)
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        tabs.forEach { t ->
                            val sel = tab == t
                            Column(
                                Modifier.clip(RoundedCornerShape(topStart = 6.dp, topEnd = 6.dp))
                                    .clickable { tabChoice = t }.width(IntrinsicSize.Max),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Text(
                                    if (t == "agents") "Agents (${agents.size})" else "Roles (${roles.size})",
                                    fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                                    color = if (sel) c.gold2 else c.textDim,
                                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                                )
                                Box(Modifier.fillMaxWidth().height(2.dp).background(if (sel) c.gold else Color.Transparent))
                            }
                        }
                    }
                }
            }

            if (tab == "agents") {
                if (agents.isEmpty()) {
                    item(key = "empty") {
                        Box(Modifier.fillMaxWidth().padding(vertical = 64.dp), contentAlignment = Alignment.Center) {
                            Text("No agents yet.", fontSize = 14.sp, color = c.textDim)
                        }
                    }
                }
                // Cards in a row share its tallest card's height, as a CSS grid row does.
                items(agents.chunked(columns), key = { row -> row.joinToString("|") { it.id } }) { row ->
                    EqualHeightRow(columns = columns, spacing = 12.dp, count = row.size) { i ->
                        val agent = row[i]
                        AgentCard(
                            agent = agent,
                            available = availability[agent.id] ?: agent.isAvailable,
                            customRole = roleById(agent.customRoleId),
                            now = now,
                            onToggle = { vm.toggleOnline(agent, availability[agent.id] ?: agent.isAvailable) },
                            onRole = { assignId = agent.id },
                            onEdit = { editId = agent.id },
                            onPassword = { pwId = agent.id },
                            onDelete = { if (vm.requestRemove(agent)) delId = agent.id },
                        )
                    }
                }
            } else {
                if (rolesLoading && roles.isEmpty()) {
                    item(key = "loading") { Loading(Modifier.height(160.dp)) }
                } else {
                    if (roles.isEmpty()) {
                        item(key = "noroles") {
                            EmptyState("No roles yet", "Create one with New Role.", icon = Icons.Outlined.VerifiedUser)
                        }
                    }
                    // Roles read as a list on the web (space-y-3), full width.
                    items(roles, key = { it.id }) { role ->
                        RoleCard(
                            role = role,
                            agentCount = agents.count { it.customRoleId == role.id },
                            onEdit = { roleModal = role.id },
                            onDelete = { delRoleId = role.id },
                        )
                    }
                }
            }
        }
      }
    }

    // ── Dialogs ───────────────────────────────────────────────────────────────

    agentById(assignId)?.let { a ->
        AssignRoleDialog(a, roles, saving, onDismiss = { assignId = null }) { roleId, perms ->
            vm.saveAssign(a, roleId, perms) { assignId = null }
        }
    }
    if (createOpen) {
        CreateAgentDialog(saving, onDismiss = { createOpen = false }) { name, email, pw, role ->
            vm.createAgent(name, email, pw, role) { createOpen = false }
        }
    }
    agentById(editId)?.let { a ->
        EditAgentDialog(a, saving, onDismiss = { editId = null }) { name, email ->
            vm.saveEdit(a, name, email) { editId = null }
        }
    }
    agentById(pwId)?.let { a ->
        ResetPasswordDialog(a, saving, onDismiss = { pwId = null }) { pw, confirm ->
            vm.savePassword(a, pw, confirm) { pwId = null }
        }
    }
    agentById(delId)?.let { a ->
        FormDialog(
            title = "Remove Agent",
            onDismiss = { delId = null },
            buttons = {
                TeamButton(if (saving) "Removing…" else "Remove Agent", { vm.deleteAgent(a) { delId = null } },
                    variant = BtnVariant.Danger, enabled = !saving)
                TeamButton("Cancel", { delId = null })
            },
        ) {
            Text(buildBold("Remove ", a.name, "?"), fontSize = 14.sp, color = c.text)
            Spacer(Modifier.height(4.dp))
            Text("This cannot be undone. Their conversations will be unassigned.", fontSize = 12.sp, color = c.textDim)
        }
    }
    roleModal?.let { key ->
        val editing = if (key == "create") null else roleById(key)
        if (key == "create" || editing != null) {
            RoleEditorDialog(editing, saving, onDismiss = { roleModal = null }) { form ->
                vm.saveRole(editing, form) { roleModal = null }
            }
        }
    }
    roleById(delRoleId)?.let { r ->
        FormDialog(
            title = "Delete Role",
            onDismiss = { delRoleId = null },
            buttons = {
                TeamButton(if (saving) "Deleting…" else "Delete Role", { vm.deleteRole(r) { delRoleId = null } },
                    variant = BtnVariant.Danger, enabled = !saving)
                TeamButton("Cancel", { delRoleId = null })
            },
        ) {
            Text(buildBold("Delete role ", r.name, "?"), fontSize = 14.sp, color = c.text)
            Spacer(Modifier.height(4.dp))
            Text(
                "${agents.count { it.customRoleId == r.id }} agent(s) will be unassigned from this role.",
                fontSize = 12.sp, color = c.textDim,
            )
        }
    }
}

/** The web's pale greens (#9ccd65, #b5da8b) — legible stand-ins on the dark theme. */
private val faint: Color @Composable get() = Neema.colors.let { if (it.isDark) it.muted else it.border2 }
private val fainter: Color @Composable get() = Neema.colors.let { if (it.isDark) it.muted.copy(alpha = 0.8f) else it.border }
/** Card borders: #cee6b2 by day, the theme hairline by night. */
private val cardBorder: Color @Composable get() = Neema.colors.let { if (it.isDark) it.hairline else it.bg4 }

private fun buildBold(
    pre: String, bold: String, post: String,
    color: Color = Color.Unspecified, weight: FontWeight = FontWeight.Bold,
) = androidx.compose.ui.text.buildAnnotatedString {
    append(pre)
    pushStyle(androidx.compose.ui.text.SpanStyle(fontWeight = weight, color = color)); append(bold); pop()
    append(post)
}

// ── Equal-height row ─────────────────────────────────────────────────────────

/**
 * [count] cells side by side in a [columns]-wide grid row, every cell as tall
 * as the tallest — the CSS grid's stretch. Each cell is measured once at its
 * natural height, then laid out at the row's height. (IntrinsicSize can't be
 * used: the avatar may be a SubcomposeAsyncImage, which has no intrinsics.)
 */
@Composable
internal fun EqualHeightRow(columns: Int, spacing: Dp, count: Int, cell: @Composable (Int) -> Unit) {
    SubcomposeLayout(Modifier.fillMaxWidth()) { constraints ->
        val gap = spacing.roundToPx()
        val width = constraints.maxWidth
        val cellW = ((width - gap * (columns - 1)) / columns).coerceAtLeast(0)
        val loose = Constraints(minWidth = cellW, maxWidth = cellW)
        val height = (0 until count).maxOfOrNull { i ->
            subcompose("measure-$i") { cell(i) }.maxOfOrNull { it.measure(loose).height } ?: 0
        } ?: 0
        val placeables = (0 until count).map { i ->
            subcompose("place-$i") { cell(i) }.map { it.measure(Constraints.fixed(cellW, height)) }
        }
        layout(width, height) {
            placeables.forEachIndexed { i, ps -> ps.forEach { it.place(i * (cellW + gap), 0) } }
        }
    }
}

// ── Agent card ────────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AgentCard(
    agent: Agent,
    available: Boolean,
    customRole: CustomRole?,
    now: Long,
    onToggle: () -> Unit,
    onRole: () -> Unit,
    onEdit: () -> Unit,
    onPassword: () -> Unit,
    onDelete: () -> Unit,
) {
    val c = Neema.colors
    // Before the roles list lands, the agent row already carries its role's name and colour.
    val roleName = customRole?.name ?: agent.roleName?.takeIf { agent.customRoleId != null }
    val roleColor = customRole?.color ?: agent.roleColor
    val rolePermCount = customRole?.permissions?.size ?: agent.rolePermissions?.size
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.bg2)
            .border(1.dp, cardBorder, RoundedCornerShape(12.dp)).padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Box {
                Avatar(agent.name, agent.avatarUrl, size = 44.dp)
                // w-3 h-3 with a 2px white ring, nudged 2px past the avatar's corner.
                Box(
                    Modifier.align(Alignment.BottomEnd).offset(2.dp, 2.dp).size(12.dp).clip(CircleShape).background(c.bg2).padding(2.dp)
                        .clip(CircleShape).background(if (available) Color(0xFF10B981) else Color(0xFFD6D3D1)),
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(agent.name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text,
                        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.align(Alignment.CenterVertically))
                    if (roleName != null) {
                        RoleBadge(roleName, hexColor(roleColor), Color.White, Modifier.align(Alignment.CenterVertically))
                    } else {
                        // The base DB role, capitalised: #e6f3d8 fill, #427425 text.
                        RoleBadge(
                            agent.role.replaceFirstChar { it.uppercase() },
                            if (c.isDark) c.goldDim else c.bg3, c.gold2, Modifier.align(Alignment.CenterVertically),
                        )
                    }
                    if (agent.customPermissions != null) {
                        Pill("Custom permissions", c.blue, modifier = Modifier.align(Alignment.CenterVertically))
                    }
                }
                Text(agent.email, fontSize = 12.sp, color = c.textDim, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    "${agent.activeConvs} active · Joined ${if (agent.createdAt != null) Fmt.date(agent.createdAt) else "—"}",
                    fontSize = 12.sp, color = faint,
                )
                Text(
                    if (available) "Online now" else "Last seen ${Fmt.timeAgo(agent.lastSeenAt, now).let { if (it == "—") "never" else it }}",
                    fontSize = 11.sp, color = if (available) c.gold else c.muted,
                )
                if (roleName != null && rolePermCount != null) {
                    Text(
                        if (agent.customPermissions != null) "${agent.customPermissions.size} permissions (custom for this agent)"
                        else "$rolePermCount permissions assigned",
                        fontSize = 11.sp, color = fainter,
                    )
                }
            }
        }
        // In a stretched grid row the footer sits on the card's bottom edge, so a row's footers line up.
        Spacer(Modifier.weight(1f))
        Spacer(Modifier.height(12.dp))
        HorizontalDivider(color = if (c.isDark) c.hairline else c.bg3)
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Available", fontSize = 12.sp, color = c.textDim)
            Spacer(Modifier.width(8.dp))
            Switch(checked = available, onCheckedChange = { onToggle() }, modifier = Modifier.scale(0.8f))
            Spacer(Modifier.weight(1f))
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                TeamButton("Role", onRole, small = true,
                    leading = { Icon(Icons.Outlined.VerifiedUser, null, Modifier.size(14.dp)) })
                TeamButton("Edit", onEdit, small = true)
                IconBtn(Icons.Outlined.Key, "Reset password", BtnVariant.Ghost, onPassword)
                IconBtn(Icons.Outlined.DeleteOutline, "Remove agent", BtnVariant.Danger, onDelete)
            }
        }
    }
}

@Composable
private fun IconBtn(icon: androidx.compose.ui.graphics.vector.ImageVector, desc: String, variant: BtnVariant, onClick: () -> Unit) {
    val (bg, fg, edge) = btnColors(variant)
    Box(
        Modifier.size(34.dp).clip(RoundedCornerShape(8.dp)).background(bg)
            .border(1.dp, edge, RoundedCornerShape(8.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, desc, tint = fg, modifier = Modifier.size(16.dp)) }
}

// ── Role card ─────────────────────────────────────────────────────────────────

@Composable
private fun RoleSquare(role: CustomRole, size: Int) {
    Box(
        Modifier.size(size.dp).clip(RoundedCornerShape(if (size >= 40) 12.dp else 8.dp)).background(hexColor(role.color)),
        contentAlignment = Alignment.Center,
    ) {
        Text(role.name.take(1).uppercase().ifEmpty { "?" }, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 14.sp)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RoleCard(role: CustomRole, agentCount: Int, onEdit: () -> Unit, onDelete: () -> Unit) {
    val c = Neema.colors
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.bg2)
            .border(1.dp, cardBorder, RoundedCornerShape(12.dp)).padding(16.dp),
        verticalAlignment = Alignment.Top,
    ) {
        RoleSquare(role, 40)
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(role.name, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text, modifier = Modifier.align(Alignment.CenterVertically))
                if (role.protected) ProtectedTag(Modifier.align(Alignment.CenterVertically))
                Text("$agentCount agent${if (agentCount != 1) "s" else ""}", fontSize = 11.sp, color = c.textDim,
                    modifier = Modifier.align(Alignment.CenterVertically))
            }
            if (role.description.isNotBlank()) {
                Text(role.description, fontSize = 12.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp, bottom = 6.dp))
            } else Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                role.permissions.take(8).forEach { p ->
                    PermissionLabel(p)?.let { label -> PermChip(label) }
                }
                if (role.permissions.size > 8) {
                    Text("+${role.permissions.size - 8} more", fontSize = 10.sp, color = c.textDim,
                        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(c.bg3).padding(horizontal = 6.dp, vertical = 2.dp))
                }
                if (role.permissions.isEmpty()) {
                    Text("No permissions assigned", fontSize = 10.sp, fontStyle = FontStyle.Italic, color = faint)
                }
            }
        }
        if (!role.protected) {
            Spacer(Modifier.width(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                TeamButton("Edit", onEdit, small = true)
                IconBtn(Icons.Outlined.DeleteOutline, "Delete role", BtnVariant.Danger, onDelete)
            }
        }
    }
}

private fun PermissionLabel(key: String): String? = PermissionCatalog.label(key)

@Composable
private fun PermChip(label: String) {
    val c = Neema.colors
    Text(
        label, fontSize = 10.sp, fontWeight = FontWeight.Medium, color = c.gold2,
        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(c.goldDim)
            .border(1.dp, c.border, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

/**
 * The role list's tag is an uppercase, tracked, bold pill; the assign
 * dialog's ([compact]) is "Protected" as typed, semibold, on a 4dp-cornered chip.
 */
@Composable
private fun ProtectedTag(modifier: Modifier = Modifier, compact: Boolean = false) {
    val c = Neema.colors
    val fill = if (c.isDark) c.goldDim else c.bg3
    if (compact) {
        Text(
            "Protected", fontSize = 9.sp, fontWeight = FontWeight.SemiBold, color = c.gold2,
            modifier = modifier.clip(RoundedCornerShape(4.dp)).background(fill).padding(horizontal = 4.dp, vertical = 2.dp),
        )
    } else {
        Text(
            "PROTECTED", fontSize = 9.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp, color = c.gold2,
            modifier = modifier.clip(RoundedCornerShape(50)).background(fill).padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}

/** The agent card's role chip: 10px semibold on a full pill (custom role colour, or the base role's pale green). */
@Composable
private fun RoleBadge(text: String, fill: Color, content: Color, modifier: Modifier = Modifier) {
    Text(
        text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = content, maxLines = 1,
        modifier = modifier.clip(RoundedCornerShape(50)).background(fill).padding(horizontal = 7.dp, vertical = 2.dp),
    )
}

// ── Assign role ───────────────────────────────────────────────────────────────

@Composable
private fun AssignRoleDialog(
    agent: Agent,
    roles: List<CustomRole>,
    saving: Boolean,
    onDismiss: () -> Unit,
    onSave: (roleId: String, customPermissions: List<String>?) -> Unit,
) {
    val c = Neema.colors
    var roleId by rememberSaveable(agent.id) { mutableStateOf(agent.customRoleId ?: "") }
    // Per-agent override (agents.custom_permissions): off = exactly the role's permissions.
    var override by rememberSaveable(agent.id) { mutableStateOf(agent.customPermissions != null) }
    var perms by rememberSaveable(agent.id) {
        mutableStateOf(agent.customPermissions ?: roles.find { it.id == agent.customRoleId }?.permissions ?: emptyList())
    }
    FormDialog(
        title = "Assign Role — ${agent.name}",
        onDismiss = onDismiss,
        buttons = {
            TeamButton(if (saving) "Assigning…" else "Assign Role", { onSave(roleId, if (override) perms else null) },
                variant = BtnVariant.Primary, enabled = !saving && roleId.isNotEmpty())
            TeamButton("Cancel", onDismiss)
        },
    ) {
        Text("Select a role. The agent will immediately receive those permissions.", fontSize = 12.sp, color = c.textDim)
        Spacer(Modifier.height(12.dp))
        roles.forEach { role ->
            val sel = roleId == role.id
            Row(
                Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(RoundedCornerShape(12.dp))
                    .background(if (sel) c.bg else c.bg2)
                    .border(if (sel) 2.dp else 1.dp, if (sel) hexColor(role.color) else if (c.isDark) c.hairline else c.bg3, RoundedCornerShape(12.dp))
                    .clickable {
                        roleId = role.id
                        // A fresh override starts from the chosen role's set.
                        if (!override) perms = role.permissions
                    }
                    .padding(12.dp),
                verticalAlignment = Alignment.Top,
            ) {
                RoleSquare(role, 32)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(role.name, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = c.text)
                        if (role.protected) { Spacer(Modifier.width(8.dp)); ProtectedTag(compact = true) }
                    }
                    if (role.description.isNotBlank()) Text(role.description, fontSize = 11.sp, color = c.textDim)
                    Text("${role.permissions.size} permission${if (role.permissions.size != 1) "s" else ""}", fontSize = 11.sp, color = fainter)
                }
                if (sel) Icon(Icons.Default.Check, "Selected", tint = c.gold, modifier = Modifier.size(18.dp))
            }
        }
        if (roles.isEmpty()) Text("No roles yet — create one on the Roles tab.", fontSize = 12.sp, color = c.muted)

        Spacer(Modifier.height(6.dp))
        HorizontalDivider(color = if (c.isDark) c.hairline else c.bg3)
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Custom permissions for this agent", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                Text(
                    if (override) "This agent gets exactly the permissions ticked below, instead of the role's."
                    else "Off — the agent gets the role's permissions.",
                    fontSize = 11.sp, color = c.textDim,
                )
            }
            Switch(checked = override, onCheckedChange = { on ->
                override = on
                if (on && agent.customPermissions == null) perms = roles.find { it.id == roleId }?.permissions ?: perms
            })
        }
        if (override) PermissionPicker(perms) { perms = it }
    }
}

// ── Create / edit / password ─────────────────────────────────────────────────

@Composable
private fun CreateAgentDialog(saving: Boolean, onDismiss: () -> Unit, onCreate: (String, String, String, String) -> Unit) {
    val typed = LocalTeamPreview.current.typed
    var name by rememberSaveable { mutableStateOf(typed["name"] ?: "") }
    var email by rememberSaveable { mutableStateOf(typed["email"] ?: "") }
    var password by rememberSaveable { mutableStateOf(typed["password"] ?: "") }
    var roleId by rememberSaveable { mutableStateOf(typed["role"] ?: "agent") }
    FormDialog(
        title = "Add Agent",
        onDismiss = onDismiss,
        buttons = {
            TeamButton(if (saving) "Creating…" else "Create Agent", { onCreate(name, email, password, roleId) },
                variant = BtnVariant.Primary, enabled = !saving)
            TeamButton("Cancel", onDismiss)
        },
    ) {
        LabeledInput("Full Name", name, { name = it }, placeholder = "Jane Doe")
        LabeledInput("Email", email, { email = it }, placeholder = "jane@bethanyhouse.co.ke",
            keyboardType = androidx.compose.ui.text.input.KeyboardType.Email)
        LabeledInput("Password", password, { password = it }, placeholder = "Min. 8 characters", password = true)
        SelectField(
            "Base Role",
            listOf("agent" to "Agent", "admin" to "Admin", "readonly" to "Read Only"),
            roleId, { roleId = it },
            container = Neema.colors.bg,
        )
        Text(
            "Assign a detailed custom role after creating the agent using the Role button.",
            fontSize = 11.sp, color = faint, modifier = Modifier.padding(top = 4.dp),
        )
    }
}

@Composable
private fun EditAgentDialog(agent: Agent, saving: Boolean, onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    var name by rememberSaveable(agent.id) { mutableStateOf(agent.name) }
    var email by rememberSaveable(agent.id) { mutableStateOf(agent.email) }
    FormDialog(
        title = "Edit — ${agent.name}",
        onDismiss = onDismiss,
        buttons = {
            TeamButton(if (saving) "Saving…" else "Save Changes", { onSave(name, email) }, variant = BtnVariant.Primary, enabled = !saving)
            TeamButton("Cancel", onDismiss)
        },
    ) {
        LabeledInput("Full Name", name, { name = it }, placeholder = "Jane Doe")
        LabeledInput("Email", email, { email = it }, placeholder = "jane@bethanyhouse.co.ke",
            keyboardType = androidx.compose.ui.text.input.KeyboardType.Email)
    }
}

@Composable
private fun ResetPasswordDialog(agent: Agent, saving: Boolean, onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    val c = Neema.colors
    val typed = LocalTeamPreview.current.typed
    var password by rememberSaveable(agent.id) { mutableStateOf(typed["password"] ?: "") }
    var confirm by rememberSaveable(agent.id) { mutableStateOf(typed["confirm"] ?: "") }
    val mismatch = confirm.isNotEmpty() && password != confirm
    FormDialog(
        title = "Reset Password — ${agent.name}",
        onDismiss = onDismiss,
        buttons = {
            TeamButton(if (saving) "Saving…" else "Update Password", { onSave(password, confirm) },
                variant = BtnVariant.Primary, enabled = !saving && !mismatch)
            TeamButton("Cancel", onDismiss)
        },
    ) {
        Text(buildBold("Set a new password for ", agent.email, ".", c.text, FontWeight.SemiBold), fontSize = 12.sp, color = c.textDim)
        Spacer(Modifier.height(12.dp))
        LabeledInput("New Password", password, { password = it }, placeholder = "Min. 8 characters", password = true)
        LabeledInput(
            "Confirm Password", confirm, { confirm = it }, placeholder = "Repeat new password", password = true,
            isError = mismatch, supporting = if (mismatch) "Passwords do not match" else null,
        )
    }
}

// ── Role editor ───────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RoleEditorDialog(editing: CustomRole?, saving: Boolean, onDismiss: () -> Unit, onSave: (RoleForm) -> Unit) {
    val c = Neema.colors
    val key = editing?.id ?: "create"
    var name by rememberSaveable(key) { mutableStateOf(editing?.name ?: "") }
    var description by rememberSaveable(key) { mutableStateOf(editing?.description ?: "") }
    var color by rememberSaveable(key) { mutableStateOf(editing?.color ?: ROLE_COLORS[0]) }
    var perms by rememberSaveable(key) { mutableStateOf(editing?.permissions ?: emptyList()) }
    FormDialog(
        title = if (editing == null) "New Role" else "Edit Role — ${editing.name}",
        onDismiss = onDismiss,
        buttons = {
            TeamButton(
                if (saving) "Saving…" else if (editing == null) "Create Role" else "Save Role",
                { onSave(RoleForm(name, description, color, perms)) },
                variant = BtnVariant.Primary, enabled = !saving,
            )
            TeamButton("Cancel", onDismiss)
        },
    ) {
        LabeledInput("Role Name", name, { name = it }, placeholder = "e.g. Sales Agent")
        LabeledInput("Description", description, { description = it }, placeholder = "Brief description")

        Text("Colour", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.textDim)
        Spacer(Modifier.height(6.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            ROLE_COLORS.forEach { hex ->
                val sel = color.equals(hex, ignoreCase = true)
                val col = hexColor(hex)
                Box(
                    Modifier.size(32.dp)
                        .then(if (sel) Modifier.border(2.dp, col, CircleShape) else Modifier)
                        .padding(4.dp).clip(CircleShape).background(col)
                        .clickable { color = hex },
                    contentAlignment = Alignment.Center,
                ) { if (sel) Icon(Icons.Default.Check, "Selected", tint = Color.White, modifier = Modifier.size(14.dp)) }
            }
        }
        Spacer(Modifier.height(14.dp))
        PermissionPicker(perms) { perms = it }
    }
}

/**
 * The role editor's permission block: select/deselect all, per-group
 * toggles, a two-column checkbox grid, and the "n of N selected" line.
 * Also used for a single agent's permission override.
 */
@Composable
private fun PermissionPicker(selected: List<String>, onChange: (List<String>) -> Unit) {
    val c = Neema.colors
    val all = PermissionCatalog.ALL.map { it.key }
    val hasAll = all.all { it in selected }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("Permissions", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.textDim, modifier = Modifier.weight(1f))
        TextButton(onClick = { onChange(if (hasAll) emptyList() else all) }) {
            Text(if (hasAll) "Deselect all" else "Select all", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.gold)
        }
    }
    PermissionCatalog.GROUPS.forEach { group ->
        val gp = PermissionCatalog.inGroup(group)
        val allSel = gp.all { it.key in selected }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(group.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp, color = c.gold2, modifier = Modifier.weight(1f))
            TextButton(onClick = {
                onChange(if (allSel) selected.filter { k -> gp.none { it.key == k } } else (selected + gp.map { it.key }).distinct())
            }, contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp)) {
                Text(if (allSel) "Deselect" else "Select all", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = c.gold)
            }
        }
        gp.chunked(2).forEach { pair ->
            Row(Modifier.fillMaxWidth().padding(bottom = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                pair.forEach { perm ->
                    val checked = perm.key in selected
                    Row(
                        Modifier.weight(1f).clip(RoundedCornerShape(8.dp))
                            .background(if (checked) c.bg3 else c.surface)
                            .border(1.dp, if (checked) c.border else c.hairline, RoundedCornerShape(8.dp))
                            .clickable { onChange(if (checked) selected - perm.key else selected + perm.key) }
                            .padding(horizontal = 8.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(16.dp).clip(RoundedCornerShape(4.dp))
                                .background(if (checked) c.gold else c.bg2)
                                .border(1.dp, if (checked) c.gold else c.border, RoundedCornerShape(4.dp)),
                            contentAlignment = Alignment.Center,
                        ) { if (checked) Icon(Icons.Default.Check, null, tint = Color.White, modifier = Modifier.size(12.dp)) }
                        Spacer(Modifier.width(6.dp))
                        Text(perm.label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = if (checked) c.gold2 else c.muted)
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
        Spacer(Modifier.height(4.dp))
    }
    Text(
        "${selected.count { it in all }} of ${all.size} permissions selected",
        fontSize = 11.sp, color = c.textDim, modifier = Modifier.padding(top = 4.dp),
    )
}
