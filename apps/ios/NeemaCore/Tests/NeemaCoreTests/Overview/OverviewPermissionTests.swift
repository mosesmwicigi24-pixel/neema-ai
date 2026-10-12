import Foundation
import XCTest
@testable import NeemaCore

/// The permission matrix for Analytics (the overview rows of Android
/// `AreaPermissionMatrixTest`): page.tsx gates only the nav entry (behind
/// view_analytics); inside OverviewView there is no `can()`, no role and no
/// isAdmin check — every section shows for anyone who reaches the view, and
/// the server's /admin/stats, /admin/attribution and /admin/conversations
/// depend only on `get_current_agent`.
final class OverviewPermissionTests: OverviewTestCase {
    private func signIn(_ p: SalesPersona) -> TestHost {
        fake = Fixtures.withFixtures()
        ReportsFixtures.install(fake)
        SalesPersonaFixtures.install(fake, p)
        let h = TestHost(fake: fake, role: p.role, superuser: p.superuser)
        hosts.append(h)
        return h
    }

    func testEverySectionLoadsForEveryPersona() async {
        for p in SalesPersona.allCases {
            let h = signIn(p)
            let vm = await vm(h)
            XCTAssertNotNil(vm.ui.stats, "\(p): stats")
            XCTAssertNil(vm.ui.statsError, "\(p)")
            XCTAssertNotNil(vm.ui.attrib, "\(p): attribution (no role check on the web or server)")
            XCTAssertNotNil(vm.ui.humanRows, "\(p): human intercepts")
            XCTAssertEqual(reads("/admin/stats"), 1, "\(p)")
            XCTAssertEqual(reads("/admin/attribution"), 1, "\(p)")
        }
    }

    /// A 403 on the attribution panel stays quiet, as on the web, but makes the
    /// app re-read /admin/me and the team list at once so the nav corrects itself.
    func testAForbiddenAttributionStaysQuietButRereadsAccess() async {
        let h = signIn(.admin)
        fake.on("GET", "/admin/attribution", code: 403, body: #"{"detail":"Admin only"}"#)
        let agentsBefore = reads("/admin/agents")
        let vm = await vm(h)
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertNil(vm.ui.attrib, "attribution stays hidden, as on the web")
        XCTAssertNotNil(vm.ui.stats)
        XCTAssertEqual(reads("/admin/agents"), agentsBefore + 1)
        XCTAssertEqual(h.accessRereads, 1)
        XCTAssertTrue(errors.isEmpty, "nothing is said for it")
    }

    func testForbiddenStatsEstimateAndSayWhy() async {
        let h = signIn(.admin)
        fake.on("GET", "/admin/stats", code: 403, body: #"{"detail":"Not authenticated"}"#)
        let vm = await vm(h)
        XCTAssertNil(vm.ui.stats)
        XCTAssertEqual(vm.ui.statsError, "You don't have permission to do that.")
        XCTAssertEqual(vm.ui.fallbackConvs.count, 9, "the cards show the phone's own estimate")
    }

    /// Only a 403 re-reads access: an outage must not hammer /admin/me and /admin/agents.
    func testOtherFailuresDoNotRereadAccess() async {
        let h = signIn(.admin)
        fake.on("GET", "/admin/stats", code: 500, body: #"{"detail":"boom"}"#)
        fake.on("GET", "/admin/attribution", code: 500, body: "{}")
        let me = reads("/admin/me"), agents = reads("/admin/agents")
        _ = await vm(h)
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(reads("/admin/me"), me)
        XCTAssertEqual(reads("/admin/agents"), agents)
        XCTAssertEqual(h.accessRereads, 0)
    }
}
