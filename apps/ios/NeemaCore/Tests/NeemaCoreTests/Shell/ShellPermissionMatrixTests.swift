import XCTest
@testable import NeemaCore

/// Android `app/PermissionMatrixTest` (round 6's matrix for the shell): for
/// each persona, what lib/permissions.ts resolves, which nav items page.tsx
/// shows, and isAdmin; then a role edited while the app is open, re-derived
/// from the new team row, and a 403's coalesced reread of /admin/me and the
/// team. The 180 s agents poll and the 15 s 403 cooldown are `AppModel`'s.
///
/// The server (apps/api) checks none of these permissions: every /admin route
/// only needs a valid token. The nav is the web's convenience, not a wall.
@MainActor
final class ShellPermissionMatrixTests: XCTestCase {
    private var fake: FakeNeema!
    private var host: TestHost?

    override func setUp() async throws {
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
    }

    override func tearDown() async throws {
        host?.logout()
        host = nil
        AppClock.reset()
    }

    /// Who is signed in: every persona is Moses (`Fixtures.ME_ID`); only his role columns change.
    private enum Persona: CaseIterable {
        case superuser, admin, agent, readonly, sales, override, emptyOverride

        static let SALES = [Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS]
        static let OVERRIDE = [Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_REPORTS, Perms.EXPORT_REPORTS]
        static let AGENT = [
            Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.INTERCEPT_RELEASE, Perms.CLOSE_CONVERSATIONS,
            Perms.TRANSFER_CONVERSATIONS, Perms.ADD_NOTES, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS, Perms.VIEW_CATALOG,
            Perms.VIEW_CRM, Perms.VIEW_LEADS,
        ]
        static let READONLY = [Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS, Perms.VIEW_ANALYTICS]

        var role: String {
            switch self {
            case .superuser, .admin: return "admin"
            case .agent, .sales, .override: return "agent"
            case .readonly, .emptyOverride: return "readonly"
            }
        }
        var superuser: Bool { self == .superuser }
        var customRole: Bool { self == .sales || self == .override || self == .emptyOverride }
        var rolePermissions: [String]? { customRole ? Persona.SALES : nil }
        var customPermissions: [String]? {
            switch self {
            case .override: return Persona.OVERRIDE
            case .emptyOverride: return []
            default: return nil
            }
        }
        /// What lib/permissions.ts `getAgentPermissions` resolves for that row.
        var expected: [String] {
            switch self {
            case .superuser, .admin: return Perms.ALL
            case .agent: return Persona.AGENT
            case .readonly, .emptyOverride: return Persona.READONLY
            case .sales: return Persona.SALES
            case .override: return Persona.OVERRIDE
            }
        }

        private static func json(_ l: [String]?) -> String { l.map { "[" + $0.map { "\"\($0)\"" }.joined(separator: ",") + "]" } ?? "null" }

        /// This persona's row in GET /admin/agents.
        var row: String {
            Fixtures.agentRow(Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", role, true, superuser, 4, 60 * 24 * 200, 1,
                              customRole: customRole ? "sales" : nil, roleName: customRole ? "Sales" : nil, roleColor: customRole ? "#3b82f6" : nil,
                              rolePermissions: Persona.json(rolePermissions), customPermissions: Persona.json(customPermissions))
        }

        /// The whole team list with this persona in Moses's place.
        var agents: String {
            let rows = JSONValue.parse(Fixtures.agents)?.arrayValue ?? []
            let mine = JSONValue.parse(row)!
            return "[" + rows.map { r in r["id"]?.content == Fixtures.ME_ID ? mine.text : r.text }.joined(separator: ",") + "]"
        }

        /// The session a sign-in as this persona gets.
        var session: Session {
            Session(accessToken: "t", refreshToken: "r", agentId: Fixtures.ME_ID, email: "moses@bethanyhouse.co.ke", name: "Moses Mwicigi",
                    role: role, isSuperuser: superuser, mode: "direct")
        }
    }

    /// An admin edits this agent: from now on the server answers the team list as `p`.
    private func become(_ p: Persona) {
        fake.on("GET", "/admin/agents", body: p.agents)
    }

    /// The access of a dashboard signed in as `p` once its team list landed (`AppModel.republishAccess`).
    private func signIn(_ p: Persona) throws -> Access {
        let team = try NeemaJSON.decode([Agent].self, from: p.agents)
        return ShellRules.access(agents: team, me: nil, session: p.session)
    }

