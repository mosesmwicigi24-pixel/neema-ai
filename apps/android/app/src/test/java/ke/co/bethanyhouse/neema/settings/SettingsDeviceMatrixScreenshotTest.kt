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

/** Round 7: Settings across the device / font / theme matrix. */
class SettingsDeviceMatrixScreenshotTest : AreaShots() {
    private fun base() = FakeNeema.withFixtures().also { TeamFixtures.settings(it) }

    private fun settings(preview: SettingsPreview = SettingsPreview(), device: DeviceConfig, dark: Boolean = false, f: FakeNeema = base()) {
        val d = dash(f)
        shot(device, dark) { CompositionLocalProvider(LocalSettingsPreview provides preview) { SettingsScreen(d) } }
    }

    @Test fun small_0() = settings(device = Devices.SMALL)
    @Test fun small_1() = settings(SettingsPreview(scroll = 1600), device = Devices.SMALL)
    @Test fun small_2() = settings(SettingsPreview(scroll = 3200), device = Devices.SMALL)
    @Test fun small_3() = settings(SettingsPreview(scroll = 4800), device = Devices.SMALL)
    @Test fun smallXlFont_0() = settings(device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_1() = settings(SettingsPreview(scroll = 1700), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_2() = settings(SettingsPreview(scroll = 3400), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_3() = settings(SettingsPreview(scroll = 5100), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_4() = settings(SettingsPreview(scroll = 6800), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_5() = settings(SettingsPreview(scroll = 8500), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_6() = settings(SettingsPreview(scroll = 10200), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_7() = settings(SettingsPreview(scroll = 11900), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_8() = settings(SettingsPreview(scroll = 13600), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_9() = settings(SettingsPreview(scroll = 15300), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_10() = settings(SettingsPreview(scroll = 17000), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_11() = settings(SettingsPreview(scroll = 18700), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFont_12() = settings(SettingsPreview(scroll = 20400), device = Devices.SMALL_XL_FONT)
    @Test fun smallXlFontDark_3() = settings(SettingsPreview(scroll = 5100), device = Devices.SMALL_XL_FONT, dark = true)
    @Test fun pixel5LargeFont_0() = settings(device = Devices.PIXEL5_LARGE_FONT)
    @Test fun pixel5LargeFont_2() = settings(SettingsPreview(scroll = 4400), device = Devices.PIXEL5_LARGE_FONT)
    @Test fun fold_0() = settings(device = Devices.FOLD)
    @Test fun fold_1() = settings(SettingsPreview(scroll = 1900), device = Devices.FOLD)
    @Test fun tabletPortrait_0() = settings(device = Devices.TABLET_PORTRAIT)
    @Test fun tabletPortraitDark_1() = settings(SettingsPreview(scroll = 1600), device = Devices.TABLET_PORTRAIT, dark = true)
    @Test fun tabletLargeFont_0() = settings(device = Devices.TABLET_LARGE_FONT)
    @Test fun productPickerSmallXlFont() = settings(SettingsPreview(skuPicker = true), device = Devices.SMALL_XL_FONT,
        f = base().also { TeamFixtures.expiredOffer(it) })
}
