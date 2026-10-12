import Foundation
import XCTest
@testable import NeemaCore

/// The permission matrix for Orders, Deals and Leads (Android
/// `SalesPermissionMatrixTest`; its Calls rows arrive with that screen).
///
/// What the web gates (app/dashboard/page.tsx): only the NAV — Deals and
/// Leads appear with `can(view_leads)`; Calls and Orders for everyone.
/// OrdersView checks no permission at all. The server (routers/admin.py)
/// guards every route in this area only by `get_current_agent`.
///
/// So for every persona: the nav follows view_leads, and every action in the
/// area is sent (nothing is hidden or blocked client-side). A 403, should the
/// server ever send one, is said in the web's words plus the reason, and makes
/// the app re-read /me and the team list so the nav corrects itself.
final class SalesPermissionMatrixTests: OrdersTestCase {
    private func signIn(_ p: SalesPersona) async -> TestHost {
        SalesPersonaFixtures.install(fake, p)
        return await signedIn(role: p.role, superuser: p.superuser)
    }

    /// The nav as page.tsx builds it for the persona's own team row.
    private func navOf(_ p: SalesPersona) -> [ViewId] {
        let access = ShellRules.access(agents: [p.agent], me: p.agent, session: nil)
        return ShellRules.navItems(can: { access.can($0) }, humanConvs: 0, pendingOrders: 0).map { $0.view }
    }

    /// Whether page.tsx would show Deals + Leads: `can(PERMS.VIEW_LEADS)` over getAgentPermissions.
    private func seesLeads(_ p: SalesPersona) -> Bool { p != .salesRole }

    // ── Effective permissions (lib/permissions.ts getAgentPermissions) ─────

    func testEffectivePermissionsPerPersonaMatchTheWeb() {
        let expected: [SalesPersona: Set<String>] = [
            .superuser: Set(Perms.ALL),
            .admin: Set(Perms.ALL),
            .legacyAgent: [
                Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.INTERCEPT_RELEASE, Perms.CLOSE_CONVERSATIONS,
                Perms.TRANSFER_CONVERSATIONS, Perms.ADD_NOTES, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS,
                Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS,
            ],
            .legacyReadonly: [Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS, Perms.VIEW_ANALYTICS],
            .salesRole: [Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS],
            .override: [Perms.VIEW_CONVERSATIONS, Perms.VIEW_LEADS],
            // `[]` is not null, so mapAgent keeps it; getAgentPermissions then falls back on the role.
            .emptyOverride: [Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS, Perms.VIEW_ANALYTICS],
        ]
        for p in SalesPersona.allCases {
            XCTAssertEqual(Set(Perms.of(p.agent)), expected[p]!, "\(p)")
        }
    }

    // ── Nav: the only gate the web has in this area ────────────────────────

    func testOrdersAndCallsAreInEveryonesNavDealsAndLeadsFollowViewLeads() {
        for p in SalesPersona.allCases {
            let nav = navOf(p)
            XCTAssertTrue(nav.contains(.calls), "\(p): Calls")
            XCTAssertTrue(nav.contains(.orders), "\(p): Orders")
            XCTAssertEqual(nav.contains(.deals), seesLeads(p), "\(p): Deals")
            XCTAssertEqual(nav.contains(.leads), seesLeads(p), "\(p): Leads")
            // Deals sits right before Leads, after Orders (and Reports), as desktopNavItems has it.
            if seesLeads(p) { XCTAssertEqual(nav.firstIndex(of: .deals)! + 1, nav.firstIndex(of: .leads)!) }
        }
    }

    // ── Every action is sent, whoever is signed in ─────────────────────────

    func testEveryPersonaCanMoveAnOrdersStatus() async {
        for p in SalesPersona.allCases {
            SalesFixtures.install(fake)
            let h = await signIn(p)
            let vm = await vm(h)
            let before = fake.callsTo("PATCH", "/admin/orders/o2").count
            vm.updateStatus(id: "o2", status: "confirmed")
            await drain()
            XCTAssertEqual(fake.callsTo("PATCH", "/admin/orders/o2").count, before + 1, "\(p)")
            XCTAssertEqual(h.toasts.last?.message, "Order marked as confirmed", "\(p)")
        }
    }

