package ke.co.bethanyhouse.neema.profile

import androidx.compose.runtime.CompositionLocalProvider
import app.cash.paparazzi.DeviceConfig
import ke.co.bethanyhouse.neema.feature.profile.LocalProfilePreview
import ke.co.bethanyhouse.neema.feature.profile.ProfilePreview
import ke.co.bethanyhouse.neema.feature.profile.ProfileScreen
import ke.co.bethanyhouse.neema.team.AreaShots
import ke.co.bethanyhouse.neema.team.Devices
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Test

/** Round 7: Profile across the device / font / theme matrix, with its forms open on small phones. */
class ProfileDeviceMatrixScreenshotTest : AreaShots() {
    /** Signed in as the long-named agent, so the header and e-mail wrap. */
    private fun longNamed() = FakeNeema.withFixtures().also(TeamFixtures::install).also {
        it.on("GET", "/admin/me", body = TeamFixtures.ormAgent(
            id = TeamFixtures.AGENT4_ID, name = "Wanjiku Kamau-Ochieng Nyambura",
            email = "wanjiku.kamau-ochieng.nyambura@bethanyhouse.co.ke", role = "agent", superuser = false,
        ))
    }

    private fun profile(
        preview: ProfilePreview = ProfilePreview(),
        device: DeviceConfig,
        dark: Boolean = false,
        f: FakeNeema = FakeNeema.withFixtures().also(TeamFixtures::install),
    ) {
        val d = dash(f)
        d.setDark(dark)
        shot(device, dark) { CompositionLocalProvider(LocalProfilePreview provides preview) { ProfileScreen(d) } }
    }

    @Test fun small() = profile(device = Devices.SMALL)
    @Test fun smallXlFont_0() = profile(device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_1() = profile(ProfilePreview(scroll = 1800), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_2() = profile(ProfilePreview(scroll = 3600), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_3() = profile(ProfilePreview(scroll = 5400), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFontDark_0() = profile(device = Devices.SMALL_XL_FONT, dark = true)
    @Test fun pixel5LargeFont() = profile(device = Devices.PIXEL5_LARGE_FONT)
    @Test fun fold() = profile(device = Devices.FOLD)
    @Test fun tabletPortraitDark() = profile(device = Devices.TABLET_PORTRAIT, dark = true)
    @Test fun longNameSmall() = profile(device = Devices.SMALL, f = longNamed())
    @Test fun longNameSmallXlFontDark() = profile(device = Devices.SMALL_XL_FONT, dark = true, f = longNamed())
    @Test fun editingSmallXlFont() = profile(ProfilePreview(editMode = true, scroll = 300), device = Devices.SMALL_XL_FONT)
    @Test fun passwordSmallXlFont() = profile(ProfilePreview(changingPassword = true, scroll = 2700,
        typed = mapOf("password" to "newpassword", "confirm" to "newpassword")), device = Devices.SMALL_XL_FONT)
    @Test fun passwordSmallDark() = profile(ProfilePreview(changingPassword = true, scroll = 700), device = Devices.SMALL, dark = true)
}
