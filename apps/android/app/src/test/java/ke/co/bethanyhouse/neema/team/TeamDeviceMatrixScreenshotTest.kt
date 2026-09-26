package ke.co.bethanyhouse.neema.team

import androidx.compose.runtime.CompositionLocalProvider
import app.cash.paparazzi.DeviceConfig
import ke.co.bethanyhouse.neema.feature.agents.AgentsScreen
import ke.co.bethanyhouse.neema.feature.agents.LocalTeamPreview
import ke.co.bethanyhouse.neema.feature.agents.TeamPreview
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Test

/**
 * Round 7: the Team screen and its forms across the device / font / theme
 * matrix — a 360dp phone at font 1.0 and 2.0, a Pixel 5 at 1.3, a foldable,
 * a tablet both ways — plus the dialogs people type into on small phones.
 */
class TeamDeviceMatrixScreenshotTest : AreaShots() {
    private fun team(preview: TeamPreview = TeamPreview(), device: DeviceConfig, dark: Boolean = false) {
        val d = dash(FakeNeema.withFixtures().also(TeamFixtures::install))
        shot(device, dark) { CompositionLocalProvider(LocalTeamPreview provides preview) { AgentsScreen(d) } }
    }

    // ── Agents list ──────────────────────────────────────────────────────────
    @Test fun agentsSmall() = team(device = Devices.SMALL)
    @Test fun agentsSmallXlFont() = team(device = Devices.SMALL_XL_FONT)
    @Test fun agentsSmallXlFontDark() = team(device = Devices.SMALL_XL_FONT, dark = true)
    @Test fun agentsSmallXlFontLongName() = team(TeamPreview(scrollItem = 5), device = Devices.SMALL_XL_FONT)
    @Test fun agentsPixel5LargeFont() = team(device = Devices.PIXEL5_LARGE_FONT)
    @Test fun agentsFold() = team(device = Devices.FOLD)
    @Test fun agentsTabletLargeFont() = team(device = Devices.TABLET_LARGE_FONT)

    // ── Roles list ───────────────────────────────────────────────────────────
    @Test fun rolesSmallXlFont() = team(TeamPreview(tab = "roles"), device = Devices.SMALL_XL_FONT)
    @Test fun rolesSmallDark() = team(TeamPreview(tab = "roles"), device = Devices.SMALL, dark = true)
    @Test fun rolesTabletPortraitDark() = team(TeamPreview(tab = "roles"), device = Devices.TABLET_PORTRAIT, dark = true)

    // ── Forms on small phones ────────────────────────────────────────────────
    @Test fun addAgentSmallXlFont() = team(TeamPreview(dialog = "create",
        typed = mapOf("name" to "Wanjiku Kamau-Ochieng Nyambura", "email" to "wanjiku.kamau-ochieng.nyambura@bethanyhouse.co.ke")),
        device = Devices.SMALL_XL_FONT)
    @Test fun editAgentLongSmall() = team(TeamPreview(dialog = "edit:${TeamFixtures.AGENT4_ID}"), device = Devices.SMALL)
    @Test fun resetPasswordSmallXlFont() = team(TeamPreview(dialog = "pw:${TeamFixtures.AGENT4_ID}",
        typed = mapOf("password" to "newpassword", "confirm" to "newpasswrd")), device = Devices.SMALL_XL_FONT)
    @Test fun removeAgentSmallXlFontDark() = team(TeamPreview(dialog = "del:${TeamFixtures.AGENT4_ID}"), device = Devices.SMALL_XL_FONT, dark = true)
    @Test fun roleEditorSmall() = team(TeamPreview(tab = "roles", dialog = "role:support"), device = Devices.SMALL)
    @Test fun roleEditorSmallXlFont() = team(TeamPreview(tab = "roles", dialog = "role:support"), device = Devices.SMALL_XL_FONT)
    @Test fun roleEditorSmallDark() = team(TeamPreview(tab = "roles", dialog = "role:create"), device = Devices.SMALL, dark = true)
    @Test fun roleEditorFold() = team(TeamPreview(tab = "roles", dialog = "role:support"), device = Devices.FOLD)
    @Test fun assignRoleSmallXlFont() = team(TeamPreview(dialog = "assign:${TeamFixtures.AGENT4_ID}"), device = Devices.SMALL_XL_FONT)
    @Test fun assignRolePixel5LargeFontDark() = team(TeamPreview(dialog = "assign:${Fixtures.AGENT2_ID}"), device = Devices.PIXEL5_LARGE_FONT, dark = true)
}