    private func ids(_ a: Access) -> [ViewId] {
        ShellRules.navItems(can: { a.can($0) }, humanConvs: 0, pendingOrders: 0).map { $0.view }
    }

    private let all: [ViewId] = [.conversations, .calls, .orders, .reports, .deals, .leads, .overview, .catalog, .agents, .settings, .profile]
    private let readonlyNav: [ViewId] = [.conversations, .calls, .orders, .deals, .leads, .overview, .catalog, .profile]
    private let salesNav: [ViewId] = [.conversations, .calls, .orders, .profile]

    /// persona -> (nav, isAdmin), straight from page.tsx's baseNavItems/desktopNavItems and isAdmin.
    private var matrix: [Persona: ([ViewId], Bool)] {
        [
            .superuser: (all, true),
            .admin: (all, true),
            .agent: ([.conversations, .calls, .orders, .deals, .leads, .catalog, .profile], false),
            .readonly: (readonlyNav, false),
            .sales: (salesNav, false),
            .override: ([.conversations, .calls, .orders, .reports, .profile], false),
            .emptyOverride: (readonlyNav, false),
        ]
    }

    func testEveryPersonaResolvesAsTheWebDoes() async throws {
        for p in Persona.allCases {
            let access = try signIn(p)
            XCTAssertEqual(Set(p.expected), access.permissions, "\(p) permissions")
            for perm in Perms.ALL { XCTAssertEqual(p.expected.contains(perm), access.can(perm), "\(p) can(\(perm))") }
            let (nav, admin) = matrix[p]!
            XCTAssertEqual(nav, ids(access), "\(p) nav")
            XCTAssertEqual(admin, access.isAdmin, "\(p) isAdmin")
        }
    }

    func testAnEmptyOverrideFallsBackToTheLegacyRoleNotTheCustomRole() async throws {
        let access = try signIn(.emptyOverride)
        // Sales grants reply_conversations / manage_orders; readonly does not.
        XCTAssertFalse(access.can(Perms.REPLY_CONVERSATIONS))
        XCTAssertFalse(access.can(Perms.MANAGE_ORDERS))
        XCTAssertTrue(access.can(Perms.VIEW_ANALYTICS))
    }

    func testSettingsIsInTheNavOnlyWithManageSettingsButOpensForAnyone() async throws {
        let access = try signIn(.readonly)
        XCTAssertFalse(ids(access).contains(.settings))
        // The web renders SettingsView for anyone who reaches it (the account
        // menu, ?view=settings); the server decides what they may change.
        var nav = NavHistory()
        XCTAssertEqual(.navigate(.settings), DeepLink(view: "settings").action)
        nav.navigate(.settings)
        XCTAssertEqual(.settings, nav.view)
        nav.navigate(.agents)
        XCTAssertEqual(.agents, nav.view, "no view is refused by the shell")
    }

    func testTheSessionRoleAloneMakesAnAdminButGrantsNoPermissions() async {
        // page.tsx: isAdmin checks session.user.role before any team row exists; can() does not.
        let s = Session(accessToken: "t", refreshToken: nil, agentId: Fixtures.ME_ID, email: "moses@bethanyhouse.co.ke", name: "",
                        role: "admin", isSuperuser: false, mode: "direct")
        let access = ShellRules.access(agents: [], me: nil, session: s)
        XCTAssertTrue(access.isAdmin)
        XCTAssertFalse(access.can(Perms.VIEW_REPORTS))
        XCTAssertEqual(salesNav, ids(access))
    }

    func testASessionSuperuserFlagIsNotEnoughWithoutTheTeamRow() async {
        // page.tsx reads is_superuser from the team row only.
        let s = Session(accessToken: "t", refreshToken: nil, agentId: Fixtures.ME_ID, email: "moses@bethanyhouse.co.ke", name: "",
                        role: "agent", isSuperuser: true, mode: "direct")
        XCTAssertFalse(ShellRules.access(agents: [], me: nil, session: s).isAdmin)
    }

    // -- Persona 8: an admin edits this agent while the app is open --------------

