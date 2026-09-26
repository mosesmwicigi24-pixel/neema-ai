package ke.co.bethanyhouse.neema.leads

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.leads.Lead
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.leads.buildBoard
import ke.co.bethanyhouse.neema.feature.leads.buildStages
import ke.co.bethanyhouse.neema.feature.leads.filterLeads
import ke.co.bethanyhouse.neema.feature.leads.overlayLocal
import ke.co.bethanyhouse.neema.orders.ClockedMainRule
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesStressFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 8 — the leads kanban at five hundred leads: the board's figures from
 * one pass, a hundred card moves in a row, and a read that was already on the
 * wire when a card moved (it must not throw the card back).
 */
class LeadsStressTest {
    @get:Rule val main = ClockedMainRule()
    @get:Rule val paparazzi = Paparazzi() // a layoutlib Context for the container

    private val fake = FakeNeema.withFixtures().also { SalesStressFixtures.install(it) }

    private fun vm() = LeadsViewModel(dashboard(paparazzi.context, fake))

    private fun stageOf(vm: LeadsViewModel, id: String) = vm.leads.value.first { it.id == id }.leadStage

    @Test fun theBoardMatchesTheWebsPerColumnFilters() {
        val vm = vm()
        val leads = vm.leads.value
        assertEquals(500, leads.size)
        val stages = vm.stages.value
        assertEquals("the custom Measuring column is there", 8, stages.size)
        val filtered = filterLeads(leads, "all", "")
        val board = buildBoard(leads, filtered, stages)
        for (s in stages) {
            // LeadsView: leads.filter(l => l.lead_stage === stage.id), once per pill and once per column.
            assertEquals(s.id, leads.count { s.matches(it.leadStage) }, board.counts[s.id])
            assertEquals(s.id, filtered.filter { s.matches(it.leadStage) }.map { it.id }, board.columns.getValue(s.id).map { it.id })
            assertEquals(s.id, filtered.filter { s.matches(it.leadStage) }.sumOf { it.totalSpent }, board.columnValue.getValue(s.id), 0.001)
        }
        assertEquals("every lead lands in exactly one column", 500, board.columns.values.sumOf { it.size })
        assertEquals(leads.filter { it.leadStage.lowercase() !in setOf("lost", "won") }.sumOf { it.totalSpent }, board.pipelineValue, 0.001)
        assertEquals(leads.filter { it.leadStage.equals("won", true) }.sumOf { it.totalSpent }, board.wonValue, 0.001)
        // A search narrows the columns but not the pills' counts.
        val narrow = buildBoard(leads, filterLeads(leads, "all", "bishop"), stages)
        assertEquals(board.counts, narrow.counts)
        assertTrue(narrow.columns.values.sumOf { it.size } in 1 until 500)
    }

    @Test fun buildingTheBoardForFiveThousandLeadsIsFast() {
        val vm = vm()
        val base = vm.leads.value
        val many = (0 until 10).flatMap { k -> base.map { it.copy(id = "${it.id}-$k") } }
        val stages = buildStages(listOf("Measuring", "Fitting"))
        repeat(3) { buildBoard(many, many, stages) }
        val t = System.nanoTime()
        val filtered = filterLeads(many, "all", "fr.")
        buildBoard(many, filtered, stages)
        buildBoard(many, many, stages)
        val ms = (System.nanoTime() - t) / 1e6
        assertTrue("5,000 leads, 9 columns in ${ms}ms (budget 200)", ms < 200)
    }

    @Test fun aHundredMovesInARowEachSaveOnceAndNeverReloadTheBoard() {
        val vm = vm()
        val gets = fake.callsTo("GET", "/admin/leads").size
        val moved = (0 until 100).map { SalesStressFixtures.leadId(it * 5) }
        moved.forEach { id ->
            val lead = vm.leads.value.first { it.id == id }
            vm.moveTo(lead, "won")
        }
        assertEquals("one PATCH per card", 100, fake.calls.count { it.method == "PATCH" && it.path.startsWith("/admin/leads/") })
        assertTrue(moved.all { stageOf(vm, it) == "won" })
        assertEquals("a stage move needs no re-read of 500 leads", gets, fake.callsTo("GET", "/admin/leads").size)
        assertTrue(vm.saving.value.isEmpty())
    }

    /**
     * A read of the board was on the wire (a pull) when the operator moved a
     * card; the read's answer — from before the move — lands after it. The
     * card stays where it was moved; the next read is the server's truth.
     */
    @Test fun aReadFromBeforeAMoveDoesNotThrowTheCardBack() {
        val vm = vm()
        val id = SalesStressFixtures.leadId(7)
        val lead = vm.leads.value.first { it.id == id }
        val before = lead.leadStage
        val hold = fake.hang("GET", "/admin/leads")
        vm.refresh()
        vm.moveTo(lead, "won")
        assertEquals("won", stageOf(vm, id))
        hold.release() // the answer from before the move
        assertEquals("won", stageOf(vm, id))
        assertTrue(before != "won")
        assertEquals("the slow read plus nothing else", 1, hold.caught)
        // A read that starts after the move is the server's truth again (this
        // fake never stores a move, so the card goes back to what it says).
        vm.refresh()
        assertEquals(before, stageOf(vm, id))
    }

    @Test fun aSecondTapWhileAMoveIsSavingIsIgnored() {
        val vm = vm()
        val lead = vm.leads.value.first { it.id == SalesStressFixtures.leadId(12) }
        val hold = fake.hang("PATCH", "/admin/leads/.+")
        vm.moveTo(lead, "won")
        vm.moveTo(lead, "lost")
        assertEquals(1, hold.waiting)
        assertEquals("won", stageOf(vm, lead.id))
        hold.release()
        assertEquals(1, fake.calls.count { it.method == "PATCH" && it.path == "/admin/leads/${lead.id}" })
        assertEquals("won", stageOf(vm, lead.id))
    }

    @Test fun overlayKeepsOnlyTheProtectedRowsAndIsLinear() {
        val vm = vm()
        val server = vm.leads.value
        val onScreen = server.map { if (it.id == "u0003") it.copy(leadStage = "won") else it }.filterNot { it.id == "u0009" }
        val out = overlayLocal(server, onScreen, setOf("u0003", "u0009"))
        assertEquals("won", out.first { it.id == "u0003" }.leadStage)
        assertTrue("a lead deleted here stays gone", out.none { it.id == "u0009" })
        assertEquals(server.size - 1, out.size)
        assertEquals(server.filterNot { it.id == "u0009" }.map { it.id }, out.map { it.id })
        val many: List<Lead> = (0 until 10).flatMap { k -> server.map { it.copy(id = "${it.id}-$k") } }
        val keep = many.map { it.id }.filterIndexed { i, _ -> i % 7 == 0 }.toSet()
        repeat(3) { overlayLocal(many, many, keep) }
        val t = System.nanoTime()
        overlayLocal(many, many, keep)
        val ms = (System.nanoTime() - t) / 1e6
        assertTrue("5,000 rows overlaid in ${ms}ms (budget 200)", ms < 200)
    }
}
