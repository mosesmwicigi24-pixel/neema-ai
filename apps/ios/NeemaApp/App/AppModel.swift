import Foundation
import SwiftUI
import AVFoundation
import UserNotifications
import NeemaCore

/// The dashboard page's shared state (Android's `DashboardViewModel`): the
/// signed-in agent, the team, permissions, the current view, cross-view
/// requests and toasts. Every screen receives this.
@MainActor
final class AppModel: ObservableObject {
    static let AGENTS_POLL_MS: Int64 = 180_000
    static let FORBIDDEN_WINDOW_MS: Int64 = 1_000
    static let FORBIDDEN_COOLDOWN_MS: Int64 = 15_000

    let container: AppContainer
    /// The dashboard's orders list: polled, pushed, snapshotted per agent (the orders part of Android's DashboardViewModel).
    let ordersFeed: OrdersFeed
    /// The hub's catalogue: read at sign-in and every five minutes while in front, snapshotted per agent.
    let catalogFeed: CatalogFeed
    /// The screens' view of the shell; their logic lives in NeemaCore and is created per sign-in.
    let inboxHost: ShellInboxHost
    /// The softphone (Android `container.calls`): one for the process, started once; signed-out it ignores every frame.
    let calls: CallManager
    /// The bell's list (Android `container.notifications`) and the message alerts, started per sign-in.
    let notifications: AgentNotifications
    let messageAlerts: MessageAlerts
    private let callRinger: CallRinger
    private let alertSink: SystemAlertSink
    /// Delivers the vault's crash reports once someone is signed in (Android `CrashReporter`).
    let crashReporter: CrashReporter
    private let signedInFlag: Watched<Bool>
    @Published private(set) var callsScreen: CallsScreenModel?
    @Published private(set) var callCard: CallCardModel?
    @Published private(set) var bell: BellModel?
    @Published private(set) var unreadBell = 0
    @Published var bellOpen = false
    @Published private(set) var inboxScreen: InboxScreenModel?
    @Published private(set) var ordersScreen: OrdersScreenModel?
    @Published private(set) var catalogScreen: CatalogScreenModel?
    @Published private(set) var dealsScreen: DealsScreenModel?
    @Published private(set) var leadsScreen: LeadsScreenModel?
    @Published private(set) var overviewScreen: OverviewScreenModel?
    @Published private(set) var reportsScreen: ReportsScreenModel?
    @Published private(set) var teamScreen: TeamScreenModel?
    @Published private(set) var profileScreen: ProfileScreenModel?
    @Published private(set) var settingsScreen: SettingsScreenModel?

    @Published private(set) var session: Session?
    @Published private(set) var me: Agent? {
        didSet { inboxHost.me.update(me) }
    }
    @Published private(set) var agents: [Agent] = [] {
        didSet { inboxHost.agents.update(agents) }
    }
    @Published private(set) var access = Access()
    @Published private(set) var inboxHuman = 0
    @Published private(set) var pendingOrders = 0
    @Published private(set) var nav = NavHistory()
    @Published private(set) var toast: Toast?
    @Published var sessionExpired = false {
        didSet { inboxHost.sessionExpired.update(sessionExpired) }
    }
    @Published private(set) var connected = false
    @Published private(set) var online = true
    @Published private(set) var dark = false
    @Published private(set) var signingOut = false
    /// A feature is full-screen (an open thread on a phone): the chrome hides.
    @Published var immersive = false
    @Published var drawerOpen = false
    @Published var accountMenuOpen = false
    /// Cross-view requests: a chat to open (wa_id, external_id, "phone|ref" or id), a caller to focus.
    @Published var openConvKey: String? {
        didSet { if inboxHost.openConvKey.value != openConvKey { inboxHost.openConvKey.update(openConvKey) } }
    }
    @Published var callsFocusKey: String? {
        didSet { if inboxHost.callsFocusKey.value != callsFocusKey { inboxHost.callsFocusKey.update(callsFocusKey) } }
    }

    private let toasts: ToastPresenter
    private var subs: [Subscription] = []
    /// A deep link that arrived signed out: replayed right after sign-in (page.tsx's sessionStorage "neema:deeplink").
    @Published private(set) var pendingLink: DeepLink?
    private var pollTask: Task<Void, Never>?
    private var forbiddenRefresh: Coalescer?
    private var lastForbiddenRefresh: Int64 = .min / 2
    private var signedInAgent: String?

