import SwiftUI
import AudioToolbox
import NeemaCore

/// Port of ProfileView.tsx plus the account menu from Sidebar.tsx (identity,
/// Settings link, theme, Sign out) and the device settings (Android
/// `ProfileScreen`): system notification settings, sounds, app version.
struct ProfileScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.profileScreen {
            GeometryReader { g in ProfileBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}

/// A permission you hold: the web's #2c4e18 on #f0f9ec.
private let hasPermText = Palette.moss800

struct ProfileBody: View {
    @ObservedObject var model: ProfileScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @Environment(\.openURL) private var openURL
    // The typed name/email/department come back after iOS reclaims the app.
    @SceneStorage("profile.ui") private var savedUi: String = ""
    @SceneStorage("profile.edit") private var editMode = false
    @SceneStorage("profile.password") private var changingPassword = false
    @State private var confirmSignOut = false

    private var vm: ProfileViewModel { model.vm }
    private var ui: ProfileUi { model.ui }

    /// The team row carries the custom role and its permissions (GET /admin/agents
    /// joins custom_roles; /me is the bare agent), so permissions come from it.
    private var teamRow: Agent? {
        model.agents.first { $0.id == model.me?.id }
            ?? model.agents.first { $0.email.caseInsensitiveCompare(app.session?.email ?? "") == .orderedSame }
    }
    private var agent: Agent? { model.me ?? teamRow }

    var body: some View {
        Group {
            if let a = agent { loaded(a) } else { loading }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        .onAppear {
            vm.restoreIfFresh(savedUi)
            if let a = agent {
                vm.fillForm(a)
                vm.reconcile(a.isAvailable)
            }
        }
        .onChange(of: agent?.id) { if let a = agent { vm.fillForm(a) } }
        .onChange(of: agent?.isAvailable) { _, v in vm.reconcile(v) }
        .onChange(of: ui.form) { savedUi = vm.saveUi() ?? "" }
        // A save that succeeded folds its form away here — also when the screen that started it has been replaced.
        .onChange(of: model.closed) { _, closed in
            if closed?.name == "edit" { editMode = false } else if closed?.name == "password" { changingPassword = false }
        }
        .alert("Sign out?", isPresented: $confirmSignOut) {
            Button("Sign out", role: .destructive) { app.logout() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("You'll stop receiving chats, alerts and calls on this device until you sign in again.")
        }
    }

    // ── Nothing to show yet ───────────────────────────────────────────────────

    private var loading: some View {
        VStack {
            if let why = ui.loadError {
                LoadProblem(message: why, title: "Couldn't load your profile", retrying: ui.refreshing, onRetry: { vm.refresh() })
                    .frame(maxWidth: 480)
            } else {
                Text("Loading profile…").font(NeemaFont.manrope(14)).foregroundColor(teamFaint(c))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(16)
    }

    // ── The page ──────────────────────────────────────────────────────────────

    private func loaded(_ agent: Agent) -> some View {
        let permKeys = Set(Perms.of(teamRow ?? agent))
        let known = permKeys.filter { k in PermissionCatalog.ALL.contains { $0.key == k } }.count
        let available = ui.availableOverride ?? agent.isAvailable
        // A 360pt phone at a large font: the header stacks, the tiles go one per line, the permission grid one column.
        let inner = min(width, 720) - 32
        let compact = inner / teamFontScale < 300
        let stackTiles = inner / teamFontScale < 260
        return ScrollView {
            // The web caps this page at max-w-2xl; tablets keep that reading width.
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Profile").font(NeemaFont.manrope(20, .bold)).tracking(-0.5).foregroundColor(c.text)
                    Text("Manage your account and preferences").font(NeemaFont.manrope(13)).foregroundColor(teamFaint(c))
                }
                profileCard(agent, compact: compact)
                statsRow(agent, available: available, permCount: known, stack: stackTiles)
                ProfileSection(title: "Availability") {
                    ToggleRow(label: "Available",
                              desc: available ? "You're online — the team sees you as available and chats can be transferred to you."
                                              : "You're away — shown as offline to the team.",
                              on: available) { Haptics.tap(); vm.setAvailable(agentId: agent.id, available: !available) }
                }
                passwordCard
                ProfileSection(title: "Appearance") {
                    ToggleRow(label: "Dark Mode", desc: "Switch to dark theme", on: app.dark) { app.setDark(!app.dark) }
                }
                notificationsCard
                soundsCard
                permissionsCard(permKeys, compact: compact)
                accountCard
                Spacer().frame(height: 24)
            }
            .frame(maxWidth: 720)
            .frame(maxWidth: .infinity)
            .padding(16)
        }
        .refreshable { await pullToRefresh() }
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }

    // ── Profile card ──────────────────────────────────────────────────────────

    private func profileCard(_ agent: Agent, compact: Bool) -> some View {
        PanelCard(padding: 20) {
            if compact {
                // Avatar and Edit on one line, the name and details under them at full width.
                HStack(alignment: .center) {
                    AvatarView(name: agent.name, url: agent.avatarUrl, size: 56)
                    Spacer(minLength: 8)
                    editButton
                }
                details(agent).padding(.top, 12)
            } else {
                HStack(alignment: .top, spacing: 16) {
                    AvatarView(name: agent.name, url: agent.avatarUrl, size: 56)
                    details(agent).frame(maxWidth: .infinity, alignment: .leading)
                    editButton.padding(.leading, 8)
                }
            }
            if editMode {
                Hairline(color: c.bg3).padding(.top, 20)
                editForm.padding(.top, 16)
            }
        }
    }

    private var editButton: some View {
        TeamBtn(label: editMode ? "Cancel" : "Edit", variant: editMode ? .outline : .secondary, small: true) { editMode.toggle() }
    }

    private func details(_ agent: Agent) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            FlowLayout(spacing: 8, lineSpacing: 4) {
                Text(agent.name).font(NeemaFont.manrope(16, .bold)).foregroundColor(c.text)
                BaseRoleBadge(role: agent.role)
            }
            if let rn = teamRow?.roleName, !rn.isEmpty {
                // Your custom role, in its colour, with whichever text colour reads on it.
                RoleBadge(text: rn, fill: hexColor(teamRow?.roleColor), content: roleInk(teamRow?.roleColor)).padding(.top, 4)
            }
            // One line with the tail cut: an address has no break point, and SwiftUI would split it mid-word where Compose fits it.
            Text(agent.email).font(NeemaFont.manrope(14)).foregroundColor(teamFaint(c)).lineLimit(1).truncationMode(.tail).padding(.top, 2)
            Text(joinedLine(agent)).font(NeemaFont.manrope(12)).foregroundColor(teamFaint(c)).padding(.top, 4)
        }
    }

