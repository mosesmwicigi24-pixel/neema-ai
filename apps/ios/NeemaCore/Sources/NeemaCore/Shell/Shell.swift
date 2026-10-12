import Foundation

/// The dashboard's views, as the web's `?view=` names and the app's labels
/// (Android `DashboardViewModel.ViewId`).
public enum ViewId: String, CaseIterable, Codable, Sendable {
    case conversations, calls, orders, reports, deals, leads, overview, catalog, agents, settings, profile

    public var label: String {
        switch self {
        case .conversations: return "Inbox"
        case .calls: return "Calls"
        case .orders: return "Orders"
        case .reports: return "Reports"
        case .deals: return "Deals"
        case .leads: return "Leads"
        case .overview: return "Analytics"
        case .catalog: return "Catalog"
        case .agents: return "Team"
        case .settings: return "Settings"
        case .profile: return "Profile"
        }
    }

    /// The web's `?view=` names.
    public static func fromWeb(_ name: String?) -> ViewId? {
        switch name?.lowercased() {
        case "conversations", "inbox": return .conversations
        case "calls": return .calls
        case "orders": return .orders
        case "reports": return .reports
        case "deals": return .deals
        case "leads": return .leads
        case "overview", "analytics": return .overview
        case "catalog": return .catalog
        case "agents", "team": return .agents
        case "settings": return .settings
        case "profile": return .profile
        default: return nil
        }
    }
}

/// What a dashboard URL asks for: `?open=<wa_id|external_id|conv id>[&ref=<order>]`,
/// `?view=calls&caller=<wa_id>`, or `?view=<name>`.
public struct DeepLink: Equatable, Sendable {
    public var open: String?
    public var ref: String?
    public var view: String?
    public var caller: String?

    public init(open: String? = nil, ref: String? = nil, view: String? = nil, caller: String? = nil) {
        self.open = open
        self.ref = ref
        self.view = view
        self.caller = caller
    }

    public var isEmpty: Bool { isBlank(open) && isBlank(view) }

    /// From a dashboard URL's (https or neema://) query parameters.
    public static func of(_ param: (String) -> String?) -> DeepLink {
        DeepLink(open: param("open"), ref: param("ref"), view: param("view"), caller: param("caller"))
    }

    public static let dashboardHost = "neema.bethanyhouse.co.ke"

    /// The URLs the app accepts: `https://neema.bethanyhouse.co.ke/dashboard…` and any `neema://…`.
    public init?(url: URL) {
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        let scheme = (c.scheme ?? "").lowercased()
        if scheme == "neema" {
            // accepted
        } else if scheme == "https", (c.host ?? "").lowercased() == Self.dashboardHost, c.path.hasPrefix("/dashboard") {
            // accepted
        } else {
            return nil
        }
        let items = c.queryItems ?? []
        self = DeepLink.of { name in items.first { $0.name == name }?.value }
    }

    public enum Action: Equatable, Sendable {
        case openConversation(key: String)
        case focusCalls(waId: String)
        case navigate(ViewId)
    }

    /// What to do with the link once signed in (nil: nothing it asks for is known).
    public var action: Action? {
        let v = ViewId.fromWeb(view)
        if let o = open, !isBlank(o) {
            if let r = ref, !isBlank(r) { return .openConversation(key: "\(o)|\(r)") }
            return .openConversation(key: o)
        }
        if v == .calls, let c = caller, !isBlank(c) { return .focusCalls(waId: c) }
        if let v = v { return .navigate(v) }
        return nil
    }
}

