package ke.co.bethanyhouse.neema.catalog

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.testing.A11yProbe
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import ke.co.bethanyhouse.neema.testing.snapshotOn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 8: Catalog on the shared device / font / theme matrix (it had none),
 * and an accessibility probe over the grid: every tappable — the cards, the
 * category menu, the audit banner — at least 48dp and labelled.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CatalogMatrixScreenshotTest {
    private val probe = A11yProbe()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false, renderExtensions = setOf(probe))

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private fun screen(dark: Boolean = false): @androidx.compose.runtime.Composable () -> Unit {
        val d = dashboard(paparazzi.context, FakeNeema.withFixtures().also(ReportsFixtures::install))
        val vm = CatalogViewModel(d)
        return { AppFrame(dark) { CatalogScreen(d, vm) } }
    }

    @Test
    fun catalogMatrix() = DeviceMatrix.core.forEach { device ->
        val content = screen(device.dark)
        paparazzi.snapshotOn(device) { content() }
    }

    @Test
    fun catalogTappablesAreLargeAndLabelled() {
        val content = screen()
        paparazzi.snapshotOn(DeviceMatrix.PHONE_LARGE_TEXT) { content() }
        // The search box is core's SearchField (40dp tall; reported to core) — everything of Catalog's own passes.
        probe.assertAccessible(exempt = setOf("Search name, SKU or alias…"))
        // Each card is announced once: the equal-height row's sizing copy is hidden from accessibility.
        val labels = probe.tappables.map { it.label }
        assertEquals(labels.distinct(), labels)
    }
}
