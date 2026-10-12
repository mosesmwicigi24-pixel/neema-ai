import Foundation
import XCTest
@testable import NeemaCore

/// The round-6 permission personas for the Reports / Analytics / Catalog
/// area: the signed-in agent (Fixtures.ME_ID, moses@...) as each kind of
/// account the web's `getAgentPermissions` distinguishes (Android
/// `AreaPersonaFixtures.Persona`). `install` serves them as routers/admin.py
/// does - `/admin/agents` (the SQL join carrying `role_permissions` /
/// `custom_permissions`) and the bare ORM `/admin/me`.
enum AreaPersona: CaseIterable {
    case superuser, admin, legacyAgent, legacyReadonly, sales, override, emptyOverride

    var label: String {
        switch self {
        case .superuser: return "superuser"
        case .admin: return "admin role"
        case .legacyAgent: return "legacy agent"
        case .legacyReadonly: return "legacy readonly"
        case .sales: return "custom Sales role"
        case .override: return "custom_permissions override"
        case .emptyOverride: return "empty override []"
        }
    }
    var role: String {
        switch self {
        case .admin: return "admin"
        case .legacyReadonly: return "readonly"
        default: return "agent"
        }
    }
    var superuser: Bool { self == .superuser }
    var customRole: String? { [.sales, .override, .emptyOverride].contains(self) ? "sales" : nil }
    var rolePermissions: String {
        customRole == nil ? "null" : #"["view_conversations","reply_conversations","view_orders","manage_orders"]"#
    }
    var customPermissions: String {
        switch self {
        // Per-agent override: wins over the Sales role; reports + catalogue management, no export, no analytics.
        case .override: return #"["view_conversations","view_reports","view_catalog","manage_catalog"]"#
        // `custom_permissions: []` - mapAgent's `[] ?? role_permissions` keeps the empty list, and
        // getAgentPermissions reads an empty list as "no custom permissions": the legacy fallback for the base role.
        case .emptyOverride: return "[]"
        default: return "null"
        }
    }
    /// What page.tsx's nav shows for this persona: Reports, Analytics, Catalog.
    var reports: Bool { [.superuser, .admin, .override].contains(self) }
    var analytics: Bool { [.superuser, .admin, .legacyReadonly].contains(self) }
    var catalog: Bool { self != .sales }

    /// The signed-in agent's /admin/agents row as this persona.
    func meRow() -> String {
        Fixtures.agentRow(Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", role, true, superuser, 4, 60 * 24 * 200, 1,
                          customRole: customRole, roleName: customRole.map { $0.prefix(1).uppercased() + String($0.dropFirst()) },
                          roleColor: customRole.map { _ in "#3b82f6" }, rolePermissions: rolePermissions, customPermissions: customPermissions)
    }

    /// GET /admin/me: the bare ORM row, no role columns.
    func meOrm() -> String {
        Fixtures.meOrm.replacingOccurrences(of: "\"role\":\"admin\"", with: "\"role\":\"\(role)\"")
            .replacingOccurrences(of: "\"is_superuser\":true", with: "\"is_superuser\":\(superuser)")
    }

    /// The team as the base fixtures serve it, with the signed-in agent as this persona (Grace and Brian kept).
    func agents() -> String {
        let others = (JSONValue.parse(Fixtures.agents)?.arrayValue ?? []).filter { $0.objectValue?["id"]?.stringValue != Fixtures.ME_ID }
        return "[" + ([meRow()] + others.map { $0.text }).joined(separator: ",") + "]"
    }

    func install(_ f: FakeNeema) {
        f.on("GET", "/admin/me", body: meOrm())
        f.on("GET", "/admin/agents", body: agents())
    }
}

/// Round 6 - the permission matrix for Reports, Analytics (overview) and
/// Catalog (Android `AreaPermissionMatrixTest`; its overview rows live in
/// `OverviewPermissionTests`).
///
/// What the web gates here: only the NAV ENTRIES (page.tsx: Reports behind
/// view_reports, Analytics behind view_analytics, Catalog behind
/// view_catalog). Inside ReportsView, OverviewView and CatalogView there is no
/// `can()`, no role and no isAdmin check at all: every section, every stat,
/// Export CSV (never checks export_reports) and the price-audit banner show
/// for anyone who reaches the view, and the catalogue is read-only for
/// everyone (manage_catalog unlocks nothing - the hub is the source of truth).
///
/// What the server allows: GET /admin/conversations, /admin/stats,
/// /admin/attribution, /admin/catalog and /admin/catalog/audit depend only on
/// `get_current_agent` - any signed-in agent may read them, whatever the role.
@MainActor
final class AreaPermissionMatrixTests: XCTestCase {
    private var hosts: [TestHost] = []
    private var closers: [() -> Void] = []

