package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportTab
import ke.co.bethanyhouse.neema.feature.reports.ReportsScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.PageSlice
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.time.LocalDate

/** Every Reports tab and range, populated / empty / loading, phone / tablet, light / dark. */
@OptIn(ExperimentalCoroutinesApi::class)
class ReportsScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = PHONE)

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private fun shot(
        tab: ReportTab = ReportTab.Overview,
        range: ReportRange = ReportRange.D30,
        from: LocalDate? = null, to: LocalDate? = null,
        dark: Boolean = false,
        empty: Boolean = false,
        canExport: Boolean = true,
        page: Int = 0,
        picker: String? = null,
    ) {
        val f = FakeNeema.withFixtures().also { if (empty) ReportsFixtures.installEmpty(it) else ReportsFixtures.install(it) }
        if (!canExport) { f.on("GET", "/admin/me", body = VIEWER); f.on("GET", "/admin/agents", body = "[$VIEWER]") }
        val dash = dashboard(paparazzi.context, f, role = if (canExport) "admin" else "agent", superuser = canExport)
        val vm = ReportsViewModel(dash, ReportsFixtures.clock).apply {
            this.tab.value = tab; this.range.value = range; customFrom.value = from; customTo.value = to
        }
        paparazzi.snapshot { AppFrame(dark) { PageSlice(page) { ReportsScreen(dash, vm, initialPicker = picker) } } }
    }

    @Test fun overview30d() = shot()
    @Test fun overview30dPage2() = shot(page = 1)
    @Test fun overview30dDarkPage2() = shot(dark = true, page = 1)
    @Test fun overview30dDark() = shot(dark = true)
    @Test fun overview7d() = shot(range = ReportRange.D7)
    @Test fun overview90d() = shot(range = ReportRange.D90)
    @Test fun customRange() = shot(range = ReportRange.Custom, from = LocalDate.of(2026, 9, 20), to = LocalDate.of(2026, 9, 22))
    @Test fun customRangeUnset() = shot(range = ReportRange.Custom)
    /**
     * The custom range's date picker, over the web's bg-black/50 dim. The
     * picker rings the device's real "today" (it takes no clock), so these
     * pick a month in the past that the real date can never enter again —
     * the goldens don't drift from one day to the next.
     */
    @Test fun customRangePickerOpen() = shot(range = ReportRange.Custom, from = LocalDate.of(2025, 1, 10), to = LocalDate.of(2025, 1, 20), picker = "from")
    @Test fun customRangePickerOpenDark() = shot(range = ReportRange.Custom, to = LocalDate.of(2025, 1, 20), dark = true, picker = "to")
    @Test fun conversations() = shot(tab = ReportTab.Conversations)
    @Test fun conversationsPage2() = shot(tab = ReportTab.Conversations, page = 1)
    @Test fun conversationsDark() = shot(tab = ReportTab.Conversations, dark = true)
    @Test fun orders() = shot(tab = ReportTab.Orders)
    @Test fun ordersPage2() = shot(tab = ReportTab.Orders, page = 1)
    @Test fun agents() = shot(tab = ReportTab.Agents)
    @Test fun emptyOverview() = shot(empty = true)
    @Test fun emptyOrders() = shot(tab = ReportTab.Orders, empty = true)
    /** A Sales agent without export_reports still gets Export CSV — the web never checks it. */
    @Test fun limitedPermissionsStillExport() = shot(canExport = false)

    @Test fun loading() {
        // Main never runs: the full-list fetch is still in flight.
        Dispatchers.setMain(StandardTestDispatcher())
        val dash = dashboard(paparazzi.context, FakeNeema.withFixtures().also(ReportsFixtures::install))
        val vm = ReportsViewModel(dash, ReportsFixtures.clock)
        paparazzi.snapshot { AppFrame { ReportsScreen(dash, vm) } }
    }

    @Test fun tabletOverview() { paparazzi.unsafeUpdateConfig(TABLET); shot() }
    @Test fun tabletOverviewDark() { paparazzi.unsafeUpdateConfig(TABLET); shot(dark = true) }
    @Test fun tabletConversations() { paparazzi.unsafeUpdateConfig(TABLET); shot(tab = ReportTab.Conversations) }
    @Test fun tabletOrders() { paparazzi.unsafeUpdateConfig(TABLET); shot(tab = ReportTab.Orders) }
    @Test fun tabletAgents() { paparazzi.unsafeUpdateConfig(TABLET); shot(tab = ReportTab.Agents) }

    companion object {
        val PHONE = DeviceConfig.PIXEL_6
        val TABLET = DeviceConfig.PIXEL_C

        /** A Sales agent: may view reports but not export them. */
        val VIEWER = """{"id":"${ke.co.bethanyhouse.neema.testing.Fixtures.ME_ID}","name":"Moses Mwicigi","email":"moses@bethanyhouse.co.ke","role":"agent",
            "is_available":true,"is_superuser":false,"active_convs":4,"avatar_url":null,"created_at":"2026-01-01T00:00:00Z",
            "custom_role_id":"sales","custom_permissions":null,"role_name":"Sales","role_color":"#3b82f6",
            "role_permissions":["view_conversations","view_orders","view_reports"]}"""
    }
}