    private func joinedLine(_ agent: Agent) -> String {
        var s = "Joined \(Fmt.date(agent.createdAt))"
        if let seen = agent.lastSeenAt { s += " · Last active \(Fmt.date(seen))" }
        return s
    }

    private var editForm: some View {
        VStack(alignment: .leading, spacing: 0) {
            LabeledInput(label: "Full Name", text: model.bind(\.name), capitalization: .words, contentType: .name, style: .form)
            LabeledInput(label: "Email", text: model.bind(\.email), keyboard: .emailAddress, contentType: .emailAddress, style: .form)
            // The web shows a Department field but never sends it (PATCH /me has no
            // such column); it is kept for parity and stays on this form only.
            LabeledInput(label: "Department", text: model.bind(\.department), placeholder: "Sales, Support…", style: .form, submit: .done)
            FlowLayout(spacing: 8, lineSpacing: 8) {
                TeamBtn(label: ui.saving ? "Saving…" : "Save Changes", variant: .amber, enabled: !ui.saving) {
                    vm.saveProfile(name: ui.form.name, email: ui.form.email) { vm.closeForm("edit") }
                }
                TeamBtn(label: "Cancel", variant: .outline) { editMode = false }
            }
        }
    }

    // ── Stats ─────────────────────────────────────────────────────────────────