    override func setUp() async throws {
        try await super.setUp()
        ReportsFixtures.pinTimeZone()
        AppClock.pin(to: PINNED)
    }

    override func tearDown() async throws {
        for c in closers { c() }
        closers = []
        for h in hosts { h.logout() }
        hosts = []
        AppClock.reset()
        ReportsFixtures.restoreTimeZone()
        try await super.tearDown()
    }

    private func fake(_ p: AreaPersona) -> FakeNeema {
        let f = Fixtures.withFixtures()
        ReportsFixtures.install(f)
        p.install(f)
        return f
    }

    /// A signed-in host (Android's `dashboard(context, fake, role, superuser)`) whose team list has landed.
    private func dash(_ f: FakeNeema, _ p: AreaPersona, catalogFeed: Bool = false) async -> TestHost {
        let h = TestHost(fake: f, role: p.role, superuser: p.superuser, catalogFeed: catalogFeed)
        hosts.append(h)
        _ = try? await h.refreshAgents()
        if catalogFeed {
            await drain()
            _ = await eventually(timeout: 10) { !(h.catalogFeed?.reading ?? false) }
        }
        await drain()
        return h
    }

    private func access(_ h: TestHost, team: [Agent]? = nil) -> Access {
        ShellRules.access(agents: team ?? h.agents.value, me: nil, session: h.session.value)
    }
    private func nav(_ h: TestHost, team: [Agent]? = nil) -> [ViewId] {
        let a = access(h, team: team)
        return ShellRules.navItems(can: { a.can($0) }, humanConvs: 0, pendingOrders: 0).map { $0.view }
    }
    private func gets(_ f: FakeNeema, _ path: String) -> [FakeNeema.Call] { f.callsTo("GET", path) }
    private func writes(_ f: FakeNeema) -> [FakeNeema.Call] { f.calls.filter { $0.method != "GET" && $0.path.hasPrefix("/admin/") } }

