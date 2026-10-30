import SwiftUI
import NeemaCore

/// Port of AgentsView.tsx (Android `AgentsScreen`) — the Team screen: agents,
/// custom roles, and the dialogs that edit both.
///
/// No permission gate here — AgentsView.tsx has none. The nav lists Team only
/// with manage_agents (page.tsx), but a link opens it for anyone and it stays
/// open when a poll takes manage_agents away. The server decides every write:
/// admin.py's agent routes check only sign-in, and roles.py refuses only
/// protected roles.
struct TeamScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.teamScreen {
            GeometryReader { g in TeamBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}

/// Which dialog is open — "create", "edit:<id>", "pw:<id>", "del:<id>",
/// "assign:<id>", "role:create", "role:<id>", "delrole:<id>" — kept in the
/// scene state so it survives a reclaim, as Android's rememberSaveable does.
enum TeamDialog: Identifiable, Equatable {
    case create, edit(String), password(String), remove(String), assign(String), role(String?), deleteRole(String)

    var id: String { key }

    var key: String {
        switch self {
        case .create: return "create"
        case .edit(let id): return "edit:\(id)"
        case .password(let id): return "pw:\(id)"
        case .remove(let id): return "del:\(id)"
        case .assign(let id): return "assign:\(id)"
        case .role(let id): return "role:\(id ?? "create")"
        case .deleteRole(let id): return "delrole:\(id)"
        }
    }

    init?(key: String) {
        if key == "create" { self = .create; return }
        guard let colon = key.firstIndex(of: ":") else { return nil }
        let kind = String(key[..<colon])
        let id = String(key[key.index(after: colon)...])
        if id.isEmpty { return nil }
        switch kind {
        case "edit": self = .edit(id)
        case "pw": self = .password(id)
        case "del": self = .remove(id)
        case "assign": self = .assign(id)
        case "role": self = .role(id == "create" ? nil : id)
        case "delrole": self = .deleteRole(id)
        default: return nil
        }
    }

    /// The `closedDialogs` name that folds this dialog away.
    var closeName: String {
        switch self {
        case .create: return "create"
        case .edit: return "edit"
        case .password: return "pw"
        case .remove: return "del"
        case .assign: return "assign"
        case .role: return "role"
        case .deleteRole: return "delrole"
        }
    }

    /// The agent this dialog is about, if any: gone from the team, the dialog goes too.
    var agentId: String? {
        switch self {
        case .edit(let id), .password(let id), .remove(let id), .assign(let id): return id
        default: return nil
        }
    }

    /// The role this dialog is about, if any.
    var roleId: String? {
        switch self {
        case .role(let id): return id
        case .deleteRole(let id): return id
        default: return nil
        }
    }
}

struct TeamBody: View {
    @ObservedObject var model: TeamScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    // The dialogs' typed input (passwords excepted) comes back after iOS reclaims the app.
    @SceneStorage("team.ui") private var savedUi: String = ""
    // Both tabs for everyone here: the web never tests manage_roles.
    @SceneStorage("team.tab") private var tab: String = "agents"
    @SceneStorage("team.dialog") private var dialogKey: String = ""

    private var vm: TeamViewModel { model.vm }
    private var ui: TeamUi { model.ui }
    private var agents: [Agent] { model.agents }

    private var dialog: Binding<TeamDialog?> {
        Binding(get: { TeamDialog(key: dialogKey) }, set: { dialogKey = $0?.key ?? "" })
    }

    private func open(_ d: TeamDialog) { dialogKey = d.key }

    private func agentById(_ id: String) -> Agent? { agents.first { $0.id == id } }

