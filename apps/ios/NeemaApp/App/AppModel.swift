import Foundation
import SwiftUI
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
    @Published private(set) var inboxScreen: InboxScreenModel?
    @Published private(set) var ordersScreen: OrdersScreenModel?
    @Published private(set) var catalogScreen: CatalogScreenModel?

    @Published private(set) var session: Session?
    @Published private(set) var me: Agent?
    @Published private(set) var agents: [Agent] = []
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
    @Published var callsFocusKey: String?

    private let toasts: ToastPresenter
    private var subs: [Subscription] = []
    private var pendingLink: DeepLink?
    private var pollTask: Task<Void, Never>?
    private var forbiddenRefresh: Coalescer?
    private var lastForbiddenRefresh: Int64 = .min / 2
    private var signedInAgent: String?

    init(container: AppContainer) {
        self.container = container
        session = container.sessionStore.current
        dark = container.prefs.dark.value
        online = container.online.value
        toasts = ToastPresenter(foreground: container.foreground)
        let snapshots = SnapshotCache.standard()
        ordersFeed = OrdersFeed(api: container.api, foreground: container.foreground, socketEvents: container.socket.events,
                                reconnected: container.socket.reconnected, snapshots: snapshots)
        catalogFeed = CatalogFeed(api: container.api, foreground: container.foreground, snapshots: snapshots)
        inboxHost = ShellInboxHost(container: container, ordersFeed: ordersFeed, catalogFeed: catalogFeed, snapshots: snapshots)
        inboxHost.onToast = { [weak self] message, type in self?.toast(message, type) }
        forbiddenRefresh = Coalescer(windowMs: Self.FORBIDDEN_WINDOW_MS) { [weak self] in
            await MainActor.run {
                guard let self = self else { return }
                self.lastForbiddenRefresh = AppClock.now()
                self.refetchMe()
                self.refetchAgents()
            }
        }
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
        nav = NavHistory()
        republishAccess()
        startPolls()
        ordersFeed.start(agentId: s.agentId)
        catalogFeed.start(agentId: s.agentId)
        startScreens()
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
    func logout() {
        if signingOut { return }
        signingOut = true
        stopPolls()
        container.auth.logout()
        session = nil
        clearAgentState()
        pendingLink = nil
        signingOut = false
    }

    private func clearAgentState() {
        stopPolls()
        stopScreens()
        toasts.cancel()
        me = nil
        agents = []
        inboxHuman = 0
        pendingOrders = 0
        openConvKey = nil
        callsFocusKey = nil
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
    }

    private func stopScreens() {
        inboxScreen?.close()
        inboxScreen = nil
        ordersScreen?.close()
        ordersScreen = nil
        catalogScreen?.close()
        catalogScreen = nil
        ordersFeed.stop()
        catalogFeed.stop()
        inboxHost.inboxSummary.update(nil)
        inboxHost.openConvKey.update(nil)
        inboxHost.composerPrefill.update(nil)
        inboxHost.callChannels.update(nil)
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
        let agent = signedInAgent
        Task { [weak self] in
            guard let self = self else { return }
            do {
                let list = try await self.container.api.agents.list()
                guard self.signedInAgent == agent else { return }
                self.agents = list
                self.republishAccess()
            } catch {
                // keep what is on screen; the poll tries again
            }
        }
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

    // ── Toasts, theme, errors ───────────────────────────────────────────────

    func toast(_ message: String, _ type: ToastType = .success) { toasts.show(message, type) }

    func setDark(_ v: Bool) {
        dark = v
        container.prefs.setDark(v)
    }

    /// Friendly message for a failed call, for toasts and inline errors.
    nonisolated func errorText(_ e: Error) -> String { ErrorText.of(e) }
}