    private func reports(_ h: TestHost) async -> ReportsViewModel {
        let v = ReportsViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 30) { v.ui.allConvs != nil || v.ui.loadError != nil }
        await drain()
        return v
    }
    private func overview(_ h: TestHost) async -> OverviewViewModel {
        let v = OverviewViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.statsLoading }
        await drain()
        return v
    }
    private func catalog(_ h: TestHost) async -> CatalogViewModel {
        let v = CatalogViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        return v
    }

    // ---- The nav: exactly page.tsx's three tests, per persona ----

    func testNavMatchesPageTsxForEveryPersona() async {
        for p in AreaPersona.allCases {
            let d = await dash(fake(p), p)
            let items = nav(d)
            XCTAssertEqual(items.contains(.reports), p.reports, "\(p.label): Reports")
            XCTAssertEqual(items.contains(.overview), p.analytics, "\(p.label): Analytics")
            XCTAssertEqual(items.contains(.catalog), p.catalog, "\(p.label): Catalog")
            XCTAssertEqual(access(d).can(Perms.VIEW_REPORTS), p.reports, "\(p.label): view_reports")
        }
    }

    func testOverrideWinsOverRoleAndEmptyOverrideFallsBackToLegacyRole() async {
        let o = access(await dash(fake(.override), .override))
        XCTAssertTrue(o.can(Perms.MANAGE_CATALOG))
        XCTAssertFalse(o.can(Perms.MANAGE_ORDERS), "the Sales role's manage_orders is replaced, not merged")
        XCTAssertFalse(o.can(Perms.EXPORT_REPORTS))

        let e = access(await dash(fake(.emptyOverride), .emptyOverride))
        // [] reads as "no custom permissions": the legacy agent set, not the Sales role.
        XCTAssertEqual(e.permissions, Set(Perms.effective(role: "agent", isSuperuser: false, permissions: nil)))
    }

    // ---- Inside the screens: identical for every persona ----

    func testReportsLoadsTheSameForEveryPersonaNoExportGate() async {
        for p in AreaPersona.allCases {
            let f = fake(p)
            let vm = await reports(await dash(f, p))
            XCTAssertEqual(vm.ui.allConvs?.count, 9, "\(p.label): every conversation")
            XCTAssertNil(vm.ui.loadError, p.label)
            XCTAssertEqual(gets(f, "/admin/conversations").map { $0.query }, [nil], p.label)
        }
        // A Reports viewer without export_reports: nothing in the model or
        // screen consults it (the screen shows Export CSV) - the web never does.
        let viewer = await dash(fake(.override), .override)
        XCTAssertFalse(access(viewer).can(Perms.EXPORT_REPORTS))
    }

    func testCatalogIsReadOnlyForEveryPersonaAuditForEveryone() async {
        for p in AreaPersona.allCases {
            let f = fake(p)
            let d = await dash(f, p, catalogFeed: true)
            let vm = await catalog(d)
            _ = await eventually(timeout: 10) { vm.ui.audit != nil }
            XCTAssertNotNil(vm.ui.audit, "\(p.label): the price audit shows for anyone")
            XCTAssertFalse(d.catalog.value.isEmpty, "\(p.label): catalogue loaded")
            vm.refresh()
            await drain()
            _ = await eventually(timeout: 10) { !vm.ui.refreshing }
            XCTAssertTrue(writes(f).filter { $0.path.contains("catalog") }.isEmpty, "\(p.label): nothing is ever written, manage_catalog or not")
        }
    }

    // ---- Persona 8: access changes while the app is open ----

    /// The 180 s agents poll (the dashboard's) carries a role change into the nav.
    func testRoleEditedWhileOpenAgentsPollUpdatesTheNav() async throws {
        let f = fake(.admin)
        let d = await dash(f, .admin)
        XCTAssertTrue(nav(d).contains(.reports))
        // An admin moves this agent to the Sales role.
        AreaPersona.sales.install(f)
        try await d.refreshAgents()
        let items = nav(d)
        XCTAssertFalse(items.contains(.reports))
        XCTAssertFalse(items.contains(.overview))
        XCTAssertFalse(items.contains(.catalog))
        // ...and back again when they are given reports.
        AreaPersona.override.install(f)
        try await d.refreshAgents()
        XCTAssertTrue(self.nav(d).contains(.reports))
        XCTAssertTrue(self.nav(d).contains(.catalog))
    }

    /// A 403 on the report's download: the server's sentence (or the web's
    /// words), and /admin/me + /admin/agents re-read at once so the nav drops
    /// Reports without waiting for the 3-minute poll.
    func testReports403SaysWhyAndRereadsAccess() async throws {
        let f = fake(.admin)
        let d = await dash(f, .admin)
        AreaPersona.sales.install(f)
        f.on("GET", "/admin/conversations", code: 403, body: #"{"detail":"Admin only"}"#)
        let agentsBefore = gets(f, "/admin/agents").count
        let meBefore = gets(f, "/admin/me").count
        let vm = await reports(d)
        await d.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertNil(vm.ui.allConvs)
        XCTAssertEqual(vm.ui.loadError, "Admin only")
        XCTAssertEqual(gets(f, "/admin/agents").count, agentsBefore + 1)
        XCTAssertEqual(gets(f, "/admin/me").count, meBefore + 1)
        XCTAssertEqual(d.accessRereads, 1)
        // The team as that re-read got it: the nav built from it has no Reports.
        let reread = try await d.api.agents.list()
        XCTAssertFalse(nav(d, team: reread).contains(.reports), "the nav corrected itself")
    }

    func testCatalogAudit403StaysHiddenAndRereadsAccess() async {
        let f = fake(.admin)
        let d = await dash(f, .admin)
        f.on("GET", "/admin/catalog/audit", code: 403, body: #"{"detail":"Forbidden"}"#)
        let before = gets(f, "/admin/me").count
        let vm = await catalog(d)
        await d.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertNil(vm.ui.audit)
        XCTAssertEqual(gets(f, "/admin/me").count, before + 1)
        XCTAssertEqual(d.accessRereads, 1)
    }

    /// Only a 403 re-reads access: an outage must not hammer /admin/me and /admin/agents.
    func testOtherFailuresDoNotRereadAccess() async {
        let f = fake(.admin)
        let d = await dash(f, .admin)
        f.on("GET", "/admin/conversations", code: 500, body: #"{"detail":"boom"}"#)
        f.on("GET", "/admin/catalog/audit", code: 503, body: "")
        f.on("GET", "/admin/attribution", code: 500, body: "{}")
        let agents = gets(f, "/admin/agents").count
        let me = gets(f, "/admin/me").count
        _ = await reports(d); _ = await overview(d); _ = await catalog(d)
        await d.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(gets(f, "/admin/agents").count, agents)
        XCTAssertEqual(gets(f, "/admin/me").count, me)
        XCTAssertEqual(d.accessRereads, 0)
    }
}
