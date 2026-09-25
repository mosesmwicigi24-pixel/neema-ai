package ke.co.bethanyhouse.neema.deals

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.feature.deals.DealsScreen
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.deals.DraftDialogCard
import ke.co.bethanyhouse.neema.orders.MainDispatcherRule
import ke.co.bethanyhouse.neema.orders.SeededStore
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import org.junit.Rule
import org.junit.Test

private fun renderDeals(
    paparazzi: Paparazzi,
    dark: Boolean = false,
    perms: List<String>? = null,
    configure: (FakeNeema) -> Unit = {},
    setup: (DealsViewModel) -> Unit = {},
) {
    val fake = FakeNeema.withFixtures()
    SalesFixtures.install(fake)
    if (perms != null) SalesFixtures.installReadOnly(fake, perms)
    configure(fake)
    val dash = dashboard(paparazzi.context, fake, role = if (perms != null) "agent" else "admin", superuser = perms == null)
    val store = SeededStore()
    setup(store.seed(DealsViewModel(dash)))
    paparazzi.snapshot { AppFrame(dark) { store.Provide { DealsScreen(dash) } } }
}

/** DealsView on a phone: the initiative queue over the stacked board. */
class DealsScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6.copy(screenHeight = 4200), showSystemUi = false)

    @Test fun board() = renderDeals(paparazzi)
    @Test fun boardDark() = renderDeals(paparazzi, dark = true)
    @Test fun guidanceEditor() = renderDeals(paparazzi) { vm ->
        vm.deals.value!!.first { it.id == "d2" }.let(vm::startGuidance)
        vm.setGuidanceDraft("No discount on this one — she already has the parish rate.")
    }
    @Test fun emptyQueueAndBoard() = renderDeals(paparazzi, configure = { f ->
        f.on("GET", "/admin/deals", body = """{"deals":[]}""")
        f.on("GET", "/admin/actions", body = """{"actions":[]}""")
    })
    /** Can see the pipeline, can't steer it or speak for the shop. */
    @Test fun readOnly() = renderDeals(paparazzi, perms = listOf(Perms.VIEW_LEADS, Perms.VIEW_CONVERSATIONS))
    @Test fun noAccess() = renderDeals(paparazzi, perms = listOf(Perms.VIEW_CONVERSATIONS))
}

/** The edit-and-send dialog over the board. */
class DealsDialogScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun dialog(dark: Boolean, id: String) {
        val fake = FakeNeema.withFixtures()
        SalesFixtures.install(fake)
        val dash = dashboard(paparazzi.context, fake)
        val action = DealsViewModel(dash).actions.value!!.first { it.id == id }
        paparazzi.snapshot {
            AppFrame(dark) {
                Box(Modifier.fillMaxSize().background(Color(0x99000000)).padding(24.dp), contentAlignment = Alignment.Center) {
                    DraftDialogCard(action, onDismiss = {}, onSend = {})
                }
            }
        }
    }

    @Test fun editAndSend() = dialog(false, "x1")
    @Test fun editAndSendDark() = dialog(true, "x1")
    /** No draft yet: empty text lets Neema write it from the reason. */
    @Test fun editAndSendNoDraft() = dialog(false, "x2")
}

/** A tablet: the three stage columns side by side. */
class DealsTabletScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_C, showSystemUi = false)

    @Test fun board() = renderDeals(paparazzi)
    @Test fun boardDark() = renderDeals(paparazzi, dark = true)
}
