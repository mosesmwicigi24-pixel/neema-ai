package ke.co.bethanyhouse.neema.reports

import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.catalog.catalogColumns
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.feature.reports.reportCustomer
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import ke.co.bethanyhouse.neema.core.model.Order
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Round 10: a report left open overnight rolls over to the new day (the web
 * recomputes "now" on every render), the web's customer naming for unnamed
 * buyers, and the catalogue's column count on a degenerate width.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ReportsRolloverTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    @After fun tearDown() = Dispatchers.resetMain()

    /** A clock the test moves by hand. */
    private class HandClock(var at: Instant, private val zone: ZoneId) : Clock() {
        override fun getZone(): ZoneId = zone
        override fun withZone(zone: ZoneId?): Clock = HandClock(at, zone ?: this.zone)
        override fun instant(): Instant = at
    }

    @Test fun reportRollsOverAtLocalMidnight() {
        val sched = TestCoroutineScheduler()
        Dispatchers.setMain(StandardTestDispatcher(sched))
        val nairobi = ZoneId.of("Africa/Nairobi")
        // 23:59:00 in Nairobi on Friday 25 September.
        val clock = HandClock(LocalDate.of(2026, 9, 25).atTime(23, 59).atZone(nairobi).toInstant(), nairobi)
        val fake = FakeNeema.withFixtures().also(ReportsFixtures::install)
        val vm = ReportsViewModel(dashboard(paparazzi.context, fake), clock)
        vm.range.value = ReportRange.D7
        sched.runCurrent()
        assertNotNull("the first report is built", vm.report.value)
        val before = vm.report.value!!
        assertEquals(LocalDate.of(2026, 9, 25), vm.today.value)
        assertEquals("Fri", before.convByDay.last().label)

        // Two minutes later it is Saturday: the next midnight check rebuilds the report.
        clock.at = clock.at.plusSeconds(120)
        sched.advanceTimeBy(61_000); sched.runCurrent()
        assertEquals(LocalDate.of(2026, 9, 26), vm.today.value)
        val after = vm.report.value!!
        assertEquals("Sat", after.convByDay.last().label)
        assertEquals(7, after.convByDay.size)

        // Nothing else changed the inputs: no rebuild before the next midnight.
        sched.advanceTimeBy(3_600_000); sched.runCurrent()
        assertEquals(true, vm.report.value === after)
    }

    @Test fun reportRollsOverOnReturnToTheApp() {
        val sched = TestCoroutineScheduler()
        Dispatchers.setMain(StandardTestDispatcher(sched))
        val nairobi = ZoneId.of("Africa/Nairobi")
        val clock = HandClock(LocalDate.of(2026, 9, 25).atTime(22, 0).atZone(nairobi).toInstant(), nairobi)
        val d = dashboard(paparazzi.context, FakeNeema.withFixtures().also(ReportsFixtures::install))
        val vm = ReportsViewModel(d, clock)
        sched.runCurrent()
        d.container.foreground.value = false
        sched.runCurrent()
        // In the pocket overnight (no tick while in the background)…
        clock.at = clock.at.plusSeconds(10 * 3600)
        d.container.foreground.value = true
        sched.runCurrent()
        // …and back: the date is read at once.
        assertEquals(LocalDate.of(2026, 9, 26), vm.today.value)
        assertEquals("Sat", vm.report.value!!.convByDay.last().label)
    }

    /** The web's mapOrder: contact_name ?? wa_id, so an unnamed buyer reads as the bare number. */
    @Test fun unnamedBuyerIsTheirBareNumber_likeTheWeb() {
        assertEquals("254712345678", reportCustomer(Order(id = "x", waId = "254712345678")))
        assertEquals("Kariuki", reportCustomer(Order(id = "x", waId = "254712345678", contactName = "  Kariuki ")))
        // An empty name is kept by `??`, so displayName falls back to the formatted number.
        assertEquals("+254 712 345 678", reportCustomer(Order(id = "x", waId = "254712345678", contactName = "")))
        assertEquals("Unknown", reportCustomer(Order(id = "x", waId = "")))
    }

    @Test fun catalogColumns_neverFewerThanOne() {
        assertEquals(1, catalogColumns(0.dp))
        assertEquals(1, catalogColumns((-20).dp))
        assertEquals(2, catalogColumns(360.dp))
        assertEquals(1, catalogColumns(360.dp, fontScale = 2f))
        assertEquals(6, catalogColumns(1200.dp))
    }
}