    func testEveryPersonaCanSendVetoAndSteerDeals() async {
        for p in SalesPersona.allCases {
            SalesFixtures.install(fake)
            let h = await signIn(p)
            let vm = DealsViewModel(host: h, sleep: h.clock.sleeper)
            await drain()
            let approves = fake.callsTo("POST", "/admin/actions/x1/approve").count
            let vetoes = fake.callsTo("POST", "/admin/actions/x2/veto").count
            let patches = fake.callsTo("PATCH", "/admin/deals/d1").count
            vm.act("x1", "approve"); await drain()
            XCTAssertEqual(h.toasts.last?.message, "Sent ✓", "\(p)")
            vm.act("x2", "veto"); await drain()
            XCTAssertEqual(h.toasts.last?.message, "Vetoed", "\(p)")
            vm.markWon("d1"); await drain()
            XCTAssertEqual(h.toasts.last?.message, "Marked won 🎉", "\(p)")
            let d2 = vm.ui.deals?.first { $0.id == "d2" }
            XCTAssertNotNil(d2, "\(p)")
            if let d = d2 {
                vm.startGuidance(d)
                vm.setGuidanceDraft("No discount")
                vm.saveGuidance("d2"); await drain()
                XCTAssertEqual(h.toasts.last?.message, "Guidance saved — Neema obeys it now", "\(p)")
            }
            XCTAssertEqual(fake.callsTo("POST", "/admin/actions/x1/approve").count, approves + 1, "\(p)")
            XCTAssertEqual(fake.callsTo("POST", "/admin/actions/x2/veto").count, vetoes + 1, "\(p)")
            XCTAssertEqual(fake.callsTo("PATCH", "/admin/deals/d1").count, patches + 1, "\(p)")
            vm.close()
        }
    }

    private func leadPatches() -> Int { fake.calls.filter { $0.method == "PATCH" && $0.path.hasPrefix("/admin/leads/") }.count }

    func testEveryPersonaCanMoveAndEditLeads() async {
        for p in SalesPersona.allCases {
            SalesFixtures.install(fake)
            let h = await signIn(p)
            let vm = LeadsViewModel(host: h, sleep: h.clock.sleeper)
            await drain()
            _ = await eventually(timeout: 10) { !vm.ui.loading }
            guard let lead = vm.ui.leads.first(where: { $0.id == "u1" }) else { XCTFail("\(p): u1 not loaded"); vm.close(); continue }
            let target = vm.ui.stages.first { !$0.matches(lead.leadStage) }!.id
            let before = leadPatches()
            vm.moveTo(lead, target); await drain()
            XCTAssertEqual(h.toasts.last?.message, "Lead updated", "\(p)")
            vm.select(lead.id)
            vm.save(lead, LeadEdit(tags: ["church"], notesBase: lead.notes ?? "")); await drain()
            XCTAssertNil(vm.ui.sheetError, "\(p)")
            XCTAssertNil(vm.ui.selectedId, "\(p): the sheet closes on save")
            XCTAssertEqual(leadPatches(), before + 2, "\(p)")
            vm.close()
        }
    }

    // ── A 403: the web's words, the reason, and a re-read of who we are ────

    private func rechecks() -> (Int, Int) { (fake.callsTo("GET", "/admin/me").count, fake.callsTo("GET", "/admin/agents").count) }

    func testForbiddenOrderMoveSaysWhyAndRereadsTheAgent() async {
        let h = await signIn(.legacyReadonly)
        SalesPersonaFixtures.refuseWrites(fake)
        let vm = await vm(h)
        vm.select(h.orders.value.first { $0.id == "o2" })
        let (me, agents) = rechecks()
        vm.updateStatus(id: "o2", status: "confirmed")
        await drain()
        let t = h.toasts.last
        XCTAssertEqual(t?.type, .error)
        XCTAssertEqual(t?.message, "Failed to update order — not allowed for your role")
        XCTAssertEqual(vm.ui.selectedId, "o2") // the sheet stays open
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(fake.callsTo("GET", "/admin/me").count, me + 1)
        XCTAssertEqual(fake.callsTo("GET", "/admin/agents").count, agents + 1)
        XCTAssertEqual(h.accessRereads, 1)
    }