    private func statsRow(_ agent: Agent, available: Bool, permCount: Int, stack: Bool) -> some View {
        let seen = !available && agent.lastSeenAt != nil ? "Seen \(Fmt.timeAgo(agent.lastSeenAt))" : nil
        return Group {
            if stack {
                // Three abreast would cut "Active chats" and "20/20" short at this size.
                VStack(spacing: 10) {
                    StatTile(label: "Active chats", value: String(agent.activeConvs))
                    StatTile(label: "Status", value: available ? "Online" : "Away", hint: seen, accent: available ? c.gold : c.muted)
                    StatTile(label: "Permissions", value: "\(permCount)/\(PermissionCatalog.ALL.count)")
                }
            } else {
                // One height for the three tiles, even when Status carries a "Seen …" line.
                HStack(alignment: .top, spacing: 10) {
                    StatTile(label: "Active chats", value: String(agent.activeConvs)).frame(maxWidth: .infinity, maxHeight: .infinity)
                    StatTile(label: "Status", value: available ? "Online" : "Away", hint: seen, accent: available ? c.gold : c.muted)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    StatTile(label: "Permissions", value: "\(permCount)/\(PermissionCatalog.ALL.count)").frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // ── Password ──────────────────────────────────────────────────────────────

    private var passwordCard: some View {
        PanelCard(padding: 20) {
            HStack(alignment: .center, spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Password").font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text)
                    Text("Change your login password").font(NeemaFont.manrope(12)).foregroundColor(teamFaint(c))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                TeamBtn(label: changingPassword ? "Cancel" : "Change", variant: .secondary, small: true) { changingPassword.toggle() }
            }
            if changingPassword {
                VStack(alignment: .leading, spacing: 0) {
                    LabeledInput(label: "New Password", text: model.bind(\.password), placeholder: "Minimum 8 characters", password: true,
                                 contentType: .newPassword, style: .form)
                    LabeledInput(label: "Confirm Password", text: model.bind(\.confirm), password: true, contentType: .newPassword, style: .form, submit: .done)
                    TeamBtn(label: ui.saving ? "Changing…" : "Change Password", variant: .amber, enabled: !ui.saving) {
                        vm.changePassword(password: ui.form.password, confirm: ui.form.confirm) { vm.closeForm("password") }
                    }
                }
                .padding(.top, 16)
            }
        }
    }

    // ── Notifications ─────────────────────────────────────────────────────────

    private var notificationsCard: some View {
        ProfileSection(title: "Notifications") {
            ForEach(Array(NOTIF_PREFS.enumerated()), id: \.offset) { i, p in
                ToggleRow(label: p.label, desc: p.desc, on: ui.notifs[p.key] ?? p.def) { vm.toggleNotif(p.key) }
                    .padding(.top, i > 0 ? 14 : 0)
            }
            Hairline(color: c.bg3).padding(.vertical, 14)
            LinkRow(icon: "bell.badge", label: "System notification settings", desc: "Alerts, sounds, the lock screen and which notifications iOS shows") {
                if let url = URL(string: UIApplication.openNotificationSettingsURLString) { openURL(url) }
            }
        }
    }

    // ── Sounds & vibration ────────────────────────────────────────────────────

    /// How Neema sounds: a beep and a buzz for every customer message, the
    /// ringtone and buzz for calls, a way to try them, and Mute for when the
    /// room needs quiet (messages only — calls keep ringing unless switched off here).
    private var soundsCard: some View {
        let a = model.alerts
        let prefs = model.prefs
        // Re-read the clock while muted, so "Muted until 3:40 PM" ends on time.
        return TimelineView(.periodic(from: .now, by: 30)) { ctx in
            let now = Int64(ctx.date.timeIntervalSince1970 * 1000)
            let status = muteStatus(until: a.mutedUntil, now: now)
            ProfileSection(title: "Sounds & vibration") {
                // Mute: the first thing here, as it is the thing reached for in a hurry.
                VStack(alignment: .leading, spacing: 2) {
                    Text(status != nil ? "Messages muted" : "Mute messages").font(NeemaFont.manrope(14, .medium)).foregroundColor(c.text)
                    Text(status ?? "Silence message sounds and vibration for a while. Messages still arrive; calls still ring.")
                        .font(NeemaFont.manrope(12)).foregroundColor(status != nil ? c.gold : teamFaint(c))
                        .fixedSize(horizontal: false, vertical: true)
                }
                FlowLayout(spacing: 8, lineSpacing: 8) {
                    if status != nil { TeamBtn(label: "Unmute", variant: .primary, small: true) { prefs.unmute() } }
                    ForEach(Array(MUTE_CHOICES.enumerated()), id: \.offset) { _, choice in
                        TeamBtn(label: choice.label, variant: .secondary, small: true) { prefs.muteFor(choice.ms) }
                    }
                }
                .padding(.top, 10)
                Hairline(color: c.bg3).padding(.vertical, 14)
                ToggleRow(label: "Message sound", desc: "Your phone's notification sound for every customer message", on: a.messageSound) {
                    var next = a; next.messageSound.toggle(); prefs.setAlerts(next)
                }
                ToggleRow(label: "Vibrate for messages", desc: "A short double buzz for every customer message", on: a.messageVibrate) {
                    var next = a; next.messageVibrate.toggle(); prefs.setAlerts(next)
                }
                .padding(.top, 14)
                ToggleRow(label: "Ring for calls", desc: "Your ringtone while a WhatsApp or Messenger call rings", on: a.callRing) {
                    var next = a; next.callRing.toggle(); prefs.setAlerts(next)
                }
                .padding(.top, 14)
                ToggleRow(label: "Vibrate for calls", desc: "Buzz while a call rings", on: a.callVibrate) {
                    var next = a; next.callVibrate.toggle(); prefs.setAlerts(next)
                }
                .padding(.top, 14)
                LinkRow(icon: "bell.badge", label: "Try the message alert", desc: "Plays it once, as a customer message would (the phone's silent switch applies)") {
                    DeviceAlertPlayer.play(sound: a.messageSound, vibrate: a.messageVibrate)
                }
                .padding(.top, 8)
            }
        }
    }

    // ── Permissions ───────────────────────────────────────────────────────────

    private func permissionsCard(_ permKeys: Set<String>, compact: Bool) -> some View {
        let perRow = compact ? 1 : 2
        let all = PermissionCatalog.ALL
        let rows = stride(from: 0, to: all.count, by: perRow).map { Array(all[$0..<min($0 + perRow, all.count)]) }
        return ProfileSection(title: "Your Permissions") {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, pair in
                HStack(alignment: .top, spacing: 8) {
                    ForEach(pair) { p in permissionCell(p, has: permKeys.contains(p.key)) }
                    if pair.count < perRow { Spacer(minLength: 0) }
                }
                .fixedSize(horizontal: false, vertical: true)
                .padding(.bottom, 8)
            }
        }
    }

    private func permissionCell(_ p: PermissionDef, has: Bool) -> some View {
        HStack(spacing: 8) {
            Circle().fill(has ? c.gold : Palette.stone300).frame(width: 6, height: 6)
            Text(p.label).font(NeemaFont.manrope(12)).foregroundColor(has ? (c.isDark ? c.gold2 : hasPermText) : teamFaint(c))
                .multilineTextAlignment(.leading)
            Spacer(minLength: 0)
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(has ? c.goldDim : c.bg))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(has ? c.border : c.bg4))
        .accessibilityElement(children: .combine)
        .accessibilityValue(has ? "Granted" : "Not granted")
    }

    // ── Account (the sidebar's account menu) ──────────────────────────────────

    private var accountCard: some View {
        ProfileSection(title: "Account") {
            // Sidebar.tsx's account menu offers Settings to everyone; the server refuses a non-admin's saves.
            LinkRow(icon: "gearshape", label: "Settings", desc: "Platform configuration and integrations") { app.navigate(.settings) }
            LinkRow(icon: "info.circle", label: "App version", desc: "Neema for iOS \(appVersion)", chevron: false) {}
                .padding(.top, 4)
            Button { confirmSignOut = true } label: {
                HStack(spacing: 8) {
                    Image(systemName: "rectangle.portrait.and.arrow.right").font(.system(size: 16, weight: .semibold))
                    Text("Sign out").font(NeemaFont.manrope(14, .semibold))
                }
                .foregroundColor(c.red)
                .frame(maxWidth: .infinity, minHeight: 48)
                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.red.opacity(0.1)))
            }
            .buttonStyle(.plain)
            .padding(.top, 12)
        }
    }

