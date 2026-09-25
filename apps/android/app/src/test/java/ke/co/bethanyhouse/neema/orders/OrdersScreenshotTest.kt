package ke.co.bethanyhouse.neema.orders

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.feature.orders.OrderDetail
import ke.co.bethanyhouse.neema.feature.orders.Pager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.feature.orders.OrdersScreen
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import org.junit.Rule
import org.junit.Test

/** OrdersView on a phone: the list in every state, and the order detail sheet. */
class OrdersScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun render(
        dark: Boolean = false,
        orders: List<String> = SalesFixtures.orders,
        perms: List<String>? = null,
        setup: (OrdersViewModel, List<Order>) -> Unit = { _, _ -> },
    ) {
        val fake = FakeNeema.withFixtures()
        SalesFixtures.install(fake, orders)
        if (perms != null) SalesFixtures.installReadOnly(fake, perms)
        val dash = dashboard(paparazzi.context, fake, role = if (perms != null) "agent" else "admin", superuser = perms == null)
        val store = SeededStore()
        val vm = store.seed(OrdersViewModel(dash))
        setup(vm, dash.orders.value)
        paparazzi.snapshot {
            AppFrame(dark) { store.Provide { OrdersScreen(dash) } }
        }
    }

    /** The detail sheet's content for [order], as a bottom sheet over the list. */
    private fun detail(order: String, dark: Boolean = false, canManage: Boolean = true, busy: Boolean = false) {
        val fake = FakeNeema.withFixtures()
        SalesFixtures.install(fake, listOf(order))
        val dash = dashboard(paparazzi.context, fake)
        val o = dash.orders.value.first()
        paparazzi.snapshot {
            AppFrame(dark) { SheetFrame { OrderDetail(dash, o, canManage = canManage, busy = busy, onStatus = {}) } }
        }
    }

    @Test fun populated() = render()
    @Test fun populatedDark() = render(dark = true)
    @Test fun filteredConfirmed() = render { vm, _ -> vm.setFilter("confirmed") }
    @Test fun searchNoMatch() = render { vm, _ -> vm.setSearch("zzz-nobody") }
    @Test fun empty() = render(orders = emptyList())
    @Test fun noAccess() = render(perms = listOf(Perms.VIEW_CONVERSATIONS))

    @Test fun detailLinked() = detail(SalesFixtures.linkedOrder)
    @Test fun detailLinkedDark() = detail(SalesFixtures.linkedOrder, dark = true)
    @Test fun detailFailedPush() = detail(SalesFixtures.failedOrder)
    @Test fun detailUpdating() = detail(SalesFixtures.failedOrder, busy = true)
    @Test fun detailReadOnly() = detail(SalesFixtures.failedOrder, canManage = false)
}

/** The pager under the list: 100 orders is seven pages, so the five buttons window around the current one. */
class OrdersPaginationScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    @Test fun pagerStates() = paparazzi.snapshot {
        AppFrame(false) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Pager(page = 1, totalPages = 7, total = 100, onPage = {})
                Pager(page = 4, totalPages = 7, total = 100, onPage = {})
                Pager(page = 7, totalPages = 7, total = 100, onPage = {})
                Pager(page = 2, totalPages = 3, total = 34, onPage = {})
            }
        }
    }

    @Test fun pagerDark() = paparazzi.snapshot {
        AppFrame(true) { Column(Modifier.padding(16.dp)) { Pager(page = 5, totalPages = 7, total = 100, onPage = {}) } }
    }
}

/** A tablet: four status cards in a row, 24dp gutters. */
class OrdersTabletScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_C, showSystemUi = false)

    @Test fun populated() {
        val fake = FakeNeema.withFixtures()
        SalesFixtures.install(fake)
        val dash = dashboard(paparazzi.context, fake)
        val store = SeededStore()
        store.seed(OrdersViewModel(dash)).setFilter("pending")
        paparazzi.snapshot { AppFrame(false) { store.Provide { OrdersScreen(dash) } } }
    }
}

/**
 * Page 2 of sixteen orders: the lone row closes the bordered card with its
 * rounded bottom, and the pager ("Showing 16–16 of 16") sits under it.
 */
class OrdersLastPageScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun render(dark: Boolean) {
        val fake = FakeNeema.withFixtures()
        SalesFixtures.install(fake, SalesFixtures.manyOrders.take(16))
        val dash = dashboard(paparazzi.context, fake)
        val store = SeededStore()
        store.seed(OrdersViewModel(dash)).setPage(2)
        paparazzi.snapshot { AppFrame(dark) { store.Provide { OrdersScreen(dash) } } }
    }

    @Test fun lastPage() = render(false)
    @Test fun lastPageDark() = render(true)
}