    func testForbiddenWithoutADetailFallsBackToFriendlyWords() async {
        let h = await signIn(.legacyAgent)
        SalesPersonaFixtures.refuseWrites(fake, detail: nil)
        let vm = await vm(h)
        vm.updateStatus(id: "o2", status: "confirmed")
        await drain()
        XCTAssertEqual(h.toasts.last?.message, "Failed to update order — your role doesn't allow that")
        let deals = DealsViewModel(host: h, sleep: h.clock.sleeper)
        await drain()
        deals.act("x2", "veto"); await drain()
        XCTAssertEqual(h.toasts.last?.message, "Couldn't veto — your role doesn't allow that")
        deals.markLost("d1"); await drain()
        XCTAssertEqual(h.toasts.last?.message, "Update failed — your role doesn't allow that")
        deals.close()
        // Never a bare "failed — " with nothing after the dash.
        XCTAssertFalse(h.toasts.contains { $0.message.trimmingCharacters(in: .whitespaces).hasSuffix("—") })
    }

    func testForbiddenDealAndLeadWritesSayWhy() async {
        let h = await signIn(.override)
        SalesPersonaFixtures.refuseWrites(fake)
        let deals = DealsViewModel(host: h, sleep: h.clock.sleeper)
        await drain()
        deals.act("x1", "approve"); await drain()
        XCTAssertEqual(h.toasts.last?.message, "Couldn't send — not allowed for your role")
        XCTAssertEqual(deals.ui.actions?.map { $0.id }, ["x1", "x2"]) // nothing left the queue

        let leads = LeadsViewModel(host: h, sleep: h.clock.sleeper)
        await drain()
        _ = await eventually(timeout: 10) { !leads.ui.loading }
        let lead = leads.ui.leads.first { $0.id == "u1" }!
        let stageBefore = lead.leadStage
        leads.moveTo(lead, leads.ui.stages.first { !$0.matches(stageBefore) }!.id); await drain()
        XCTAssertEqual(h.toasts.last?.message, "Failed to update lead — not allowed for your role")
        XCTAssertEqual(leads.ui.leads.first { $0.id == "u1" }?.leadStage, stageBefore) // rolled back

        leads.select(lead.id)
        leads.save(lead, LeadEdit(notes: "x", notesBase: lead.notes ?? "")); await drain()
        XCTAssertEqual(leads.ui.sheetError, "Couldn't save — not allowed for your role")
        XCTAssertEqual(leads.ui.selectedId, lead.id)
        deals.close(); leads.close()
    }

    /// A burst of refusals (several screens' parallel loads) costs one re-read.
    func testABurstOfRefusalsRereadsOnce() async {
        let h = await signIn(.legacyAgent)
        SalesPersonaFixtures.refuseWrites(fake)
        let vm = await vm(h)
        for id in ["o1", "o2", "o3"] {
            vm.updateStatus(id: id, status: "confirmed")
            await drain()
        }
        XCTAssertEqual(fake.calls.filter { $0.method == "PATCH" }.count, 3)
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(h.accessRereads, 1)
    }

    // ── Persona 8: the role changes while the app is open ─────────────────

    /// An admin gives the Sales role view_leads; the team-list poll (or a refusal's re-read) picks it up.
    func testARoleEditedMidSessionShowsOnTheAgentsPoll() {
        XCTAssertFalse(navOf(.salesRole).contains(.deals))
        XCTAssertTrue(navOf(.override).contains(.deals))
        XCTAssertTrue(navOf(.override).contains(.leads))
        XCTAssertFalse(navOf(.salesRole).contains(.leads))
    }

    func testOtherFailuresDoNotRereadTheAgent() async {
        let h = await signIn(.legacyAgent)
        fake.on("PATCH", "/admin/orders/[^/]+", code: 500, body: "{}")
        let before = rechecks()
        let vm = await vm(h)
        vm.updateStatus(id: "o2", status: "confirmed")
        await drain()
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(rechecks().0, before.0)
        XCTAssertEqual(rechecks().1, before.1)
        XCTAssertEqual(h.accessRereads, 0)
    }
}
