import XCTest
@testable import NeemaCore

/// lib/permissions.ts: what an agent may do, resolved the same way as the web.
final class PermsTests: XCTestCase {
    private func agent(role: String, superuser: Bool = false, custom: [String]? = nil, roleOf: [String]? = nil) -> Agent {
        var a = Agent(id: "a1", name: "A", email: "a@b.co", role: role)
        a.isSuperuser = superuser
        a.customPermissions = custom
        a.rolePermissions = roleOf
        return a
    }

    func testSuperuserHasEverything() {
        XCTAssertEqual(Perms.ALL, Perms.of(agent(role: "readonly", superuser: true)))
    }

    func testCustomPermissionsWinOverTheRole() {
        let a = agent(role: "agent", custom: ["view_orders"], roleOf: ["view_catalog"])
        XCTAssertEqual(["view_orders"], Perms.of(a))
        XCTAssertTrue(Perms.has(a, "view_orders"))
        XCTAssertFalse(Perms.has(a, "view_catalog"))
    }

    func testTheRolesPermissionsWhenNoOverride() {
        XCTAssertEqual(["view_catalog"], Perms.of(agent(role: "agent", roleOf: ["view_catalog"])))
    }

    func testAnEmptyOverrideFallsBackToTheLegacyRole() {
        let a = agent(role: "agent", custom: [], roleOf: [])
        XCTAssertEqual(Perms.effective(role: "agent", isSuperuser: false, permissions: nil), Perms.of(a))
        XCTAssertTrue(Perms.hasAll(a, ["view_conversations", "manage_orders", "view_leads"]))
        XCTAssertFalse(Perms.has(a, "manage_agents"))
    }

    func testLegacyRoles() {
        XCTAssertEqual(Perms.ALL, Perms.effective(role: "admin", isSuperuser: false, permissions: nil))
        XCTAssertEqual(["view_conversations", "view_orders", "view_catalog", "view_crm", "view_leads", "view_analytics"],
                       Perms.effective(role: "readonly", isSuperuser: false, permissions: nil))
        XCTAssertEqual([], Perms.effective(role: "visitor", isSuperuser: false, permissions: nil))
        XCTAssertTrue(Perms.hasAny(agent(role: "readonly"), ["manage_agents", "view_analytics"]))
        XCTAssertFalse(Perms.hasAny(agent(role: "visitor"), ["view_orders"]))
    }

    func testTwentyOneKeys() {
        XCTAssertEqual(21, Perms.ALL.count)
        XCTAssertEqual(21, Set(Perms.ALL).count)
    }
}
