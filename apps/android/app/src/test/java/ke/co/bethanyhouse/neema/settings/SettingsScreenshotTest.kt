package ke.co.bethanyhouse.neema.settings

import androidx.compose.runtime.CompositionLocalProvider
import app.cash.paparazzi.DeviceConfig
import ke.co.bethanyhouse.neema.feature.settings.LocalSettingsPreview
import ke.co.bethanyhouse.neema.feature.settings.SettingsPreview
import ke.co.bethanyhouse.neema.feature.settings.SettingsScreen
import ke.co.bethanyhouse.neema.team.AreaShots
import ke.co.bethanyhouse.neema.team.Devices
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Test

/**
 * Settings (SettingsView.tsx + the pipeline stage list) in every state. Long
 * pages are shot a screen at a time ("…_1", "…_2" scroll further down) so each
 * image stays at full resolution.
 */
class SettingsScreenshotTest : AreaShots() {
    /** The base data set with crm.py's settings routes as the server answers them. */
    private fun base() = FakeNeema.withFixtures().also { TeamFixtures.settings(it) }

    private fun settings(
        preview: SettingsPreview = SettingsPreview(),
        dark: Boolean = false,
        device: DeviceConfig = Devices.PHONE,
        f: FakeNeema = base(),
        role: String = "admin",
        superuser: Boolean = true,
    ) {
        val d = dash(f, role, superuser)
        shot(device, dark) { CompositionLocalProvider(LocalSettingsPreview provides preview) { SettingsScreen(d) } }
    }

    /** One phone screen is ~2400px; step a little less so consecutive shots overlap. */
    private fun at(part: Int) = SettingsPreview(scroll = part * 2100)

    // Offer in "category" scope, translation on, one custom stage.
    @Test fun page_0() = settings(at(0))
    @Test fun page_1() = settings(at(1))
    @Test fun page_2() = settings(at(2))
    @Test fun page_3() = settings(at(3))
    @Test fun page_4() = settings(at(4))
    @Test fun pageDark_0() = settings(at(0), dark = true)
    @Test fun pageDark_1() = settings(at(1), dark = true)
    @Test fun pageDark_2() = settings(at(2), dark = true)
    @Test fun pageDark_3() = settings(at(3), dark = true)
    @Test fun pageDark_4() = settings(at(4), dark = true)
    @Test fun pageTablet_0() = settings(device = Devices.TABLET)
    @Test fun pageTablet_1() = settings(SettingsPreview(scroll = 1600), device = Devices.TABLET)
    @Test fun pageTablet_2() = settings(SettingsPreview(scroll = 3200), device = Devices.TABLET)
    @Test fun pageTabletDark_0() = settings(device = Devices.TABLET, dark = true)
    @Test fun pageTabletDark_1() = settings(SettingsPreview(scroll = 1600), device = Devices.TABLET, dark = true)

    /** Nothing declared: "Start offer", scope "all", translation off with nothing spent, four stages (the limit). */
    private val blank get() = base().also {
        TeamFixtures.noOffer(it)
        it.on("GET", "/admin/settings/translation", body = """{"enabled":false,"default":false,"spend_30d_usd":0,"calls_30d":0}""")
        it.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["Measuring","Sampling","Awaiting deposit","In production"]}""")
        it.on("GET", "/admin/settings/directives", body = """{"directives":"","max_chars":600}""")
    }
    @Test fun blank_0() = settings(at(0), f = blank)
    @Test fun blank_1() = settings(at(1), f = blank)
    @Test fun blankDark_1() = settings(at(1), f = blank, dark = true)

    /** A stored offer past its end date, scoped to products (chips name the catalogue items). */
    private val expired get() = base().also { TeamFixtures.expiredOffer(it) }
    @Test fun expiredProducts_0() = settings(at(0), f = expired)
    @Test fun expiredProducts_1() = settings(SettingsPreview(scroll = 1500), f = expired)
    @Test fun expiredProductsDark_1() = settings(SettingsPreview(scroll = 1500), f = expired, dark = true)

    /** All four GETs failed: each card says so, with its own Retry (the web leaves them on Loading… forever). */
    @Test fun loading() = settings(
        f = base().also { f ->
            listOf("directives", "translation", "offer", "pipeline-stages").forEach { f.on("GET", "/admin/settings/$it", code = 500, body = "{}") }
        },
    )

    @Test fun lastDayPicker() = settings(SettingsPreview(datePicker = "ends"))
    @Test fun firstDayPickerDark() = settings(SettingsPreview(datePicker = "starts"), dark = true)
    @Test fun endOfferConfirm() = settings(SettingsPreview(confirmEnd = true))
    @Test fun productPicker() = settings(SettingsPreview(skuPicker = true), f = expired)
    @Test fun productPickerDark() = settings(SettingsPreview(skuPicker = true), f = expired, dark = true)

    @Test fun noAccess() = settings(
        f = base().also {
            it.on("GET", "/admin/agents", body = TeamFixtures.agentsWithMe("agent", false, listOf("view_conversations")))
        },
        role = "agent", superuser = false,
    )
}
