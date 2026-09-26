package ke.co.bethanyhouse.neema.orders

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.deals.DealsScreen
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.leads.LeadDetail
import ke.co.bethanyhouse.neema.feature.leads.LeadsScreen
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.orders.OrdersScreen
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import org.junit.Rule
import org.junit.Test

/**
 * Orders, Deals and Leads when the network lets them down: the error state
 * that replaces a never-loaded screen, the banner over data that couldn't be
 * refreshed, and failures shown where the operator was typing.
 */
class SalesNetworkScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun fake() = FakeNeema.withFixtures().also { SalesFixtures.install(it) }

    // ── Orders ──────────────────────────────────────────────────────────────

    private fun orders(dark: Boolean = false, before: (FakeNeema) -> Unit = {}, after: (FakeNeema, OrdersViewModel) -> Unit = { _, _ -> }) {
        val fake = fake()
        before(fake)
        val dash = dashboard(paparazzi.context, fake)
        val store = SeededStore()
        val vm = store.seed(OrdersViewModel(dash))
        after(fake, vm)
        paparazzi.snapshot { AppFrame(dark) { store.Provide { OrdersScreen(dash) } } }
    }

    @Test fun ordersOffline() = orders(before = { it.offline("GET", "/admin/orders") })
    @Test fun ordersOfflineDark() = orders(dark = true, before = { it.offline("GET", "/admin/orders") })
    @Test fun ordersStale() = orders(after = { f, vm -> f.timeout("GET", "/admin/orders"); vm.refresh() })
    @Test fun ordersStaleDark() = orders(dark = true, after = { f, vm -> f.timeout("GET", "/admin/orders"); vm.refresh() })

    // ── Deals ───────────────────────────────────────────────────────────────

    private fun deals(dark: Boolean = false, before: (FakeNeema) -> Unit = {}, after: (FakeNeema, DealsViewModel) -> Unit = { _, _ -> }) {
        val fake = fake()
        before(fake)
        val dash = dashboard(paparazzi.context, fake)
        val store = SeededStore()
        val vm = store.seed(DealsViewModel(dash))
        after(fake, vm)
        paparazzi.snapshot { AppFrame(dark) { store.Provide { DealsScreen(dash) } } }
    }

    @Test fun dealsOffline() = deals(before = { it.offline("GET", "/admin/deals"); it.offline("GET", "/admin/actions") })
    @Test fun dealsOfflineDark() = deals(dark = true, before = { it.offline("GET", "/admin/deals"); it.offline("GET", "/admin/actions") })
    /** A refresh failed: the board stays under the banner; a send's answer was lost and is being checked. */
    @Test fun dealsStaleAndChecking() = deals(after = { f, vm ->
        f.timeout("POST", "/admin/actions/x1/approve")
        vm.act("x1", "approve")
        f.htmlPage("GET", "/admin/deals", 502)
        vm.refresh()
    })
    @Test fun dealsStaleAndCheckingDark() = deals(dark = true, after = { f, vm ->
        f.timeout("POST", "/admin/actions/x1/approve")
        vm.act("x1", "approve")
        f.htmlPage("GET", "/admin/deals", 502)
        vm.refresh()
    })
    /** Guidance that didn't save: the editor stays open with the text and the reason. */
    @Test fun dealsGuidanceFailed() = deals(after = { f, vm ->
        vm.startGuidance(vm.deals.value!!.first { it.id == "d3" })
        vm.setGuidanceDraft("No discount — she already has the parish rate.")
        f.offline("PATCH", "/admin/deals/d3")
        vm.saveGuidance("d3")
    })

    // ── Leads ───────────────────────────────────────────────────────────────

    private fun leads(dark: Boolean = false, before: (FakeNeema) -> Unit = {}, after: (FakeNeema, LeadsViewModel) -> Unit = { _, _ -> }) {
        val fake = fake()
        before(fake)
        val dash = dashboard(paparazzi.context, fake)
        val store = SeededStore()
        val vm = store.seed(LeadsViewModel(dash))
        after(fake, vm)
        paparazzi.snapshot { AppFrame(dark) { store.Provide { LeadsScreen(dash) } } }
    }

    @Test fun leadsOffline() = leads(before = { it.offline("GET", "/admin/leads") })
    @Test fun leadsOfflineDark() = leads(dark = true, before = { it.offline("GET", "/admin/leads") })
    @Test fun leadsStale() = leads(after = { f, vm -> f.timeout("GET", "/admin/leads"); vm.refresh() })

    private fun leadSheet(dark: Boolean = false, saving: Boolean = false, error: String? = null) {
        val dash = dashboard(paparazzi.context, fake())
        val vm = LeadsViewModel(dash)
        val lead = vm.leads.value.first { it.id == "u1" }
        paparazzi.snapshot {
            AppFrame(dark) {
                SheetFrame {
                    LeadDetail(lead, vm.stages.value, canManage = true, onClose = {}, onOpenChat = {}, onSave = {}, saving = saving, error = error)
                }
            }
        }
    }

    @Test fun leadSheetSaving() = leadSheet(saving = true)
    @Test fun leadSheetFailed() = leadSheet(error = "Couldn't save — no connection — check your internet and try again")
    @Test fun leadSheetFailedDark() = leadSheet(dark = true, error = "No answer from the server — your changes may not have saved. Save again to be sure.")
}

/** The same on a tablet, where the banner spans a wider board. */
class SalesNetworkTabletScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_C, showSystemUi = false)

    @Test fun dealsStale() {
        val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
        val dash = dashboard(paparazzi.context, fake)
        val store = SeededStore()
        val vm = store.seed(DealsViewModel(dash))
        fake.offline("GET", "/admin/deals"); fake.offline("GET", "/admin/actions")
        vm.refresh()
        paparazzi.snapshot { AppFrame(false) { store.Provide { DealsScreen(dash) } } }
    }

    @Test fun ordersOffline() {
        val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
        fake.offline("GET", "/admin/orders")
        val dash = dashboard(paparazzi.context, fake)
        val store = SeededStore()
        store.seed(OrdersViewModel(dash))
        paparazzi.snapshot { AppFrame(false) { store.Provide { OrdersScreen(dash) } } }
    }
}
