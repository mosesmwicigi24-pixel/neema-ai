package ke.co.bethanyhouse.neema.orders

import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.feature.deals.DealsScreen
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.leads.LeadDetail
import ke.co.bethanyhouse.neema.feature.leads.LeadsScreen
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.orders.OrderDetail
import ke.co.bethanyhouse.neema.feature.orders.OrdersScreen
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesPolishFixtures
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * Round 7 — the sales screens across the device / font / theme matrix, on
 * stress data (7-digit KES totals, long Swahili + emoji titles, 40 rows).
 * Every shot also reads the semantics tree: the controls these screens own
 * must be labelled, and the ones fixed this round must be ≥ 48dp.
 */
class SalesPolishScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private val audit = TouchAudit()

    private fun shot(device: DeviceConfig, dark: Boolean, content: @Composable () -> Unit) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        paparazzi.snapshot { AppFrame(dark) { audit.Wrap(content) } }
        assertEquals("unlabelled tappables", emptyList<Tappable>(), audit.unlabelled())
    }

    private fun fake() = FakeNeema.withFixtures().also(SalesPolishFixtures::install)

    /** The controls fixed this round keep a 48dp touch target on every device in the matrix. */
    private fun assertTouch(vararg labels: String) =
        assertEquals("touch targets under 48dp", emptyList<Tappable>(), audit.tooSmall(48.dp, *labels))

    /** The whole sheet, however long: the same phone, three screens tall. */
    private fun DeviceConfig.tall() = copy(screenHeight = screenHeight * 3)

    // ── Orders ──────────────────────────────────────────────────────────────
    private fun orders(device: DeviceConfig, dark: Boolean = false, setup: (OrdersViewModel, List<Order>) -> Unit = { _, _ -> }) {
        val dash = dashboard(paparazzi.context, fake())
        val store = SeededStore()
        setup(store.seed(OrdersViewModel(dash)), dash.orders.value)
        shot(device, dark) { store.Provide { OrdersScreen(dash) } }
        assertTouch("Page ", "Previous page", "Next page", "Close", "Mark as")
    }

    private fun orderDetail(device: DeviceConfig, dark: Boolean = false) {
        val dash = dashboard(paparazzi.context, fake())
        val o = dash.orders.value.first { it.id == "254711222333_1773480600000" }
        shot(device, dark) { SheetFrame { OrderDetail(dash, o, busy = false, onStatus = {}) } }
        assertTouch("Close", "Mark as", "Open in hub", "Customer's order page", "Copy link", "Open conversation")
    }

    @Test fun ordersSmallPhone() = orders(Devices.SmallPhoneLargeText)
    @Test fun ordersPixel5LargeTextDark() = orders(Devices.Pixel5LargeText, dark = true)
    @Test fun ordersHugeText() = orders(Devices.HugeText)
    @Test fun ordersFoldable() = orders(Devices.Foldable)
    @Test fun ordersTabletPortrait() = orders(Devices.TabletPortrait)
    @Test fun ordersTabletLandscapeDark() = orders(Devices.TabletLandscape, dark = true)
    @Test fun orderDetailSmallPhone() = orderDetail(Devices.SmallPhoneLargeText)
    @Test fun orderDetailHugeTextDark() = orderDetail(Devices.HugeText, dark = true)
    @Test fun orderDetailTablet() = orderDetail(Devices.TabletLandscape)
    @Test fun orderDetailSmallPhoneFull() = orderDetail(Devices.SmallPhoneLargeText.tall())
    /** A wide tablet: the order opens in a pane beside the list, not a sheet over it. */
    @Test fun ordersTwoPane() = orders(Devices.TabletLandscape) { vm, list ->
        vm.select(list.first { it.id == "254711222333_1773480600000" })
    }
    @Test fun ordersTwoPaneDark() = orders(Devices.TabletLandscape, dark = true) { vm, list ->
        vm.select(list.first { it.id == "254711222333_1773480600000" })
    }

    // ── Leads ───────────────────────────────────────────────────────────────
    private fun leads(device: DeviceConfig, dark: Boolean = false, setup: (LeadsViewModel) -> Unit = {}) {
        val dash = dashboard(paparazzi.context, fake())
        val store = SeededStore()
        setup(store.seed(LeadsViewModel(dash)))
        shot(device, dark) { store.Provide { LeadsScreen(dash) } }
        assertTouch("All (", "New (", "Contacted →", "← ")
    }

    /** The lead sheet; [keyboard] shrinks the window by a keyboard's height, as adjustResize does. */
    private fun leadDetail(device: DeviceConfig, dark: Boolean = false, keyboard: Boolean = false) {
        val dash = dashboard(paparazzi.context, fake())
        val vm = LeadsViewModel(dash)
        val lead = vm.leads.value.first { it.id == "L1" }
        val d = if (keyboard) device.copy(screenHeight = device.screenHeight - 300 * device.density.dpiValue / 160) else device
        shot(d, dark) { SheetFrame { LeadDetail(lead, vm.stages.value, onClose = {}, onOpenChat = {}, onSave = {}) } }
        assertTouch("Close", "Open chat", "Save Changes", "Cancel", "Qualified", "Proposal")
    }

    @Test fun leadsSmallPhone() = leads(Devices.SmallPhoneLargeText)
    @Test fun leadsHugeTextDark() = leads(Devices.HugeText, dark = true)
    @Test fun leadsFoldable() = leads(Devices.Foldable)
    @Test fun leadsTabletPortrait() = leads(Devices.TabletPortrait)
    @Test fun leadsTabletLandscape() = leads(Devices.TabletLandscape)
    @Test fun leadsTabletLandscapeDark() = leads(Devices.TabletLandscape, dark = true)
    @Test fun leadDetailSmallPhone() = leadDetail(Devices.SmallPhoneLargeText)
    @Test fun leadDetailHugeTextDark() = leadDetail(Devices.HugeText, dark = true)
    @Test fun leadDetailWithKeyboard() = leadDetail(Devices.SmallPhoneLargeText, keyboard = true)
    @Test fun leadDetailSmallPhoneFull() = leadDetail(Devices.SmallPhoneLargeText.tall())

    // ── Deals ───────────────────────────────────────────────────────────────
    private fun deals(device: DeviceConfig, dark: Boolean = false) {
        val dash = dashboard(paparazzi.context, fake())
        val store = SeededStore()
        store.seed(DealsViewModel(dash))
        shot(device, dark) { store.Provide { DealsScreen(dash) } }
        assertTouch("Send", "Edit & send", "Veto", "Open chat", "Guidance", "Won", "Lost")
    }

    @Test fun dealsSmallPhone() = deals(Devices.SmallPhoneLargeText)
    @Test fun dealsHugeTextDark() = deals(Devices.HugeText, dark = true)
    @Test fun dealsFoldable() = deals(Devices.Foldable)
    @Test fun dealsTabletPortrait() = deals(Devices.TabletPortrait)
    @Test fun dealsSmallPhoneFull() = deals(Devices.SmallPhoneLargeText.tall())
}
