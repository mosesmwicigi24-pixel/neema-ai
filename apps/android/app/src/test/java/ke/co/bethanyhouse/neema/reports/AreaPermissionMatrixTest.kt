package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.AreaPersonaFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.AreaPersonaFixtures.Persona
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 6 — the permission matrix for Reports, Analytics (overview) and
 * Catalog.
 *
 * What the web gates here: only the NAV ENTRIES (page.tsx: Reports behind
 * view_reports, Analytics behind view_analytics, Catalog behind
 * view_catalog). Inside ReportsView, OverviewView and CatalogView there is no
 * `can()`, no role and no isAdmin check at all: every section, every stat,
 * Export CSV (never checks export_reports) and the price-audit banner show
 * for anyone who reaches the view, and the catalogue is read-only for
 * everyone (manage_catalog unlocks nothing — the hub is the source of truth).
 *
 * What the server allows: GET /admin/conversations, /admin/stats,
 * /admin/attribution, /admin/catalog and /admin/catalog/audit depend only on
 * `get_current_agent` — any signed-in agent may read them, whatever the role.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AreaPermissionMatrixTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = kotlinx.coroutines.test.TestCoroutineScheduler()
    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher(scheduler))
    /** Core batches a burst of 403s into one access re-read after a short window. */
    private fun settle() { scheduler.advanceTimeBy(1_000); scheduler.runCurrent() }
    @After fun tearDown() = Dispatchers.resetMain()

    private fun fake(p: Persona) = FakeNeema.withFixtures().also {
        ReportsFixtures.install(it)
        AreaPersonaFixtures.install(it, p)
    }

    private fun dash(f: FakeNeema, p: Persona): DashboardViewModel =
        dashboard(paparazzi.context, f, role = p.role, superuser = p.superuser)

    private fun FakeNeema.gets(path: String) = calls.filter { it.method == "GET" && it.path == path }
    private fun FakeNeema.writes() = calls.filter { it.method != "GET" && it.path.startsWith("/admin/") }
    private fun DashboardViewModel.nav() = navItems().map { it.id }

    // ── The nav: exactly page.tsx's three tests, per persona ────────────────

    @Test fun nav_matchesPageTsx_forEveryPersona() {
        for (p in Persona.entries) {
            val d = dash(fake(p), p)
            val nav = d.nav()
            assertEquals("${p.label}: Reports", p.reports, ViewId.Reports in nav)
            assertEquals("${p.label}: Analytics", p.analytics, ViewId.Overview in nav)
            assertEquals("${p.label}: Catalog", p.catalog, ViewId.Catalog in nav)
            assertEquals("${p.label}: view_reports", p.reports, d.can(Perms.VIEW_REPORTS))
        }
    }

    @Test fun override_winsOverRole_andEmptyOverrideFallsBackToLegacyRole() {
        val o = dash(fake(Persona.Override), Persona.Override)
        assertTrue(o.can(Perms.MANAGE_CATALOG))
        assertFalse("the Sales role's manage_orders is replaced, not merged", o.can(Perms.MANAGE_ORDERS))
        assertFalse(o.can(Perms.EXPORT_REPORTS))

        val e = dash(fake(Persona.EmptyOverride), Persona.EmptyOverride)
        // [] reads as "no custom permissions": the legacy agent set, not the Sales role.
        assertEquals(Perms.effective("agent", false, null).toSet(), e.permissions().toSet())
    }

    // ── Inside the screens: identical for every persona ─────────────────────

    @Test fun reports_loadsTheSameForEveryPersona_noExportGate() {
        for (p in Persona.entries) {
            val f = fake(p)
            val vm = ReportsViewModel(dash(f, p))
            assertEquals("${p.label}: every conversation", 9, vm.allConvs.value?.size)
            assertNull(p.label, vm.loadError.value)
            assertEquals(p.label, listOf<String?>(null), f.gets("/admin/conversations").map { it.query })
        }
        // A Reports viewer without export_reports: nothing in the ViewModel or
        // screen consults it (the screenshot shows Export CSV) — the web never does.
        assertFalse(dash(fake(Persona.Override), Persona.Override).can(Perms.EXPORT_REPORTS))
    }

    @Test fun overview_loadsEverySectionForEveryPersona() {
        for (p in Persona.entries) {
            val f = fake(p)
            val vm = OverviewViewModel(dash(f, p))
            assertNotNull("${p.label}: stats", vm.stats.value)
            assertNull(p.label, vm.statsError.value)
            assertNotNull("${p.label}: attribution (no role check on the web or server)", vm.attrib.value)
            assertNotNull("${p.label}: human intercepts", vm.humanRows.value)
            assertEquals(1, f.gets("/admin/stats").size)
            assertEquals(1, f.gets("/admin/attribution").size)
        }
    }

    @Test fun catalog_isReadOnlyForEveryPersona_auditForEveryone() {
        for (p in Persona.entries) {
            val f = fake(p)
            val d = dash(f, p)
            val vm = CatalogViewModel(d)
            assertNotNull("${p.label}: the price audit shows for anyone", vm.audit.value)
            assertTrue("${p.label}: catalogue loaded", d.catalog.value.isNotEmpty())
            vm.refresh()
            assertEquals("${p.label}: nothing is ever written, manage_catalog or not", emptyList<Any>(), f.writes().filter { "catalog" in it.path })
        }
    }

    // ── Persona 8: access changes while the app is open ─────────────────────

    /** The 180 s agents poll (DashboardViewModel's usePolling) carries a role change into the nav. */
    @Test fun roleEditedWhileOpen_agentsPollUpdatesTheNav() {
        val f = fake(Persona.Admin)
        val d = dash(f, Persona.Admin)
        assertTrue(ViewId.Reports in d.nav())
        // An admin moves this agent to the Sales role.
        AreaPersonaFixtures.install(f, Persona.Sales)
        kotlinx.coroutines.runBlocking { d.refreshAgents() }
        val nav = d.nav()
        assertFalse(ViewId.Reports in nav)
        assertFalse(ViewId.Overview in nav)
        assertFalse(ViewId.Catalog in nav)
        // …and back again when they are given reports.
        AreaPersonaFixtures.install(f, Persona.Override)
        kotlinx.coroutines.runBlocking { d.refreshAgents() }
        assertTrue(ViewId.Reports in d.nav())
        assertTrue(ViewId.Catalog in d.nav())
    }

    /**
     * A 403 on the report's download: the server's sentence (or the web's
     * words), and /admin/me + /admin/agents re-read at once so the nav drops
     * Reports without waiting for the 3-minute poll.
     */
    @Test fun reports403_saysWhy_andRereadsAccess() {
        val f = fake(Persona.Admin)
        val d = dash(f, Persona.Admin)
        AreaPersonaFixtures.install(f, Persona.Sales)
        f.on("GET", "/admin/conversations", code = 403, body = """{"detail":"Admin only"}""")
        val agentsBefore = f.gets("/admin/agents").size
        val meBefore = f.gets("/admin/me").size
        val vm = ReportsViewModel(d)
        settle()
        assertNull(vm.allConvs.value)
        assertEquals("Admin only", vm.loadError.value)
        assertEquals(agentsBefore + 1, f.gets("/admin/agents").size)
        assertEquals(meBefore + 1, f.gets("/admin/me").size)
        assertFalse("the nav corrected itself", ViewId.Reports in d.nav())
    }

    @Test fun reports403_withoutASentence_usesTheWebsWords() {
        val f = fake(Persona.Admin)
        f.on("GET", "/admin/conversations", code = 403, body = """{"detail":"Forbidden"}""")
        val vm = ReportsViewModel(dash(f, Persona.Admin))
        assertEquals(
            "Could not load conversations for this report — you don't have permission to see them.",
            vm.loadError.value,
        )
    }

    @Test fun overview403_staysQuiet_likeTheWeb_butRereadsAccess() {
        val f = fake(Persona.Admin)
        val d = dash(f, Persona.Admin)
        AreaPersonaFixtures.install(f, Persona.LegacyAgent)
        f.on("GET", "/admin/attribution", code = 403, body = """{"detail":"Admin only"}""")
        val before = f.gets("/admin/agents").size
        val vm = OverviewViewModel(d)
        settle()
        assertNull("attribution stays hidden, as on the web", vm.attrib.value)
        assertNotNull(vm.stats.value)
        assertEquals(before + 1, f.gets("/admin/agents").size)
        assertFalse(ViewId.Overview in d.nav())
    }

    @Test fun overviewStats403_estimatesAndSaysWhy() {
        val f = fake(Persona.Admin)
        f.on("GET", "/admin/stats", code = 403, body = """{"detail":"Not authenticated"}""")
        val vm = OverviewViewModel(dash(f, Persona.Admin))
        assertNull(vm.stats.value)
        assertEquals("You don't have permission to do that.", vm.statsError.value)
    }

    @Test fun catalogAudit403_staysHidden_andRereadsAccess() {
        val f = fake(Persona.Admin)
        val d = dash(f, Persona.Admin)
        f.on("GET", "/admin/catalog/audit", code = 403, body = """{"detail":"Forbidden"}""")
        val before = f.gets("/admin/me").size
        val vm = CatalogViewModel(d)
        settle()
        assertNull(vm.audit.value)
        assertEquals(before + 1, f.gets("/admin/me").size)
    }

    /** Only a 403 re-reads access: an outage must not hammer /admin/me and /admin/agents. */
    @Test fun otherFailures_doNotRereadAccess() {
        val f = fake(Persona.Admin)
        val d = dash(f, Persona.Admin)
        f.on("GET", "/admin/conversations", code = 500, body = """{"detail":"boom"}""")
        f.on("GET", "/admin/catalog/audit", code = 503, body = "")
        f.on("GET", "/admin/attribution", code = 500, body = "{}")
        val agents = f.gets("/admin/agents").size
        val me = f.gets("/admin/me").size
        ReportsViewModel(d); OverviewViewModel(d); CatalogViewModel(d)
        assertEquals(agents, f.gets("/admin/agents").size)
        assertEquals(me, f.gets("/admin/me").size)
    }
}
