import Foundation
import XCTest
@testable import NeemaCore

/// The rows of Android `SalesPermissionMatrixTest` that `SalesPermissionMatrixTests`
/// leaves out: a `?view=` link opening Deals / Leads without view_leads, the
/// call log and transcription for every persona, and a refusal correcting
/// who this agent is without waiting for the team-list poll.
final class SalesPermissionExtraTests: OrdersTestCase {
    private let C5 = CallsFixtures.C5

    private func signIn(_ p: SalesPersona) async -> TestHost {
        SalesPersonaFixtures.install(fake, p)
        return await signedIn(role: p.role, superuser: p.superuser)
    }

    /// The nav as page.tsx builds it over `team` for the signed-in agent.
    private func navOf(_ team: [Agent], _ h: TestHost) -> [ViewId] {
        let access = ShellRules.access(agents: team, me: nil, session: h.session.value)
        return ShellRules.navItems(can: { access.can($0) }, humanConvs: 0, pendingOrders: 0).map { $0.view }
    }

    private func rechecks() -> (Int, Int) { (fake.callsTo("GET", "/admin/me").count, fake.callsTo("GET", "/admin/agents").count) }

    // ---- A ?view= link opens the screen whatever the nav shows ----

    func testAViewDeepLinkOpensDealsAndLeadsWithoutViewLeadsAsTheWebDoes() async {
        let h = await signIn(.salesRole)
        let access = ShellRules.access(agents: [SalesPersona.salesRole.agent], me: nil, session: h.session.value)
        XCTAssertFalse(access.can(Perms.VIEW_LEADS))
        XCTAssertEqual(DeepLink(view: "deals").action, .navigate(.deals))
        // ...and the screen's data loads: DealsView renders whatever the server answers.
        let deals = DealsViewModel(host: h, sleep: h.clock.sleeper)
        await drain()
        _ = await eventually(timeout: 10) { deals.ui.deals != nil }
        XCTAssertEqual(deals.ui.deals?.map { $0.id }, ["d1", "d2", "d3", "d4"])
        deals.close()
        XCTAssertEqual(DeepLink(view: "leads").action, .navigate(.leads))
    }

    // ---- Every persona gets the call log and can transcribe ----

    func testEveryPersonaGetsTheCallLogAndCanTranscribe() async {
        CallsFixtures.install(fake)
        fake.on("POST", CallsFixtures.route(C5, "transcribe"), body: #"{"ok":true,"status":"pending"}"#)
        for p in SalesPersona.allCases {
            let h = await signIn(p)
            let vm = CallsViewModel(host: h, sleep: h.clock.sleeper)
            _ = await eventually(timeout: 5) { vm.calls.value != nil && !vm.busy }
            XCTAssertEqual(vm.calls.value?.count, 7, "\(p)")
            XCTAssertNil(vm.loadError.value, "\(p)")
            let before = fake.callsTo("POST", CallsFixtures.path(C5, "transcribe")).count
            vm.toggleTranscript(C5)
            _ = await eventually { vm.transcript.value?.data != nil || vm.transcript.value?.loadErr != nil }
            vm.runTranscribe()
            await drain()
            _ = await eventually { vm.transcript.value?.busy == false }
            XCTAssertEqual(fake.callsTo("POST", CallsFixtures.path(C5, "transcribe")).count, before + 1, "\(p)")
            XCTAssertNil(vm.transcript.value?.err, "\(p)")
            vm.close()
        }
    }

    // ---- Persona 8: the role changes while the app is open ----

    /// Demoted to the Sales role meanwhile; the server now refuses the move,
    /// and the refusal re-reads the team at once: the list it gets back no
    /// longer carries view_leads, so the nav drops Deals and Leads.
    func testARefusalCorrectsTheNavWithoutWaitingForThePoll() async throws {
        let h = await signIn(.legacyAgent)
        let before = try await h.api.agents.list()
        XCTAssertTrue(navOf(before, h).contains(.leads))
        SalesPersonaFixtures.install(fake, .salesRole)
        SalesPersonaFixtures.refuseWrites(fake)
        let leads = LeadsViewModel(host: h, sleep: h.clock.sleeper)
        await drain()
        _ = await eventually(timeout: 10) { !leads.ui.loading }
        let lead = leads.ui.leads.first { $0.id == "u1" }!
        let (me, agents) = rechecks()
        leads.moveTo(lead, leads.ui.stages.first { !$0.matches(lead.leadStage) }!.id)
        await drain()
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(h.accessRereads, 1)
        XCTAssertEqual(fake.callsTo("GET", "/admin/me").count, me + 1)
        XCTAssertEqual(fake.callsTo("GET", "/admin/agents").count, agents + 1)
        // What that re-read answered: the nav built from it has neither screen.
        let team = try await h.api.agents.list()
        let nav = navOf(team, h)
        XCTAssertFalse(nav.contains(.leads))
        XCTAssertFalse(nav.contains(.deals))
        XCTAssertFalse(ShellRules.access(agents: team, me: nil, session: h.session.value).can(Perms.VIEW_LEADS))
        leads.close()
    }

    func testARefusedCallLogRereadsTheAgentAndSaysSo() async {
        let h = await signIn(.legacyAgent)
        fake.on("GET", "/admin/calls", code: 403, body: #"{"detail":"Forbidden"}"#)
        let (me, agents) = rechecks()
        let vm = CallsViewModel(host: h, sleep: h.clock.sleeper)
        _ = await eventually(timeout: 5) { vm.loadError.value != nil }
        XCTAssertEqual(vm.loadError.value, "You don't have access to calls.")
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(fake.callsTo("GET", "/admin/me").count, me + 1)
        XCTAssertEqual(fake.callsTo("GET", "/admin/agents").count, agents + 1)
        vm.close()
    }
}
