package ke.co.bethanyhouse.neema.orders

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.leads.LeadEdit
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.SalesPersona
import ke.co.bethanyhouse.neema.testing.fixtures.SalesPersonaFixtures
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 6's permission matrix for Orders, Deals, Leads and Calls.
 *
 * What the web gates (app/dashboard/page.tsx): only the NAV — Deals and Leads
 * appear with `can(view_leads)`; Calls and Orders for everyone. OrdersView,
 * DealsView, LeadsView and CallsView check no permission at all, and a
 * `?view=deals` link opens Deals without view_leads. The server
 * (routers/admin.py, routers/crm.py) guards every route in this area only by
 * `get_current_agent`, except a recording upload with recording disabled.
 *
 * So for every persona: the nav follows view_leads, and every action in the
 * area is sent (nothing is hidden or blocked client-side). A 403, should the
 * server ever send one, is said in the web's words plus the reason, and makes
 * the app re-read /me and the team list so the nav corrects itself.
 */
class SalesPermissionMatrixTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi() // a layoutlib Context for the container

    private val fake = FakeNeema.withFixtures().also {
        SalesFixtures.install(it)
        CallsFixtures.install(it)
        it.on("POST", CallsFixtures.route(CallsFixtures.C5, "transcribe"), body = """{"ok":true,"status":"pending"}""")
    }
    private val logs = mutableListOf<ToastLog>()

    @After fun tearDown() = logs.forEach { it.close() }

    private fun signIn(p: SalesPersona): Pair<DashboardViewModel, ToastLog> {
        SalesPersonaFixtures.install(fake, p)
        val dash = dashboard(paparazzi.context, fake, role = p.role, superuser = p.superuser)
        val log = ToastLog(dash).also { logs += it }
        return dash to log
    }

    private fun navOf(dash: DashboardViewModel) = dash.navItems().map { it.id }

    /** Whether page.tsx would show Deals + Leads: `can(PERMS.VIEW_LEADS)` over getAgentPermissions. */
    private val SalesPersona.seesLeads get() = when (this) {
        SalesPersona.SalesRole -> false
        else -> true
    }

    // ── Effective permissions (lib/permissions.ts getAgentPermissions) ─────

    @Test fun effectivePermissionsPerPersonaMatchTheWeb() {
        val expected = mapOf(
            SalesPersona.Superuser to Perms.ALL.toSet(),
            SalesPersona.Admin to Perms.ALL.toSet(),
            SalesPersona.LegacyAgent to setOf(
                Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.INTERCEPT_RELEASE, Perms.CLOSE_CONVERSATIONS,
                Perms.TRANSFER_CONVERSATIONS, Perms.ADD_NOTES, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS,
                Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS,
            ),
            SalesPersona.LegacyReadonly to setOf(
                Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS, Perms.VIEW_ANALYTICS,
            ),
            SalesPersona.SalesRole to setOf(Perms.VIEW_CONVERSATIONS, Perms.REPLY_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.MANAGE_ORDERS),
            SalesPersona.Override to setOf(Perms.VIEW_CONVERSATIONS, Perms.VIEW_LEADS),
            // `[]` is not null, so mapAgent keeps it; getAgentPermissions then falls back on the role.
            SalesPersona.EmptyOverride to setOf(
                Perms.VIEW_CONVERSATIONS, Perms.VIEW_ORDERS, Perms.VIEW_CATALOG, Perms.VIEW_CRM, Perms.VIEW_LEADS, Perms.VIEW_ANALYTICS,
            ),
        )
        SalesPersona.entries.forEach { p ->
            val (dash, _) = signIn(p)
            assertEquals("$p", expected.getValue(p), dash.permissions().toSet())
        }
    }

    // ── Nav: the only gate the web has in this area ────────────────────────

    @Test fun ordersAndCallsAreInEveryonesNavDealsAndLeadsFollowViewLeads() {
        SalesPersona.entries.forEach { p ->
            val (dash, _) = signIn(p)
            val nav = navOf(dash)
            assertTrue("$p: Calls", ViewId.Calls in nav)
            assertTrue("$p: Orders", ViewId.Orders in nav)
            assertEquals("$p: Deals", p.seesLeads, ViewId.Deals in nav)
            assertEquals("$p: Leads", p.seesLeads, ViewId.Leads in nav)
            // Deals sits right before Leads, after Orders (and Reports), as desktopNavItems has it.
            if (p.seesLeads) assertEquals(nav.indexOf(ViewId.Deals) + 1, nav.indexOf(ViewId.Leads))
        }
    }

    @Test fun aViewDeepLinkOpensDealsAndLeadsWithoutViewLeadsAsTheWebDoes() {
        val (dash, _) = signIn(SalesPersona.SalesRole)
        assertFalse(dash.can(Perms.VIEW_LEADS))
        dash.applyDeepLink(open = null, ref = null, view = "deals", caller = null)
        assertEquals(ViewId.Deals, dash.view.value)
        // …and the screen's data loads: DealsView renders whatever the server answers.
        val deals = DealsViewModel(dash)
        assertEquals(listOf("d1", "d2", "d3", "d4"), deals.deals.value!!.map { it.id })
        dash.applyDeepLink(open = null, ref = null, view = "leads", caller = null)
        assertEquals(ViewId.Leads, dash.view.value)
    }

    // ── Every action is sent, whoever is signed in ─────────────────────────

    @Test fun everyPersonaCanMoveAnOrdersStatus() {
        SalesPersona.entries.forEach { p ->
            val (dash, log) = signIn(p)
            val vm = OrdersViewModel(dash)
            val before = fake.callsTo("PATCH", "/admin/orders/o2").size
            vm.updateStatus("o2", "confirmed")
            assertEquals("$p", before + 1, fake.callsTo("PATCH", "/admin/orders/o2").size)
            assertEquals("$p", "Order marked as confirmed", log.all.last().message)
        }
    }

    @Test fun everyPersonaCanSendVetoAndSteerDeals() {
        SalesPersona.entries.forEach { p ->
            val (dash, log) = signIn(p)
            val vm = DealsViewModel(dash)
            val approves = fake.callsTo("POST", "/admin/actions/x1/approve").size
            val vetoes = fake.callsTo("POST", "/admin/actions/x2/veto").size
            val patches = fake.callsTo("PATCH", "/admin/deals/d1").size
            vm.act("x1", "approve")
            assertEquals("$p", "Sent ✓", log.all.last().message)
            vm.act("x2", "veto")
            assertEquals("$p", "Vetoed", log.all.last().message)
            vm.markWon("d1")
            assertEquals("$p", "Marked won 🎉", log.all.last().message)
            vm.startGuidance(vm.deals.value!!.first { it.id == "d2" })
            vm.setGuidanceDraft("No discount")
            vm.saveGuidance("d2")
            assertEquals("$p", "Guidance saved — Neema obeys it now", log.all.last().message)
            assertEquals(approves + 1, fake.callsTo("POST", "/admin/actions/x1/approve").size)
            assertEquals(vetoes + 1, fake.callsTo("POST", "/admin/actions/x2/veto").size)
            assertEquals(patches + 1, fake.callsTo("PATCH", "/admin/deals/d1").size)
        }
    }

    @Test fun everyPersonaCanMoveAndEditLeads() {
        SalesPersona.entries.forEach { p ->
            val (dash, log) = signIn(p)
            val vm = LeadsViewModel(dash)
            val lead = vm.leads.value.first { it.id == "u1" }
            val target = vm.stages.value.first { !it.matches(lead.leadStage) }.id
            val before = fake.calls.count { it.method == "PATCH" && it.path.startsWith("/admin/leads/") }
            vm.moveTo(lead, target)
            assertEquals("$p", "Lead updated", log.all.last().message)
            vm.select(lead.id)
            vm.save(lead, LeadEdit(tags = listOf("church"), notesBase = lead.notes.orEmpty()))
            assertNull("$p", vm.sheetError.value)
            assertNull("$p: the sheet closes on save", vm.selectedId.value)
            assertEquals("$p", before + 2, fake.calls.count { it.method == "PATCH" && it.path.startsWith("/admin/leads/") })
        }
    }

    @Test fun everyPersonaGetsTheCallLogAndCanTranscribe() {
        SalesPersona.entries.forEach { p ->
            val (dash, _) = signIn(p)
            val vm = CallsViewModel(dash)
            assertEquals("$p", 7, vm.calls.value!!.size)
            assertNull("$p", vm.loadError.value)
            val before = fake.callsTo("POST", CallsFixtures.path(CallsFixtures.C5, "transcribe")).size
            vm.toggleTranscript(CallsFixtures.C5)
            vm.runTranscribe()
            assertEquals("$p", before + 1, fake.callsTo("POST", CallsFixtures.path(CallsFixtures.C5, "transcribe")).size)
            assertNull("$p", vm.transcript.value!!.err)
        }
    }

    // ── A 403: the web's words, the reason, and a re-read of who we are ────

    private fun rechecks() = fake.callsTo("GET", "/admin/me").size to fake.callsTo("GET", "/admin/agents").size

    @Test fun forbiddenOrderMoveSaysWhyAndRereadsTheAgent() {
        val (dash, log) = signIn(SalesPersona.LegacyReadonly)
        SalesPersonaFixtures.refuseWrites(fake)
        val vm = OrdersViewModel(dash)
        vm.select(dash.orders.value.first { it.id == "o2" })
        val (me, agents) = rechecks()
        vm.updateStatus("o2", "confirmed")
        val t = log.all.last()
        assertEquals(ToastType.Error, t.type)
        assertEquals("Failed to update order — not allowed for your role", t.message)
        assertEquals("o2", vm.selectedId.value) // the sheet stays open
        assertEquals(me + 1, fake.callsTo("GET", "/admin/me").size)
        assertEquals(agents + 1, fake.callsTo("GET", "/admin/agents").size)
    }

    @Test fun forbiddenWithoutADetailFallsBackToFriendlyWords() {
        val (dash, log) = signIn(SalesPersona.LegacyAgent)
        SalesPersonaFixtures.refuseWrites(fake, detail = null)
        OrdersViewModel(dash).updateStatus("o2", "confirmed")
        assertEquals("Failed to update order — your role doesn't allow that", log.all.last().message)
        val deals = DealsViewModel(dash)
        deals.act("x2", "veto")
        assertEquals("Couldn't veto — your role doesn't allow that", log.all.last().message)
        deals.markLost("d1")
        assertEquals("Update failed — your role doesn't allow that", log.all.last().message)
        // Never a bare "veto failed — " with nothing after the dash.
        assertTrue(log.all.none { it.message.trimEnd().endsWith("—") })
    }

    @Test fun forbiddenDealAndLeadWritesSayWhy() {
        val (dash, log) = signIn(SalesPersona.Override)
        SalesPersonaFixtures.refuseWrites(fake)
        val deals = DealsViewModel(dash)
        deals.act("x1", "approve")
        assertEquals("Couldn't send — not allowed for your role", log.all.last().message)
        assertEquals(listOf("x1", "x2"), deals.actions.value!!.map { it.id }) // nothing left the queue

        val leads = LeadsViewModel(dash)
        val lead = leads.leads.value.first { it.id == "u1" }
        val stageBefore = lead.leadStage
        leads.moveTo(lead, leads.stages.value.first { !it.matches(stageBefore) }.id)
        assertEquals("Failed to update lead — not allowed for your role", log.all.last().message)
        assertEquals(stageBefore, leads.leads.value.first { it.id == "u1" }.leadStage) // rolled back

        leads.select(lead.id)
        leads.save(lead, LeadEdit(notes = "x", notesBase = lead.notes.orEmpty()))
        assertEquals("Couldn't save — not allowed for your role", leads.sheetError.value)
        assertEquals(lead.id, leads.selectedId.value)
    }

    // ── Persona 8: the role changes while the app is open ─────────────────

    @Test fun aRoleEditedMidSessionShowsOnTheAgentsPoll() {
        val (dash, _) = signIn(SalesPersona.SalesRole)
        assertFalse(ViewId.Deals in navOf(dash))
        // An admin gives the Sales role view_leads; the 180 s agents poll picks it up.
        SalesPersonaFixtures.install(fake, SalesPersona.Override)
        dash.refetchAgents()
        assertTrue(ViewId.Deals in navOf(dash))
        assertTrue(ViewId.Leads in navOf(dash))
        // …and takes it away again.
        SalesPersonaFixtures.install(fake, SalesPersona.SalesRole)
        dash.refetchAgents()
        assertFalse(ViewId.Deals in navOf(dash))
    }

    @Test fun aRefusalCorrectsTheNavWithoutWaitingForThePoll() {
        val (dash, _) = signIn(SalesPersona.LegacyAgent)
        assertTrue(ViewId.Leads in navOf(dash))
        // Demoted to the Sales role meanwhile; the server now refuses the move.
        SalesPersonaFixtures.install(fake, SalesPersona.SalesRole)
        SalesPersonaFixtures.refuseWrites(fake)
        val leads = LeadsViewModel(dash)
        val lead = leads.leads.value.first { it.id == "u1" }
        leads.moveTo(lead, leads.stages.value.first { !it.matches(lead.leadStage) }.id)
        assertFalse(ViewId.Leads in navOf(dash))
        assertFalse(ViewId.Deals in navOf(dash))
        assertFalse(dash.can(Perms.VIEW_LEADS))
    }

    @Test fun aRefusedCallLogRereadsTheAgentAndSaysSo() {
        val (dash, _) = signIn(SalesPersona.LegacyAgent)
        fake.on("GET", "/admin/calls", code = 403, body = """{"detail":"Forbidden"}""")
        val (me, agents) = rechecks()
        val vm = CallsViewModel(dash)
        assertEquals("You don't have access to calls.", vm.loadError.value)
        assertEquals(me + 1, fake.callsTo("GET", "/admin/me").size)
        assertEquals(agents + 1, fake.callsTo("GET", "/admin/agents").size)
    }

    @Test fun otherFailuresDoNotRereadTheAgent() {
        val (dash, _) = signIn(SalesPersona.LegacyAgent)
        fake.on("PATCH", "/admin/orders/[^/]+", code = 500, body = "{}")
        val (me, agents) = rechecks()
        OrdersViewModel(dash).updateStatus("o2", "confirmed")
        assertEquals(me to agents, rechecks())
    }
}