    var body: some View {
        // Indexed once per list, not searched per card: a 200-agent, 50-role team.
        let roleIndex = Dictionary(ui.roles.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let agentsPerRole = Dictionary(grouping: agents.compactMap { $0.customRoleId }, by: { $0 }).mapValues { $0.count }
        let onlineCount = agents.filter { ui.availability[$0.id] ?? $0.isAvailable }.count
        // The web's grid: one column on phones, two from sm, three from lg — here
        // as many 320pt columns as fit, never more than three.
        let columns = min(3, max(1, Int((width - 32 + 12) / (320 + 12))))
        // "Last seen 4m ago" keeps counting between polls instead of freezing at first paint.
        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            let now = Int64(ctx.date.timeIntervalSince1970 * 1000)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    header(onlineCount: onlineCount)
                    tabs
                    if tab == "agents" {
                        agentsTab(columns: columns, roleIndex: roleIndex, now: now)
                    } else {
                        rolesTab(agentsPerRole: agentsPerRole)
                    }
                }
                .padding(16)
            }
            .refreshable { await pullToRefresh() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        .sheet(item: dialog) { d in
            dialogView(d, roleIndex: roleIndex, agentsPerRole: agentsPerRole)
                .environment(\.neema, c)
                .environmentObject(app)
        }
        .onAppear {
            vm.restoreIfFresh(savedUi)
            vm.life.shown.update(true)
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: ui.forms) { savedUi = vm.saveUi() }
        // A save that succeeded closes its dialog here — also when the sheet that started it has been replaced.
        .onChange(of: model.closed) { _, closed in
            if let d = TeamDialog(key: dialogKey), let name = closed?.name, d.closeName == name { dialogKey = "" }
        }
        // The row a dialog is about has gone (removed by someone else): the dialog goes with it.
        .onChange(of: agents) { _, list in
            if let d = TeamDialog(key: dialogKey), let id = d.agentId, !list.contains(where: { $0.id == id }) { dialogKey = "" }
        }
        .onChange(of: ui.roles) { _, roles in
            if let d = TeamDialog(key: dialogKey), let id = d.roleId, !roles.contains(where: { $0.id == id }) { dialogKey = "" }
        }
    }

    // ── Header and tabs ───────────────────────────────────────────────────────