    private var appVersion: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "dev"
        if let build = info?["CFBundleVersion"] as? String, !build.isEmpty, build != version { return "\(version) (\(build))" }
        return version
    }
}

// ── Pieces ────────────────────────────────────────────────────────────────────

/// The role chip beside your name: `capitalize`d DB role; admin in purple
/// (purple-100 / purple-700 / purple-200 border), anyone else in the pale
/// greens (#e6f3d8 / #427425 / #cee6b2 border).
struct BaseRoleBadge: View {
    let role: String
    @Environment(\.neema) private var c

    private var look: (fill: Color, text: Color, edge: Color) {
        let admin = role == "admin"
        if admin && c.isDark { return (Palette.purple500.opacity(0.2), Palette.purple300, Palette.purple500.opacity(0.4)) }
        if admin { return (Palette.purple100, Palette.purple700, Palette.purple200) }
        if c.isDark { return (c.goldDim, c.gold2, c.border) }
        return (c.bg3, c.gold2, c.bg4)
    }

    var body: some View {
        let l = look
        Text(capitalizeFirst(role)).font(NeemaFont.manrope(12, .semibold)).foregroundColor(l.text).lineLimit(1)
            .padding(.horizontal, 8).padding(.vertical, 2)
            .background(Capsule().fill(l.fill))
            .overlay(Capsule().stroke(l.edge))
    }
}

