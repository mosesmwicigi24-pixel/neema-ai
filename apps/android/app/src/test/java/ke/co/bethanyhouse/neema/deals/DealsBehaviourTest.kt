package ke.co.bethanyhouse.neema.deals

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.deals.fmtDue
import ke.co.bethanyhouse.neema.orders.MainDispatcherRule
import ke.co.bethanyhouse.neema.orders.ToastLog
import ke.co.bethanyhouse.neema.orders.bodies
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.serialization.json.Json
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.time.Instant

/** DealsView's behaviour: the board's loads, approve / veto, and every deal patch. */
class DealsBehaviourTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private lateinit var toasts: ToastLog

    private fun vm(): DealsViewModel {
        val dash = dashboard(paparazzi.context, fake)
        toasts = ToastLog(dash)
        return DealsViewModel(dash)
    }

    @After fun tearDown() { if (::toasts.isInitialized) toasts.close() }

    private fun json(s: String) = Json.parseToJsonElement(s)
    private fun gets(path: String) = fake.calls.filter { it.method == "GET" && it.path == path }.map { it.query }

    @Test fun loadsOpenDealsWonCountAndThePendingQueue() {
        val vm = vm()
        assertEquals(listOf("status=open", "status=won"), gets("/admin/deals"))
        assertEquals(listOf("status=pending"), gets("/admin/actions"))
        assertEquals(listOf("d1", "d2", "d3", "d4"), vm.deals.value!!.map { it.id })
        assertEquals(2, vm.wonCount.value)
        assertEquals(listOf("x1", "x2"), vm.actions.value!!.map { it.id })
    }

    @Test fun failedLoadsShowEmptyNotLoading() {
        fake.on("GET", "/admin/deals", code = 500, body = "{}")
        fake.on("GET", "/admin/actions", code = 500, body = "{}")
        val vm = vm()
        assertEquals(emptyList<Any>(), vm.deals.value)
        assertEquals(emptyList<Any>(), vm.actions.value)
    }

    @Test fun sendAsDraftedPostsAnEmptyBodyAndReloads() {
        val vm = vm()
        val before = gets("/admin/actions").size
        vm.act("x1", "approve")
        assertEquals(listOf(json("{}")), fake.bodies("POST", "/admin/actions/x1/approve"))
        assertEquals("Sent ✓", toasts.all.last().message)
        assertEquals(before + 1, gets("/admin/actions").size)
        assertTrue(vm.acting.value.isEmpty())
    }

    @Test fun editAndSendPostsTheEditedDraft() {
        val vm = vm()
        vm.act("x1", "approve", "  Father, we deliver Friday 🙏  ")
        assertEquals(listOf(json("""{"draft":"Father, we deliver Friday 🙏"}""")), fake.bodies("POST", "/admin/actions/x1/approve"))
    }

    @Test fun emptiedDraftLetsNeemaWriteIt() {
        val vm = vm()
        vm.act("x2", "approve", "   ")
        assertEquals(listOf(json("{}")), fake.bodies("POST", "/admin/actions/x2/approve"))
    }

    @Test fun vetoPostsToVeto() {
        val vm = vm()
        vm.act("x2", "veto")
        assertEquals(listOf(json("{}")), fake.bodies("POST", "/admin/actions/x2/veto"))
        assertEquals("Vetoed", toasts.all.last().message)
    }

    @Test fun failedApproveSaysWhich() {
        fake.on("POST", "/admin/actions/.*/approve", code = 409, body = """{"detail":"Action is sent"}""")
        val vm = vm()
        vm.act("x1", "approve")
        val t = toasts.all.last()
        assertEquals(ToastType.Error, t.type)
        assertEquals("approve failed", t.message)
        assertTrue(vm.acting.value.isEmpty())
    }

    @Test fun wonAndLostPatchStatusAndStage() {
        val vm = vm()
        vm.markWon("d1")
        vm.markLost("d2")
        assertEquals(listOf(json("""{"status":"won","stage":"won"}""")), fake.bodies("PATCH", "/admin/deals/d1"))
        assertEquals(listOf(json("""{"status":"lost","stage":"lost"}""")), fake.bodies("PATCH", "/admin/deals/d2"))
        assertEquals("Marked lost", toasts.all.last().message)
    }

    @Test fun guidanceEditorSavesOnlyGuidanceAndCloses() {
        val vm = vm()
        vm.startGuidance(vm.deals.value!!.first { it.id == "d1" })
        assertEquals("d1", vm.editing.value)
        assertEquals("Offer free delivery to Nyeri", vm.guidanceDraft.value)
        vm.setGuidanceDraft("x".repeat(450))
        assertEquals(400, vm.guidanceDraft.value.length)
        vm.setGuidanceDraft("No discount on this one")
        vm.saveGuidance("d1")
        assertEquals(listOf(json("""{"guidance":"No discount on this one"}""")), fake.bodies("PATCH", "/admin/deals/d1"))
        assertEquals("Guidance saved — Neema obeys it now", toasts.all.last().message)
        assertNull(vm.editing.value)
    }

    @Test fun cancelLeavesGuidanceUntouched() {
        val vm = vm()
        vm.startGuidance(vm.deals.value!!.first())
        vm.cancelGuidance()
        assertNull(vm.editing.value)
        assertTrue(fake.calls.none { it.method == "PATCH" })
    }

    @Test fun failedPatchToasts() {
        fake.on("PATCH", "/admin/deals/.*", code = 404, body = """{"detail":"Deal not found"}""")
        val vm = vm()
        vm.markWon("d1")
        assertEquals(ToastType.Error, toasts.all.last().type)
        assertEquals("Update failed", toasts.all.last().message)
    }

    @Test fun dueLabels() {
        val now = Instant.parse("2026-09-25T12:00:00Z").toEpochMilli()
        assertEquals("", fmtDue(null, now))
        assertEquals("due now", fmtDue("2026-09-25T11:59:00Z", now))
        assertEquals("in 1m", fmtDue("2026-09-25T12:00:20Z", now))
        assertEquals("in 45m", fmtDue("2026-09-25T12:45:00Z", now))
        assertEquals("in 5h", fmtDue("2026-09-25T17:30:00Z", now))
        assertEquals("in 47h", fmtDue("2026-09-27T11:00:00Z", now))
        assertEquals("in 3d", fmtDue("2026-09-28T13:00:00Z", now))
    }
}