    /// A large font or a narrow phone moves the button under the title rather than squeeze the counts.
    private func header(onlineCount: Int) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 12) {
                headerText(onlineCount: onlineCount)
                Spacer(minLength: 12)
                headerButton
            }
            VStack(alignment: .leading, spacing: 8) {
                headerText(onlineCount: onlineCount)
                headerButton
            }
        }
    }

    private func headerText(onlineCount: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Team").font(NeemaFont.manrope(20, .bold)).tracking(-0.5).foregroundColor(c.text)
            teamCounts(agents.count, onlineCount)
        }
    }

    /// "4 agents · 2 online", the online count in the brand green.
    private func teamCounts(_ total: Int, _ online: Int) -> Text {
        Text("\(total) agents · ").font(NeemaFont.manrope(14)).foregroundColor(c.textDim)
            + Text("\(online) online").font(NeemaFont.manrope(14)).foregroundColor(c.gold)
    }

    @ViewBuilder private var headerButton: some View {
        if tab == "agents" {
            TeamBtn(label: "Add Agent", variant: .primary, lead: "plus") { open(.create) }
        } else {
            TeamBtn(label: "New Role", variant: .primary, lead: "plus") {
                vm.editForms { $0.openRole(nil) }
                open(.role(nil))
            }
        }
    }

    /// The web's tabs: left-aligned labels, a 2pt underline on the active one, over a hairline.
    private var tabs: some View {
        ZStack(alignment: .bottom) {
            Hairline(color: c.bg4)
            HStack(spacing: 4) {
                tabButton("agents", "Agents (\(agents.count))")
                tabButton("roles", "Roles (\(ui.roles.count))")
                Spacer(minLength: 0)
            }
        }
    }

    private func tabButton(_ key: String, _ label: String) -> some View {
        let sel = tab == key
        return Button { tab = key } label: {
            VStack(spacing: 0) {
                Text(label).font(NeemaFont.manrope(13, .semibold)).foregroundColor(sel ? c.gold2 : c.textDim).monospacedDigit()
                    .padding(.horizontal, 16).padding(.vertical, 12).frame(minHeight: 46)
                Rectangle().fill(sel ? c.gold : .clear).frame(height: 2)
            }
            // As wide as its label, not the row's share: the underline would otherwise stretch each tab to half the row.
            .fixedSize(horizontal: true, vertical: false)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(sel ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }

    // ── Agents ────────────────────────────────────────────────────────────────

    private func agentsTab(columns: Int, roleIndex: [String: CustomRole], now: Int64) -> some View {
        // Cards in a row share its tallest card's height, as a CSS grid row does.
        let rows = stride(from: 0, to: agents.count, by: columns).map { Array(agents[$0..<min($0 + columns, agents.count)]) }
        return Group {
            if agents.isEmpty, let e = ui.agentsError {
                LoadProblem(message: e, title: "Couldn't load the team", retrying: ui.refreshing, onRetry: { vm.refresh() })
            } else if agents.isEmpty {
                Text("No agents yet.").font(NeemaFont.manrope(14)).foregroundColor(c.textDim)
                    .frame(maxWidth: .infinity).padding(.vertical, 64)
            }
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .top, spacing: 12) {
                    ForEach(row) { agent in
                        AgentCard(agent: agent, available: ui.availability[agent.id] ?? agent.isAvailable,
                                  customRole: agent.customRoleId.flatMap { roleIndex[$0] }, now: now,
                                  onToggle: { Haptics.tap(); vm.toggleOnline(agent, current: ui.availability[agent.id] ?? agent.isAvailable) },
                                  onRole: { vm.editForms { $0.openAssign(agent, roles: ui.roles) }; open(.assign(agent.id)) },
                                  onEdit: { vm.editForms { $0.openEdit(agent) }; open(.edit(agent.id)) },
                                  onPassword: { vm.editForms { $0.openPassword() }; open(.password(agent.id)) },
                                  onDelete: { if vm.requestRemove(agent) { open(.remove(agent.id)) } })
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                    // A short last row keeps its cards at column width.
                    ForEach(Array(0..<(columns - row.count)), id: \.self) { _ in Color.clear.frame(maxWidth: .infinity, maxHeight: 1) }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // ── Roles ─────────────────────────────────────────────────────────────────

    private func rolesTab(agentsPerRole: [String: Int]) -> some View {
        Group {
            if ui.rolesLoading && ui.roles.isEmpty {
                LoadingView().frame(height: 160)
            } else if ui.roles.isEmpty, let e = ui.rolesError {
                LoadProblem(message: e, title: "Couldn't load the roles", retrying: ui.refreshing, onRetry: { vm.refresh() })
            } else if ui.roles.isEmpty {
                EmptyStateView(title: "No roles yet", subtitle: "Create one with New Role.", icon: "checkmark.shield")
            }
            // Roles read as a list on the web (space-y-3), full width.
            ForEach(ui.roles) { role in
                RoleCard(role: role, agentCount: agentsPerRole[role.id] ?? 0,
                         onEdit: { vm.editForms { $0.openRole(role) }; open(.role(role.id)) },
                         onDelete: { open(.deleteRole(role.id)) })
            }
        }
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }

    // ── Dialogs ───────────────────────────────────────────────────────────────

    @ViewBuilder
    private func dialogView(_ d: TeamDialog, roleIndex: [String: CustomRole], agentsPerRole: [String: Int]) -> some View {
        switch d {
        case .create:
            CreateAgentDialog(model: model, saving: ui.saving, onDismiss: { dialogKey = "" }) { name, email, pw, role in
                vm.createAgent(name: name, email: email, password: pw, roleId: role) { vm.closeDialog("create") }
            }
        case .edit(let id):
            if let a = agentById(id) {
                EditAgentDialog(agent: a, model: model, saving: ui.saving, onDismiss: { dialogKey = "" }) { name, email in
                    vm.saveEdit(a, name: name, email: email) { vm.closeDialog("edit") }
                }
            }
        case .password(let id):
            if let a = agentById(id) {
                ResetPasswordDialog(agent: a, model: model, saving: ui.saving, onDismiss: { dialogKey = "" }) { pw, confirm in
                    vm.savePassword(a, password: pw, confirm: confirm) { vm.closeDialog("pw") }
                }
            }
        case .remove(let id):
            if let a = agentById(id) {
                RemoveAgentDialog(agent: a, saving: ui.saving, onDismiss: { dialogKey = "" }) {
                    vm.deleteAgent(a) { vm.closeDialog("del") }
                }
            }
        case .assign(let id):
            if let a = agentById(id) {
                AssignRoleDialog(agent: a, roles: ui.roles, model: model, saving: ui.saving, onDismiss: { dialogKey = "" }) { roleId, perms in
                    vm.saveAssign(a, roleId: roleId, customPermissions: perms) { vm.closeDialog("assign") }
                }
            }
        case .role(let id):
            roleEditor(id, roleIndex: roleIndex)
        case .deleteRole(let id):
            if let r = roleIndex[id] {
                DeleteRoleDialog(role: r, agentCount: agentsPerRole[id] ?? 0, saving: ui.saving, onDismiss: { dialogKey = "" }) {
                    vm.deleteRole(r) { vm.closeDialog("delrole") }
                }
            }
        }
    }

    /// `id` nil = a new role; an id whose role has gone shows nothing (the sheet closes with it).
    private func roleEditor(_ id: String?, roleIndex: [String: CustomRole]) -> some View {
        let editing = id.flatMap { roleIndex[$0] }
        return Group {
            if id == nil || editing != nil {
                RoleEditorDialog(editing: editing, model: model, saving: ui.saving, onDismiss: { dialogKey = "" }) { form in
                    vm.saveRole(editing: editing, form: form) { vm.closeDialog("role") }
                }
            }
        }
    }
}

// ── Agent card ────────────────────────────────────────────────────────────────

struct AgentCard: View {
    let agent: Agent
    let available: Bool
    let customRole: CustomRole?
    let now: Int64
    let onToggle: () -> Void
    let onRole: () -> Void
    let onEdit: () -> Void
    let onPassword: () -> Void
    let onDelete: () -> Void
    @Environment(\.neema) private var c

    // Before the roles list lands, the agent row already carries its role's name and colour.
    private var roleName: String? { customRole?.name ?? (agent.customRoleId != nil ? agent.roleName : nil) }
    private var roleColor: String? { customRole?.color ?? agent.roleColor }
    private var rolePermCount: Int? { customRole?.permissions.count ?? agent.rolePermissions?.count }

    private var lastSeen: String {
        let t = Fmt.timeAgo(agent.lastSeenAt, now: now)
        return t == "—" ? "never" : t
    }

    /// "11 permissions assigned", or the agent's own count when they carry an override.
    private var permissionsLine: String? {
        guard roleName != nil, let n = rolePermCount else { return nil }
        if let own = agent.customPermissions { return "\(own.count) permissions (custom for this agent)" }
        return "\(n) permissions assigned"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 12) {
                ZStack(alignment: .bottomTrailing) {
                    AvatarView(name: agent.name, url: agent.avatarUrl, size: 44)
                    // w-3 h-3 with a 2px white ring, nudged 2px past the avatar's corner.
                    Circle().fill(available ? Palette.emerald500 : Palette.stone300).frame(width: 8, height: 8)
                        .padding(2).background(Circle().fill(c.bg2)).offset(x: 2, y: 2)
                }
                .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    FlowLayout(spacing: 6, lineSpacing: 2) {
                        Text(agent.name).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text).lineLimit(2)
                        if let rn = roleName {
                            RoleBadge(text: rn, fill: hexColor(roleColor), content: roleInk(roleColor))
                        } else {
                            // The base DB role, capitalised: #e6f3d8 fill, #427425 text.
                            RoleBadge(text: capitalizeFirst(agent.role), fill: c.isDark ? c.goldDim : c.bg3, content: c.gold2)
                        }
                        if agent.customPermissions != nil { TeamPill(text: "Custom permissions", color: c.blue) }
                    }
                    Text(agent.email).font(NeemaFont.manrope(12)).foregroundColor(c.textDim).lineLimit(1)
                    Text("\(agent.activeConvs) active · Joined \(Fmt.date(agent.createdAt))").font(NeemaFont.manrope(12)).foregroundColor(teamFaint(c))
                    Text(available ? "Online now" : "Last seen \(lastSeen)").font(NeemaFont.manrope(11)).foregroundColor(available ? c.gold : c.muted)
                    if let line = permissionsLine {
                        Text(line).font(NeemaFont.manrope(11)).foregroundColor(c.muted)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            // In a stretched grid row the footer sits on the card's bottom edge, so a row's footers line up.
            Spacer(minLength: 12)
            Hairline(color: c.isDark ? c.hairline : c.bg3)
            footer.padding(.top, 8)
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(teamCardBorder(c)))
    }

    /// One line on a phone; at a large font the buttons wrap under the switch instead of clipping.
    private var footer: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 4) {
                availability
                Spacer(minLength: 4)
                buttons
            }
            FlowLayout(spacing: 4, lineSpacing: 4) {
                availability
                buttons
            }
        }
    }

    private var availability: some View {
        HStack(spacing: 8) {
            Text("Available").font(NeemaFont.manrope(12)).foregroundColor(c.textDim)
            Toggle("Available", isOn: Binding(get: { available }, set: { _ in onToggle() }))
                .labelsHidden().tint(c.gold).scaleEffect(0.8)
                .accessibilityLabel("Available")
        }
        .padding(.trailing, 4)
    }

    @ViewBuilder private var buttons: some View {
        TeamBtn(label: "Role", small: true, lead: "checkmark.shield", action: onRole)
        TeamBtn(label: "Edit", small: true, action: onEdit)
        TeamIconBtn(icon: "key", label: "Reset password", variant: .ghost, action: onPassword)
        TeamIconBtn(icon: "trash", label: "Remove agent", variant: .danger, action: onDelete)
    }
}