/// A titled card (Android `ProfileCard`).
struct ProfileSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content
    @Environment(\.neema) private var c

    var body: some View {
        PanelCard(padding: 20) {
            Text(title).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text).padding(.bottom, 16)
            content()
        }
    }
}

/// A KPI tile: label, big number, optional hint (Android `StatTile`). A
/// one-word label or figure steps its size down rather than break mid-word.
struct StatTile: View {
    let label: String
    let value: String
    var hint: String? = nil
    var accent: Color? = nil
    @Environment(\.neema) private var c

    var body: some View {
        PanelCard {
            Text(label).font(NeemaFont.manrope(12)).foregroundColor(c.muted).lineLimit(2).minimumScaleFactor(0.66)
            Text(value).font(NeemaFont.manrope(22, .extrabold)).monospacedDigit().foregroundColor(accent ?? c.text)
                .lineLimit(1).minimumScaleFactor(0.55).padding(.top, 4)
            if let h = hint { Text(h).font(NeemaFont.manrope(11)).foregroundColor(c.muted).lineLimit(2) }
        }
    }
}

/// A labelled switch whose whole row is the target (read as "label, switch, on").
struct ToggleRow: View {
    let label: String
    let desc: String
    let on: Bool
    let onToggle: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Toggle(isOn: Binding(get: { on }, set: { _ in onToggle() })) {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(NeemaFont.manrope(14, .medium)).foregroundColor(c.text)
                Text(desc).font(NeemaFont.manrope(12)).foregroundColor(teamFaint(c)).fixedSize(horizontal: false, vertical: true)
            }
            .padding(.trailing, 12)
        }
        .tint(c.gold)
        .frame(minHeight: 48)
    }
}

/// An icon, a label with a line under it, and a chevron: a row that opens something.
struct LinkRow: View {
    let icon: String
    let label: String
    let desc: String
    var chevron: Bool = true
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon).font(.system(size: 18, weight: .regular)).foregroundColor(c.textDim).frame(width: 24)
                VStack(alignment: .leading, spacing: 2) {
                    Text(label).font(NeemaFont.manrope(14, .medium)).foregroundColor(c.text)
                    Text(desc).font(NeemaFont.manrope(12)).foregroundColor(teamFaint(c)).fixedSize(horizontal: false, vertical: true)
                }
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                if chevron { Image(systemName: "chevron.right").font(.system(size: 14, weight: .semibold)).foregroundColor(c.muted) }
            }
            .padding(.vertical, 8)
            .frame(minHeight: 48)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!chevron)
    }
}

/// Plays the message alert once, as a customer message would (the phone's silent switch applies).
enum DeviceAlertPlayer {
    static func play(sound: Bool, vibrate: Bool) {
        if sound { AudioServicesPlaySystemSound(1007) }
        if vibrate { AudioServicesPlaySystemSound(kSystemSoundID_Vibrate) }
    }
}
