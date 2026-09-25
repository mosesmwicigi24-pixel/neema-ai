package ke.co.bethanyhouse.neema.reports

import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.buildReport
import ke.co.bethanyhouse.neema.feature.reports.csvField
import ke.co.bethanyhouse.neema.feature.reports.csvFileName
import ke.co.bethanyhouse.neema.feature.reports.reportCsv
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures.NAIROBI
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures.NOW
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.time.LocalDate

/** The aggregation maths of ReportsView.tsx, on a fixed clock. */
class ReportMathTest {
    private val convs: List<Conversation> = NeemaJson.decodeFromString("[${ReportsFixtures.conversations.joinToString(",")}]")
    private val orders: List<Order> = NeemaJson.decodeFromString("[${ReportsFixtures.orders.joinToString(",")}]")
    private val agents: List<Agent> = NeemaJson.decodeFromString(Fixtures.agents)

    @Before fun tz() = ReportsFixtures.pinTimeZone()
    @org.junit.After fun untz() = ReportsFixtures.restoreTimeZone()

    private fun report(range: ReportRange, from: LocalDate? = null, to: LocalDate? = null) =
        buildReport(convs, orders, agents, range, from, to, NOW.toEpochMilli(), NAIROBI)

    @Test fun last30Days_countsAndRevenueExcludeCancelled() {
        val r = report(ReportRange.D30)
        // r8 is 45 days old; r9 has no messages and dates from its creation (4h ago).
        assertEquals(listOf("r1", "r2", "r3", "r4", "r5", "r6", "r7", "r9"), r.convs.map { it.id })
        assertEquals(3, r.humanConvs)
        assertEquals(4, r.aiConvs) // "paused" is neither
        assertEquals(listOf("o1", "o2", "o3", "o4", "o5", "o6"), r.orders.map { it.id })
        // 8000 + 12500 + 18000 + 4800 + 3500 — the cancelled 9600 is not revenue.
        assertEquals(46_800.0, r.revenue, 0.0)
        assertEquals(2, r.pending) // an "open" cart reads as pending (mapOrder)
        assertEquals(1, r.confirmed)
        assertEquals(2, r.delivered)
        assertEquals(1, r.cancelled)
    }

    @Test fun last7And90Days() {
        val w = report(ReportRange.D7)
        assertEquals(6, w.convs.size)
        assertEquals(listOf("o1", "o2", "o3", "o4", "o5"), w.orders.map { it.id })
        assertEquals(43_300.0, w.revenue, 0.0)
        val q = report(ReportRange.D90)
        assertEquals(9, q.convs.size)
        assertEquals(7, q.orders.size)
        assertEquals(71_800.0, q.revenue, 0.0)
    }

    @Test fun customRange_isWholeLocalDays_toInclusive() {
        val r = report(ReportRange.Custom, LocalDate.of(2026, 9, 20), LocalDate.of(2026, 9, 22))
        // r4 is on the 22nd — the "to" day, which the web's UTC parse dropped.
        assertEquals(listOf("r4", "r5"), r.convs.map { it.id })
        assertEquals(listOf("o3", "o4"), r.orders.map { it.id })
        assertEquals(18_000.0, r.revenue, 0.0)
        // The chart still shows 14 bars ending on the "to" day.
        assertEquals(14, r.convByDay.size)
        assertEquals("Tue", r.convByDay.last().label)
    }

    @Test fun customRange_withOneDateMissing_fallsBackTo30Days() {
        assertEquals(report(ReportRange.D30).convs, report(ReportRange.Custom, LocalDate.of(2026, 9, 20), null).convs)
        assertEquals(report(ReportRange.D30).orders, report(ReportRange.Custom, null, null).orders)
    }

    @Test fun customRange_backwards_isEmpty() {
        val r = report(ReportRange.Custom, LocalDate.of(2026, 9, 22), LocalDate.of(2026, 9, 20))
        assertEquals(0, r.convs.size)
        assertEquals(0, r.orders.size)
    }

    @Test fun perDayBuckets_7days() {
        val r = report(ReportRange.D7)
        assertEquals(listOf("Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"), r.convByDay.map { it.label })
        // Fri: r1 + r9 (created today); Thu r2; Wed r3; Tue r4; Sun r5.
        assertEquals(listOf(0.0, 1.0, 0.0, 1.0, 1.0, 1.0, 2.0), r.convByDay.map { it.value })
        // Revenue per day includes the cancelled order, exactly like the web's orderByDay.
        assertEquals(listOf(4800.0, 0.0, 9600.0, 18000.0, 0.0, 12500.0, 8000.0), r.orderByDay.map { it.value })
    }

    @Test fun perDayBuckets_countIsCappedAt14() {
        assertEquals(14, report(ReportRange.D30).convByDay.size)
        assertEquals(14, report(ReportRange.D90).orderByDay.size)
        assertEquals("Fri", report(ReportRange.D90).orderByDay.last().label)
    }

    @Test fun agentPerformance() {
        val stats = report(ReportRange.D30).agentStats
        assertEquals(listOf("Grace Wanjiru", "Moses Mwicigi", "Brian Otieno"), stats.map { it.agent.name })
        assertEquals(listOf(2, 1, 0), stats.map { it.handled })
        // Grace holds James (o3 18000, o6 3500) and Samuel (o4 9600, cancelled — the web counts it too).
        assertEquals(listOf(31_100.0, 8_000.0, 0.0), stats.map { it.revenue })
    }

    @Test fun emptyData() {
        val r = buildReport(emptyList(), emptyList(), emptyList(), ReportRange.D30, null, null, NOW.toEpochMilli(), NAIROBI)
        assertEquals(0.0, r.revenue, 0.0)
        assertEquals(14, r.convByDay.size)
        assertEquals(true, r.convByDay.all { it.value == 0.0 })
        assertEquals(emptyList<Any>(), r.agentStats)
    }

    @Test fun csv_headerRowsAndQuoting() {
        val csv = reportCsv(report(ReportRange.D30).orders)
        assertEquals(
            """
            Date,Customer,Amount,Status
            25 Sept 2026,Fr. Peter Kamau,8000,confirmed
            24 Sept 2026,Rev. Mary Achieng,12500,pending
            22 Sept 2026,Deacon James Mwangi,18000,delivered
            21 Sept 2026,"Kariuki, Samuel",9600,cancelled
            19 Sept 2026,+254 711 000 999,4800,pending
            15 Sept 2026,Deacon James Mwangi,3500,delivered
            """.trimIndent(),
            csv,
        )
        assertEquals("Date,Customer,Amount,Status\n", reportCsv(emptyList()))
        assertEquals("neema-report-custom.csv", csvFileName(ReportRange.Custom))
    }

    @Test fun csvField_quotesOnlyWhenNeeded() {
        assertEquals("plain", csvField("plain"))
        assertEquals("\"a,b\"", csvField("a,b"))
        assertEquals("\"say \"\"hi\"\"\"", csvField("say \"hi\""))
        assertEquals("\"two\nlines\"", csvField("two\nlines"))
    }
}