// ── Role card ─────────────────────────────────────────────────────────────────

struct RoleCard: View {
    let role: CustomRole
    let agentCount: Int
    let onEdit: () -> Void
    let onDelete: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            RoleSquare(role: role, size: 40)
            VStack(alignment: .leading, spacing: 0) {
                // The Edit / Delete pair sits beside the name only, so on a phone the
                // description and permission chips below keep the card's full width.
                HStack(alignment: .top, spacing: 8) {
                    FlowLayout(spacing: 6, lineSpacing: 2) {
                        Text(role.name).font(NeemaFont.manrope(14, .bold)).foregroundColor(c.text)
                        if role.isProtected { ProtectedTag() }
                        Text("\(agentCount) agent\(agentCount != 1 ? "s" : "")").font(NeemaFont.manrope(11)).foregroundColor(c.textDim)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    if !role.isProtected {
                        HStack(spacing: 4) {
                            TeamBtn(label: "Edit", small: true, action: onEdit)
                            TeamIconBtn(icon: "trash", label: "Delete role", variant: .danger, action: onDelete)
                        }
                    }
                }
                if !role.description.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text(role.description).font(NeemaFont.manrope(12)).foregroundColor(c.textDim).padding(.top, 2).padding(.bottom, 6)
                } else {
                    Spacer().frame(height: 6)
                }
                FlowLayout(spacing: 4, lineSpacing: 4) {
                    ForEach(Array(role.permissions.prefix(8).enumerated()), id: \.offset) { _, p in
                        if let label = PermissionCatalog.label(p) { PermChip(label: label) }
                    }
                    if role.permissions.count > 8 {
                        Text("+\(role.permissions.count - 8) more").font(NeemaFont.manrope(10)).foregroundColor(c.textDim)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(RoundedRectangle(cornerRadius: 4).fill(c.bg3))
                    }
                    if role.permissions.isEmpty {
                        Text("No permissions assigned").font(NeemaFont.manrope(10)).italic().foregroundColor(teamFaint(c))
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(teamCardBorder(c)))
    }
}
