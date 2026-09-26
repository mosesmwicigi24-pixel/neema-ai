package ke.co.bethanyhouse.neema.orders

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.feature.calls.CallReadiness
import ke.co.bethanyhouse.neema.feature.calls.CallsScreen
import ke.co.bethanyhouse.neema.feature.deals.DealsScreen
import ke.co.bethanyhouse.neema.feature.leads.LeadsScreen
import ke.co.bethanyhouse.neema.feature.orders.OrdersScreen
import ke.co.bethanyhouse.neema.testing.A11yProbe
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.TestDevice
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesStressFixtures
import ke.co.bethanyhouse.neema.testing.snapshotOn
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 8: the four sales screens on a busy shop's data (1,000 orders, 500
 * leads, a 200-action queue, a 1,000-call log) across the device / font
 * matrix — what a lazily-drawn list and the derived figures look like at size.
 */
class SalesStressScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false)

    private fun dash(): DashboardViewModel =
        dashboard(paparazzi.context, FakeNeema.withFixtures().also { SalesStressFixtures.install(it) })

    private fun each(devices: List<TestDevice>, screen: @androidx.compose.runtime.Composable (DashboardViewModel) -> Unit) =
        devices.forEach { d ->
            val dash = dash()
            paparazzi.snapshotOn(d) { AppFrame(d.dark) { screen(dash) } }
        }

    /** The 8-device core set, plus an upright tablet at 200% text (the status cards go 2-up there). */
    @Test fun orders() = each(DeviceMatrix.core + DeviceMatrix.TABLET_PORTRAIT.fontScale(2f)) { OrdersScreen(it) }

    @Test fun leads() = each(
        listOf(DeviceMatrix.PHONE, DeviceMatrix.PHONE_HUGE_TEXT, DeviceMatrix.TABLET_LANDSCAPE, DeviceMatrix.PHONE.dark()),
    ) { LeadsScreen(it) }

    @Test fun deals() = each(
        listOf(DeviceMatrix.PHONE, DeviceMatrix.PHONE_HUGE_TEXT, DeviceMatrix.TABLET_LANDSCAPE, DeviceMatrix.PHONE.dark()),
    ) { DealsScreen(it) }

    @Test fun calls() = each(
        listOf(DeviceMatrix.SMALL_PHONE, DeviceMatrix.PHONE, DeviceMatrix.PHONE_HUGE_TEXT, DeviceMatrix.TABLET_LANDSCAPE, DeviceMatrix.PHONE.dark()),
    ) { CallsScreen(it, readinessOverride = CallReadiness()) }
}

/**
 * Round 8: every tappable on the four sales screens (with stress data) is
 * labelled and at least 48dp — at 100% and at 200% text.
 */
class SalesA11yTest {
    private val probe = A11yProbe()
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false, renderExtensions = setOf(probe))

    private fun check(name: String, screen: @androidx.compose.runtime.Composable (DashboardViewModel) -> Unit) =
        listOf(DeviceMatrix.PHONE, DeviceMatrix.PHONE_HUGE_TEXT).forEach { d ->
            val dash = dashboard(paparazzi.context, FakeNeema.withFixtures().also { SalesStressFixtures.install(it) })
            paparazzi.snapshotOn(d) { AppFrame { screen(dash) } }
            probe.assertAccessible()
            assertTrue("$name on ${d.name}: ${probe.tappables}", probe.tappables.size > 3)
        }

    @Test fun orders() = check("orders") { OrdersScreen(it) }
    @Test fun leads() = check("leads") { LeadsScreen(it) }
    @Test fun deals() = check("deals") { DealsScreen(it) }
    @Test fun calls() = check("calls") { CallsScreen(it, readinessOverride = CallReadiness()) }
}