    /// `ringer`: the screenshot gallery passes a silent one so CallKit's system call UI never opens over the test host.
    init(container: AppContainer, ringer: CallRinger? = nil) {
        self.container = container
        session = container.sessionStore.current
        dark = container.prefs.dark.value
        online = container.online.value
        toasts = ToastPresenter(foreground: container.foreground)
        let snapshots = container.snapshots
        ordersFeed = OrdersFeed(api: container.api, foreground: container.foreground, socketEvents: container.socket.events,
                                reconnected: container.socket.reconnected, snapshots: snapshots)
        catalogFeed = CatalogFeed(api: container.api, foreground: container.foreground, snapshots: snapshots)
        let sessions = container.sessionStore
        let ringer = ringer ?? CallKitRinger()
        callRinger = ringer
        calls = CallManager(
            api: NeemaCallApi(container.api), events: container.socket.events, connected: container.socket.connected, foreground: container.foreground,
            signedIn: { sessions.current != nil }, media: makeCallMedia(), ringer: ringer, audio: SessionCallAudio(),
            micGranted: { AVAudioSession.sharedInstance().recordPermission == .granted },
            outboxDir: FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first.map { $0.appendingPathComponent("call-recordings") }
                ?? FileManager.default.temporaryDirectory.appendingPathComponent("call-recordings"),
            myAgentId: { sessions.current?.agentId }, myAgentName: { sessions.current?.name }
        )
        let sink = SystemAlertSink()
        alertSink = sink
        notifications = AgentNotifications(events: container.socket.events, appPrefs: container.prefs, store: container.prefs.raw, sink: sink)
        messageAlerts = MessageAlerts(events: container.socket.events, notifications: notifications, prefs: container.prefs, sink: sink, player: SystemAlertPlayer())
        inboxHost = ShellInboxHost(container: container, ordersFeed: ordersFeed, catalogFeed: catalogFeed, snapshots: snapshots, calls: calls)
        let flag = Watched<Bool>(container.sessionStore.current != nil)
        signedInFlag = flag
        crashReporter = CrashReporter(http: container.http, signedIn: flag, vault: container.crashVault)
        inboxHost.onToast = { [weak self] message, type in self?.toast(message, type) }
        inboxHost.onRefreshAgents = { [weak self] in try await self?.refreshAgents() }
        inboxHost.onRefetchAgents = { [weak self] in self?.refetchAgents() }
        inboxHost.onRefetchMe = { [weak self] in self?.refetchMe() }
        forbiddenRefresh = Coalescer(windowMs: Self.FORBIDDEN_WINDOW_MS) { [weak self] in
            await MainActor.run {
                guard let self = self else { return }
                self.lastForbiddenRefresh = AppClock.now()
                self.refetchMe()
                self.refetchAgents()
            }
        }
        calls.canManageSettings = { [weak self] in self?.access.can(Perms.MANAGE_SETTINGS) ?? false }
        // The system call UI's Answer / Decline (CallKit) come back as the softphone's own actions.
        if let kit = ringer as? CallKitRinger {
            kit.onAction = { [weak self] action, id in Task { @MainActor in self?.calls.handleAction(action, id: id) } }
        }
        calls.start()
        // An error caught at the edge (a WebRTC callback, a background task) is written down and sent on.
        let vault = container.crashVault
        let reporter = crashReporter
        CrashHooks.install(vault) { reporter.flushSoon() }
        crashReporter.start()
        subscribe()
        if let s = session { signedIn(s) }
    }

