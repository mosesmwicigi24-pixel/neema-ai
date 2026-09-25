package ke.co.bethanyhouse.neema.leads

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.feature.leads.LeadDetail
import ke.co.bethanyhouse.neema.feature.leads.LeadsScreen
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.orders.MainDispatcherRule
import ke.co.bethanyhouse.neema.orders.SeededStore
import ke.co.bethanyhouse.neema.orders.SheetFrame
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import org.junit.Rule
import org.junit.Test

private fun renderLeads(
    paparazzi: Paparazzi,
    dark: Boolean = false,
    perms: List<String>? = null,
    leadsJson: String? = null,
    setup: (LeadsViewModel) -> Unit = {},
) {
    val fake = FakeNeema.withFixtures()
    SalesFixtures.install(fake)
    if (leadsJson != null) fake.on("GET", "/admin/leads", body = leadsJson)
    if (perms != null) SalesFixtures.installReadOnly(fake, perms)
    val dash = dashboard(paparazzi.context, fake, role = if (perms != null) "agent" else "admin", superuser = perms == null)
    val store = SeededStore()
    setup(store.seed(LeadsViewModel(dash)))
    paparazzi.snapshot { AppFrame(dark) { store.Provide { LeadsScreen(dash) } } }
}

/** The lead detail sheet for lead [id]. */
private fun renderDetail(paparazzi: Paparazzi, id: String, dark: Boolean = false, canManage: Boolean = true) {
    val fake = FakeNeema.withFixtures()
    SalesFixtures.install(fake)
    val dash = dashboard(paparazzi.context, fake)
    val vm = LeadsViewModel(dash)
    val lead = vm.leads.value.first { it.id == id }
    paparazzi.snapshot {
        AppFrame(dark) {
            SheetFrame {
                LeadDetail(lead, vm.stages.value, canManage = canManage, onClose = {}, onOpenChat = {}, onSave = {})
            }
        }
    }
}

/** LeadsView on a phone: the kanban scrolls sideways, a column at a time. */
class LeadsScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    @Test fun kanban() = renderLeads(paparazzi)
    @Test fun kanbanDark() = renderLeads(paparazzi, dark = true)
    @Test fun filteredProposal() = renderLeads(paparazzi) { it.filterStage.value = "proposal" }
    @Test fun searchNoMatch() = renderLeads(paparazzi) { it.search.value = "zzz-nobody" }
    @Test fun empty() = renderLeads(paparazzi, leadsJson = "[]")
    @Test fun readOnly() = renderLeads(paparazzi, perms = listOf(Perms.VIEW_LEADS))
    @Test fun noAccess() = renderLeads(paparazzi, perms = listOf(Perms.VIEW_CONVERSATIONS))

    @Test fun detail() = renderDetail(paparazzi, "u1")
    @Test fun detailDark() = renderDetail(paparazzi, "u1", dark = true)
    @Test fun detailUnknownNoNotes() = renderDetail(paparazzi, "u3")
    @Test fun detailReadOnly() = renderDetail(paparazzi, "u1", canManage = false)
}

/** A tablet: seven canonical columns plus the custom "measuring", 210dp each. */
class LeadsTabletScreenshotTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_C, showSystemUi = false)

    @Test fun kanban() = renderLeads(paparazzi)
    @Test fun kanbanDark() = renderLeads(paparazzi, dark = true)
}