private func isBlank(_ s: String?) -> Bool { (s ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

/// Where the agent is and the way back: each view at most once, most recent
/// last, at most ten. Back walks it: the previous view, then the inbox, and
/// only then out of the app.
public struct NavHistory: Equatable, Codable, Sendable {
    public static let MAX = 10
    public private(set) var view: ViewId
    public private(set) var history: [ViewId]

    public init(view: ViewId = .conversations, history: [ViewId] = []) {
        self.view = view
        self.history = history
    }

    public var canGoBack: Bool { !history.isEmpty || view != .conversations }

    public mutating func navigate(_ v: ViewId) {
        let from = view
        if v == from { return }
        history.removeAll { $0 == v }
        history.append(from)
        while history.count > Self.MAX { history.removeFirst() }
        view = v
    }

    /// False when already on the inbox with nowhere to go back to.
    @discardableResult
    public mutating func back() -> Bool {
        if let to = history.popLast() {
            view = to
            return true
        }
        if view != .conversations {
            view = .conversations
            return true
        }
        return false
    }

    public mutating func reset() {
        history.removeAll()
        view = .conversations
    }
}

public enum ToastType: String, Codable, Sendable { case success, error, warning, info }

public struct Toast: Equatable, Sendable, Identifiable {
    public let message: String
    public let type: ToastType
    public let id: Int64

    public init(message: String, type: ToastType = .success, id: Int64 = Int64(Date().timeIntervalSince1970 * 1_000_000)) {
        self.message = message
        self.type = type
        self.id = id
    }
}

/// page.tsx showToast: one toast at a time, replaced by the next, gone after
/// 3.5 s. The 3.5 s count only while the app is in front — a toast raised in
/// the background waits for the agent, then gets what it had left (at least
/// `RETURN_MIN_MS`). Each toast gets its own full time.
public final class ToastPresenter: @unchecked Sendable {
    public static let TOAST_MS: Int64 = 3_500
    public static let RETURN_MIN_MS: Int64 = 1_500

    public let current = Watched<Toast?>(nil)
    /// Every toast raised, for logs and tests.
    public let toasts = Signal<Toast>(buffer: 16)

    private let foreground: Watched<Bool>
    private let sleep: Sleeper
    private let now: () -> Int64
    private let lock = NSLock()
    private var timer: Task<Void, Never>?

    public init(foreground: Watched<Bool>, sleep: @escaping Sleeper = realSleep, now: @escaping () -> Int64 = AppClock.now) {
        self.foreground = foreground
        self.sleep = sleep
        self.now = now
    }

    public func show(_ message: String, _ type: ToastType = .success) { show(Toast(message: message, type: type)) }

    public func show(_ t: Toast) {
        toasts.emit(t)
        current.value = t
        lock.sync { timer?.cancel() }
        let task = Task { [weak self] in guard let self = self else { return }; await self.run(t) }
        lock.sync { timer = task }
    }

    private func run(_ t: Toast) async {
        var left = Self.TOAST_MS
        while left > 0 {
            if Task.isCancelled { return }
            await Self.first(of: foreground) { $0 }
            if Task.isCancelled { return }
            let from = now()
            let wentAway = await Self.race(sleep: sleep, ms: left, until: foreground) { !$0 }
            if Task.isCancelled { return }
            left = wentAway ? max(left - (now() - from), Self.RETURN_MIN_MS) : 0
        }
        dismiss(t)
    }

    /// Clears `t` if it is still the one showing (a newer toast keeps its own time).
    public func dismiss(_ t: Toast? = nil) {
        let shown = current.value
        guard let s = shown else { return }
        if let t = t, t.id != s.id { return }
        current.value = nil
    }

    public func cancel() {
        lock.sync { timer?.cancel(); timer = nil }
        current.value = nil
    }

    static func first(of w: Watched<Bool>, _ pred: @escaping (Bool) -> Bool) async {
        for await v in w.stream() where pred(v) { return }
    }

    /// True when the foreground condition fired before the sleep ended.
    static func race(sleep: @escaping Sleeper, ms: Int64, until w: Watched<Bool>, _ pred: @escaping (Bool) -> Bool) async -> Bool {
        await withTaskGroup(of: Bool.self) { group in
            group.addTask { await first(of: w, pred); return true }
            group.addTask { try? await sleep(ms); return false }
            let r = await group.next() ?? false
            group.cancelAll()
            return r
        }
    }
}

/// What the signed-in agent may do (page.tsx `can()` / `isAdmin`).
public struct Access: Equatable, Sendable {
    public var permissions: Set<String>
    public var isAdmin: Bool
    public init(permissions: Set<String> = [], isAdmin: Bool = false) {
        self.permissions = permissions
        self.isAdmin = isAdmin
    }
    public func can(_ perm: String) -> Bool { permissions.contains(perm) }
}

public struct NavItem: Equatable, Sendable {
    public let view: ViewId
    public let badge: Int
    public init(_ view: ViewId, badge: Int = 0) {
        self.view = view
        self.badge = badge
    }
}

public enum ShellRules {
    /// My row in /admin/agents, matched by id then by email.
    public static func teamRow(agents: [Agent], me: Agent?, session: Session?) -> Agent? {
        let id = me?.id ?? session?.agentId
        let email = (me?.email.isEmpty == false ? me?.email : nil) ?? session?.email
        if let a = agents.first(where: { $0.id == id }) { return a }
        if let e = email { return agents.first { $0.email.caseInsensitiveCompare(e) == .orderedSame } }
        return nil
    }

    /// getAgentPermissions(currentAgent) — or nothing at all while there is no
    /// team row, exactly as the web's `can()` returns false then.
    public static func permissions(teamRow: Agent?) -> [String] { teamRow.map(Perms.of) ?? [] }

    /// page.tsx `isAdmin`: the session's role is admin, or the team row's role
    /// is admin, or the team row is a superuser, or `can(manage_agents)`.
    public static func isAdmin(session: Session?, teamRow: Agent?) -> Bool {
        session?.role == "admin" || teamRow?.role == "admin" || teamRow?.isSuperuser == true || permissions(teamRow: teamRow).contains(Perms.MANAGE_AGENTS)
    }

    public static func access(agents: [Agent], me: Agent?, session: Session?) -> Access {
        let row = teamRow(agents: agents, me: me, session: session)
        return Access(permissions: Set(permissions(teamRow: row)), isAdmin: isAdmin(session: session, teamRow: row))
    }

    /// The nav, gated exactly as page.tsx builds its desktopNavItems.
    public static func navItems(can: (String) -> Bool, humanConvs: Int, pendingOrders: Int) -> [NavItem] {
        var out: [NavItem] = [NavItem(.conversations, badge: humanConvs), NavItem(.calls), NavItem(.orders, badge: pendingOrders)]
        if can(Perms.VIEW_REPORTS) { out.append(NavItem(.reports)) }
        if can(Perms.VIEW_LEADS) { out.append(NavItem(.deals)); out.append(NavItem(.leads)) }
        if can(Perms.VIEW_ANALYTICS) { out.append(NavItem(.overview)) }
        if can(Perms.VIEW_CATALOG) { out.append(NavItem(.catalog)) }
        if can(Perms.MANAGE_AGENTS) { out.append(NavItem(.agents)) }
        if can(Perms.MANAGE_SETTINGS) { out.append(NavItem(.settings)) }
        out.append(NavItem(.profile))
        return out
    }
}