    func testARoleChangeArrivesWithTheNext180sAgentsPoll() async throws {
        // The 180 s poll is AppModel's; what it re-derives from the new team row is the rule here.
        let before = try signIn(.superuser)
        XCTAssertEqual(all, ids(before))

        let demoted = try NeemaJSON.decode([Agent].self, from: Persona.sales.agents)
        let after = ShellRules.access(agents: demoted, me: nil, session: Persona.superuser.session)
        XCTAssertEqual(salesNav, ids(after))
        XCTAssertFalse(after.can(Perms.MANAGE_AGENTS))
        XCTAssertEqual(Set(Persona.SALES), after.permissions)
        // page.tsx's isAdmin also trusts the session's role, which only a new
        // sign-in changes: signed in as admin, the web keeps isAdmin true too.
        XCTAssertTrue(after.isAdmin)

        // ...and back again when the admin restores it.
        let restored = try NeemaJSON.decode([Agent].self, from: Persona.admin.agents)
        let again = ShellRules.access(agents: restored, me: nil, session: Persona.superuser.session)
        XCTAssertEqual(all, ids(again))
        XCTAssertTrue(again.isAdmin)
    }

    func testADemotionDropsIsAdminForAnAgentWhoSignedInWithoutTheAdminRole() async throws {
        // Signed in as a legacy agent who was then given manage_agents by override.
        let promoted = try NeemaJSON.decode([Agent].self, from: Persona.agent.agents.replacingOccurrences(of: "\"custom_permissions\":null", with: "\"custom_permissions\":[\"manage_agents\"]"))
        XCTAssertEqual(["manage_agents"], promoted.first { $0.id == Fixtures.ME_ID }?.customPermissions)
        let before = ShellRules.access(agents: promoted, me: nil, session: Persona.agent.session)
        XCTAssertTrue(before.isAdmin)
        let demoted = try NeemaJSON.decode([Agent].self, from: Persona.agent.agents)
        let after = ShellRules.access(agents: demoted, me: nil, session: Persona.agent.session)
        XCTAssertFalse(after.isAdmin)
        XCTAssertFalse(ids(after).contains(.agents))
    }

    private func fire(_ h: TestHost, _ path: String) {
        Task {
            do {
                _ = try await h.http.raw("POST", path)
                XCTFail("expected a 403")
            } catch let e as ApiError {
                XCTAssertEqual(403, e.status)
            } catch {
                XCTFail("expected ApiError, got \(error)")
            }
        }
    }

    func testA403RereadsMeAndTheTeamOnceForABurst() async throws {
        become(.override)
        let h = TestHost(fake: fake, role: "agent", superuser: false)
        host = h
        try await h.refreshAgents()
        let access = ShellRules.access(agents: h.agents.value, me: nil, session: h.session.value)
        XCTAssertTrue(ids(access).contains(.reports))
        func agents() -> Int { fake.callsTo("GET", "/admin/agents").count }
        func me() -> Int { fake.callsTo("GET", "/admin/me").count }
        let (a0, m0) = (agents(), me())

        // The admin took Reports away; the agent's next export is refused.
        become(.sales)
        fake.on("POST", "/admin/reports/export", code: 403, body: #"{"detail":"Not allowed"}"#)
        for _ in 0..<3 { fire(h, "/admin/reports/export") }
        let refused = await eventually { self.fake.callsTo("POST", "/admin/reports/export").count == 3 }
        XCTAssertTrue(refused)
        await drain()
        XCTAssertEqual(a0, agents(), "coalesced, not yet")
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS)
        let reread = await eventually { h.accessRereads == 1 && agents() == a0 + 1 && me() == m0 + 1 }
        XCTAssertTrue(reread)
        XCTAssertEqual(a0 + 1, agents(), "one reread of the team for three 403s")
        XCTAssertEqual(m0 + 1, me(), "and of /admin/me")
        // AppModel paints the reread rows; the rule over them:
        try await h.refreshAgents()
        let after = ShellRules.access(agents: h.agents.value, me: nil, session: h.session.value)
        XCTAssertEqual(salesNav, ids(after))
        XCTAssertEqual(Set(Persona.SALES), after.permissions)
    }

    func testA403OnTheTeamListItselfDoesNotLoop() async throws {
        become(.sales)
        let h = TestHost(fake: fake, role: "agent", superuser: false)
        host = h
        try await h.refreshAgents()
        fake.on("GET", "/admin/agents", code: 403, body: "{}")
        _ = await expectApi { try await h.refreshAgents() }
        let n = fake.callsTo("GET", "/admin/agents").count
        await h.clock.advance(by: 10_000)
        await drain()
        XCTAssertEqual(n, fake.callsTo("GET", "/admin/agents").count)
        XCTAssertEqual(0, h.accessRereads, "an identity read's 403 is not a feature's refusal")
        // The last good row still decides.
        let access = ShellRules.access(agents: h.agents.value, me: nil, session: h.session.value)
        XCTAssertEqual(Set(Persona.SALES), access.permissions)
    }
}