    private func subscribe() {
        subs.append(container.sessionStore.session.observe { [weak self] s in
            Task { @MainActor in self?.sessionChanged(s) }
        })
        subs.append(container.http.sessionExpired.observe { [weak self] in
            Task { @MainActor in self?.sessionExpired = true }
        })
        subs.append(container.http.forbidden.observe { [weak self] _ in
            Task { @MainActor in self?.onForbidden() }
        })
        subs.append(container.socket.connected.observe { [weak self] up in
            Task { @MainActor in self?.connected = up }
        })
        subs.append(container.online.observe { [weak self] up in
            Task { @MainActor in self?.online = up }
        })
        // Every notification frame toasts "title: body" as it lands in the bell (page.tsx showToast; the
        // inbox and the orders feed refetch themselves from the same frames).
        subs.append(notifications.incoming.observe { [weak self] n in
            Task { @MainActor in self?.toast("\(n.title): \(n.body)", .info) }
        })
        subs.append(toasts.current.observe { [weak self] t in
            Task { @MainActor in self?.toast = t }
        })
        // The inbox keeps the shell's badge fresh, and consumes the open-conversation request.
        subs.append(inboxHost.inboxSummary.observe { [weak self] s in
            Task { @MainActor in self?.inboxHuman = s?.human ?? 0 }
        })
        subs.append(inboxHost.openConvKey.observe { [weak self] k in
            Task { @MainActor in
                guard let self = self else { return }
                if self.openConvKey != k { self.openConvKey = k }
            }
        })
        // The calls screen consumes the focus request; the deep link sets it.
        subs.append(inboxHost.callsFocusKey.observe { [weak self] k in
            Task { @MainActor in
                guard let self = self else { return }
                if self.callsFocusKey != k { self.callsFocusKey = k }
            }
        })
        // The bell's count.
        subs.append(notifications.items.observe { [weak self] list in
            Task { @MainActor in self?.unreadBell = list.filter { !$0.read }.count }
        })
        // The orders feed keeps the nav's pending badge fresh.
        subs.append(ordersFeed.orders.observe { [weak self] _ in
            Task { @MainActor in
                guard let self = self else { return }
                self.pendingOrders = self.ordersFeed.pendingOrders
            }
        })
    }

    // ── Session ─────────────────────────────────────────────────────────────

    private func sessionChanged(_ s: Session?) {
        let before = session
        session = s
        guard let s = s else {
            if before != nil { clearAgentState() }
            return
        }
        if s.agentId != signedInAgent { signedIn(s) }
    }

    private func signedIn(_ s: Session) {
        signedInAgent = s.agentId
        signedInFlag.update(true)
        askForNotificationsOnce()
        nav = NavHistory()
        republishAccess()
        startPolls()
        ordersFeed.start(agentId: s.agentId)
        catalogFeed.start(agentId: s.agentId)
        startScreens()
        notifications.start(foreground: container.foreground)
        messageAlerts.start(foreground: container.foreground)
        alertSink.refreshPermission()
        unreadBell = notifications.unread
        refetchCallChannels()
        refetchMe()
        if let link = pendingLink {
            pendingLink = nil
            applyDeepLink(link)
        }
    }

    func login(email: String, password: String) async throws {
        _ = try await container.auth.login(email: email, password: password)
    }

    func reauthenticate(password: String) async throws {
        guard let email = session?.email ?? container.sessionStore.lastEmail else { throw AuthError(AuthRepository.INVALID) }
        _ = try await container.auth.login(email: email, password: password)
        onReauthenticated()
    }

    func onReauthenticated() {
        sessionExpired = false
        refetchMe()
        refetchAgents()
        ordersFeed.refetchOrders()
        catalogFeed.refetchCatalog()
        refreshInbox()
    }

    /// Sidebar.tsx's sign-out: the token, the bell and every per-agent state go.
    /// A live call is ended first and the server told, bounded (CallManager.endForSignOut: 3 s;
    /// a merely ringing call is left ringing for colleagues).
    func logout() {
        if signingOut { return }
        signingOut = true
        stopPolls()
        if calls.state.value.live && calls.state.value.phase != .ringing {
            Task { @MainActor [weak self] in
                guard let self = self else { return }
                await self.endCallBounded()
                self.finishLogout()
            }
        } else {
            finishLogout()
        }
    }

    /// `endForSignOut` bounds itself at 3 s; this only guards against it ever
    /// hanging (DashboardViewModel.SIGN_OUT_CALL_MS).
    private func endCallBounded() async {
        let calls = self.calls
        await withTaskGroup(of: Void.self) { group in
            group.addTask { @MainActor in await calls.endForSignOut() }
            group.addTask { try? await Task.sleep(nanoseconds: UInt64(Self.SIGN_OUT_CALL_MS) * 1_000_000) }
            _ = await group.next()
            group.cancelAll()
        }
    }

    private func finishLogout() {
        container.auth.logout()
        session = nil
        notifications.clear()
        clearAgentState()
        pendingLink = nil
        signingOut = false
    }

    private func clearAgentState() {
        signedInFlag.update(false)
        stopPolls()
        stopScreens()
        toasts.cancel()
        me = nil
        agents = []
        inboxHuman = 0
        pendingOrders = 0
        openConvKey = nil
        callsFocusKey = nil
        bellOpen = false
        unreadBell = 0
        sessionExpired = false
        immersive = false
        drawerOpen = false
        accountMenuOpen = false
        signedInAgent = nil
        nav = NavHistory()
        republishAccess()
    }

    // ── The screens ─────────────────────────────────────────────────────────

    /// One model per screen per sign-in (Android's per-agent ViewModelStore).
    private func startScreens() {
        inboxScreen?.close()
        let vm = InboxViewModel(host: inboxHost, media: AppleMediaAccess())
        inboxScreen = InboxScreenModel(vm: vm, customerHost: inboxHost)
        ordersScreen?.close()
        ordersScreen = OrdersScreenModel(vm: OrdersViewModel(host: inboxHost))
        catalogScreen?.close()
        catalogScreen = CatalogScreenModel(vm: CatalogViewModel(host: inboxHost))
        dealsScreen?.close()
        dealsScreen = DealsScreenModel(vm: DealsViewModel(host: inboxHost))
        leadsScreen?.close()
        leadsScreen = LeadsScreenModel(vm: LeadsViewModel(host: inboxHost))
        overviewScreen?.close()
        overviewScreen = OverviewScreenModel(vm: OverviewViewModel(host: inboxHost))
        reportsScreen?.close()
        reportsScreen = ReportsScreenModel(vm: ReportsViewModel(host: inboxHost))
        teamScreen?.close()
        teamScreen = TeamScreenModel(vm: TeamViewModel(host: inboxHost))
        profileScreen?.close()
        profileScreen = ProfileScreenModel(vm: ProfileViewModel(host: inboxHost), prefs: container.prefs)
        settingsScreen?.close()
        settingsScreen = SettingsScreenModel(vm: SettingsViewModel(host: inboxHost), catalog: inboxHost.catalog)
        callsScreen?.close()
        callsScreen = CallsScreenModel(vm: CallsViewModel(host: inboxHost), calls: calls)
        callCard?.close()
        callCard = CallCardModel(calls: calls)
        bell?.close()
        bell = BellModel(center: notifications, prefs: container.prefs)
    }

    private func stopScreens() {
        inboxScreen?.close()
        inboxScreen = nil
        ordersScreen?.close()
        ordersScreen = nil
        catalogScreen?.close()
        catalogScreen = nil
        dealsScreen?.close()
        dealsScreen = nil
        leadsScreen?.close()
        leadsScreen = nil
        overviewScreen?.close()
        overviewScreen = nil
        reportsScreen?.close()
        reportsScreen = nil
        teamScreen?.close()
        teamScreen = nil
        profileScreen?.close()
        profileScreen = nil
        settingsScreen?.close()
        settingsScreen = nil
        callsScreen?.close()
        callsScreen = nil
        callCard?.close()
        callCard = nil
        bell?.close()
        bell = nil
        notifications.stop()
        messageAlerts.stop()
        ordersFeed.stop()
        catalogFeed.stop()
        inboxHost.inboxSummary.update(nil)
        inboxHost.openConvKey.update(nil)
        inboxHost.composerPrefill.update(nil)
        inboxHost.callChannels.update(nil)
        inboxHost.callsFocusKey.update(nil)
    }

    /// Once per install, right after the first sign-in (Android `MainActivity.maybeAskForNotifications`):
    /// the system's own prompt, so a customer's message or a call can alert from the background.
    private func askForNotificationsOnce() {
        let prefs = container.prefs.raw
        if prefs.bool(Self.ASKED_NOTIFICATIONS, default: false) { return }
        prefs.set(true, for: Self.ASKED_NOTIFICATIONS)
        let sink = alertSink
        UNUserNotificationCenter.current().getNotificationSettings { s in
            guard s.authorizationStatus == .notDetermined else { return }
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in sink.refreshPermission() }
        }
    }

    static let ASKED_NOTIFICATIONS = "asked_post_notifications"
    /// The shell's own cap on waiting for the call to end before the token goes (the terminate request needs it).
    static let SIGN_OUT_CALL_MS: Int64 = 4_000

    /// A row in the bell: read, and where it names a customer (or an order) the
    /// app also takes the agent there — the same target as tapping its phone notification.
    func openNotification(_ n: AppNotification) {
        notifications.markRead(n.id)
        let view = AgentNotifications.viewFor(n).flatMap { ViewId.fromWeb($0) }
        if n.convKey != nil || view != nil {
            bellOpen = false
            drawerOpen = false
            if let k = n.convKey { openConversationFor(k) } else if let v = view { navigate(v) }
        }
    }

    /// GET /admin/calls/channels: which apps can call now (the customer panel's Messenger Call button follows it).
    func refetchCallChannels() {
        let agent = signedInAgent
        Task { [weak self] in
            guard let self = self else { return }
            if let ch = try? await self.container.api.calls.channels(), self.signedInAgent == agent { self.inboxHost.callChannels.update(ch) }
        }
    }

    /// Words another view wants in a thread's composer (never sent by themselves).
    func prefillComposer(convId: String, text: String) {
        inboxHost.composerPrefill.update(ComposerPrefill(convId: convId, text: text))
        openConversationFor(convId)
    }

    /// A notification landed: the inbox refetches.
    func refreshInbox() { inboxHost.inboxRefresh.emit() }

    /// The freshest record of who this agent is: the team-list row, else /admin/me.
    var currentAgent: Agent? { agents.first { $0.id == session?.agentId } ?? me }

    /// The open thread's controls follow the web's role rules (ConversationsView.tsx).
    var inboxPerms: InboxPerms { InboxPerms.of(agent: currentAgent, sessionAgentId: session?.agentId) }

    // ── Me, the team, access ────────────────────────────────────────────────

    /// GET /admin/me: up to 3 tries with attempt × 500 ms between, no retry on 401.
    func refetchMe() {
        let agent = signedInAgent
        Task { [weak self] in
            guard let self = self else { return }
            for attempt in 1...3 {
                do {
                    let m = try await self.container.api.profile.me()
                    guard self.signedInAgent == agent else { return }
                    self.me = m
                    let nextAuth = self.session?.mode == "nextauth"
                    self.container.auth.updateProfile(name: m.name, email: m.email, role: nextAuth ? m.role : nil, isSuperuser: nextAuth ? m.isSuperuser : nil)
                    self.republishAccess()
                    return
                } catch let e as ApiError where e.status == 401 {
                    return
                } catch {
                    if attempt < 3 { try? await Task.sleep(nanoseconds: UInt64(attempt) * 500_000_000) }
                }
            }
        }
    }

    func refetchAgents() {
        Task { [weak self] in
            // keep what is on screen on a failure; the poll tries again
            _ = try? await self?.refreshAgents()
        }
    }

    /// Re-read the team list and return when it has landed (a pull-to-refresh waits for it); throws on failure.
    func refreshAgents() async throws {
        let agent = signedInAgent
        let list = try await container.api.agents.list()
        guard signedInAgent == agent else { return }
        agents = list
        republishAccess()
    }

    private func republishAccess() {
        access = ShellRules.access(agents: agents, me: me, session: session)
        inboxHost.canManageSettings = access.can(Perms.MANAGE_SETTINGS)
    }

    /// page.tsx `can(perm)`: the one permission test every feature uses.
    func can(_ perm: String) -> Bool { access.can(perm) }

    var isAdmin: Bool { access.isAdmin }

    var navItems: [NavItem] {
        ShellRules.navItems(can: { self.can($0) }, humanConvs: inboxHuman, pendingOrders: pendingOrders)
    }

    private func onForbidden() {
        if AppClock.now() - lastForbiddenRefresh < Self.FORBIDDEN_COOLDOWN_MS { return }
        forbiddenRefresh?.kick()
    }

    // ── Polls (only while in front; a return refetches at once) ─────────────

    private func startPolls() {
        stopPolls()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                if let self = self, self.container.foreground.value { self.refetchAgents() }
                try? await Task.sleep(nanoseconds: UInt64(Self.AGENTS_POLL_MS) * 1_000_000)
            }
        }
    }

    private func stopPolls() {
        pollTask?.cancel()
        pollTask = nil
    }

    /// The app came to the front (or left it). Coming back: the live policy
    /// reconnects a closed socket itself; `nudge` is for one already wanted and
    /// mid-backoff, so it is only sent when the foreground state did not change.
    func setForeground(_ front: Bool) {
        let was = container.foreground.value
        container.foreground.update(front)
        if front {
            if was { container.socket.nudge() }
            if !was && session != nil { refetchAgents() }
        }
    }

    // ── Navigation and deep links ───────────────────────────────────────────

    func navigate(_ v: ViewId) {
        nav.navigate(v)
        drawerOpen = false
    }

    @discardableResult
    func back() -> Bool { nav.back() }

    /// Esc on a hardware keyboard: close the topmost overlay (the bell, the account menu, the
    /// drawer, a thread open full-screen on a phone), never leave the view at the root
    /// (`escapeIsBack`). False when nothing was open.
    @discardableResult
    func escapeBack() -> Bool {
        let threadOpen = inboxScreen?.thread.threadOpen == true && view == .conversations
        let somethingOpen = bellOpen || accountMenuOpen || drawerOpen || threadOpen
        guard escapeIsBack(key: .escape, modified: false, somethingOpen: somethingOpen) else { return false }
        if bellOpen { bellOpen = false }
        else if accountMenuOpen { accountMenuOpen = false }
        else if drawerOpen { drawerOpen = false }
        else if threadOpen { inboxScreen?.vm.closeThread() }
        return true
    }

    var view: ViewId { nav.view }

    func openConversationFor(_ key: String) {
        openConvKey = key
        navigate(.conversations)
    }

    func focusCalls(_ waId: String) {
        callsFocusKey = waId
        navigate(.calls)
    }

    func open(_ url: URL) {
        guard let link = DeepLink(url: url) else { return }
        applyDeepLink(link)
    }

    /// Signed out, the link is kept and replayed right after sign-in; a newer link replaces an older one.
    func applyDeepLink(_ link: DeepLink) {
        if link.isEmpty { return }
        if session == nil {
            pendingLink = link
            return
        }
        switch link.action {
        case .openConversation(let key): openConversationFor(key)
        case .focusCalls(let waId): focusCalls(waId)
        case .navigate(let v): navigate(v)
        case nil: break
        }
    }

    // ── Saved state across a process death (Android's SavedStateHandle) ──────

    /// The view, its history and whose they are, as the scene stores them
    /// (`@SceneStorage` in `DashboardShell`): restored after the system killed
    /// the app in the background, never after a sign-out.
    var savedNav: String {
        guard let id = signedInAgent else { return "" }
        let names = ([nav.view] + nav.history).map { $0.rawValue }
        return ([id] + names).joined(separator: ",")
    }

    /// A view restored after a process death belongs to whoever was signed in
    /// then: someone else starts on the inbox. Unknown names are ignored.
    func restoreNav(_ saved: String) {
        let parts = saved.split(separator: ",").map(String.init)
        guard parts.count >= 2, parts[0] == signedInAgent, let view = ViewId(rawValue: parts[1]) else { return }
        let history = parts.dropFirst(2).compactMap { ViewId(rawValue: $0) }
        nav = NavHistory(view: view, history: history)
    }

    /// The pending link as the scene stores it (`@SceneStorage` in `RootView`), so the
    /// login screen being killed in the background does not lose it either.
    var savedPendingLink: String {
        guard let l = pendingLink else { return "" }
        return [l.open, l.ref, l.view, l.caller].map { $0 ?? "" }.joined(separator: "\u{1F}")
    }

    func restorePendingLink(_ saved: String) {
        guard session == nil, pendingLink == nil, !saved.isEmpty else { return }
        let f = saved.split(separator: "\u{1F}", omittingEmptySubsequences: false).map { $0.isEmpty ? nil : String($0) }
        guard f.count == 4 else { return }
        let link = DeepLink(open: f[0], ref: f[1], view: f[2], caller: f[3])
        if !link.isEmpty { pendingLink = link }
    }

    /// The toast on screen, as the scene stores it: a toast restored after a
    /// process death gets its time on screen again; an expired one is gone.
    var savedToast: String {
        guard let t = toast else { return "" }
        return "\(t.type.rawValue)\u{1F}\(t.message)"
    }

    func restoreToast(_ saved: String) {
        guard toast == nil, !saved.isEmpty else { return }
        let f = saved.split(separator: "\u{1F}", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
        guard f.count == 2, let type = ToastType(rawValue: f[0]), !f[1].isEmpty else { return }
        toasts.show(f[1], type)
    }

    // ── Toasts, theme, errors ───────────────────────────────────────────────

    func toast(_ message: String, _ type: ToastType = .success) {
        if type == .error { Haptics.error() }
        toasts.show(message, type)
    }

    func setDark(_ v: Bool) {
        dark = v
        container.prefs.setDark(v)
    }

    /// Friendly message for a failed call, for toasts and inline errors.
    nonisolated func errorText(_ e: Error) -> String { ErrorText.of(e) }
}
