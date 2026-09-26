package ke.co.bethanyhouse.neema.testing

import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.runtime.Composable
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.android.resources.ScreenOrientation

/**
 * Round 7: the device / font-scale matrix every area renders its key screens
 * on. Use it with any Paparazzi rule:
 *
 * ```
 * @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config)
 *
 * @Test fun ordersMatrix() = paparazzi.matrix(DeviceMatrix.core) { device ->
 *     AppFrame(device.dark) { DashboardShell(dash, device.widthClass) }
 * }
 * ```
 *
 * Each device writes its own golden (`<test>_<device.name>.png`). For a
 * single target use [Paparazzi.snapshotOn] or `DeviceConfig.withFontScale`.
 */
data class TestDevice(
    /** Goes into the snapshot name: keep it a short identifier. */
    val name: String,
    val config: DeviceConfig,
    val dark: Boolean = false,
) {
    /** The width in dp, as Compose sees it. */
    val widthDp: Int get() = config.screenWidth * 160 / config.density.dpiValue
    val heightDp: Int get() = config.screenHeight * 160 / config.density.dpiValue

    /** What MainActivity's calculateWindowSizeClass would report on this screen. */
    val widthClass: WindowWidthSizeClass get() = when {
        widthDp < 600 -> WindowWidthSizeClass.Compact
        widthDp < 840 -> WindowWidthSizeClass.Medium
        else -> WindowWidthSizeClass.Expanded
    }

    val fontScale: Float get() = config.fontScale

    fun dark() = copy(name = "${name}_dark", dark = true)
    fun fontScale(scale: Float) = copy(name = "${name}_font${fontLabel(scale)}", config = config.withFontScale(scale))
}

private fun fontLabel(scale: Float) = scale.toString().replace(".", "")

/** This config with the system font size set to [scale] (1.0, 1.3, 2.0 …). */
fun DeviceConfig.withFontScale(scale: Float): DeviceConfig = copy(fontScale = scale)

object DeviceMatrix {
    /** 360 × 640dp (Nexus 5): the narrowest phone we support. */
    val SMALL_PHONE = TestDevice("small360", DeviceConfig.NEXUS_5)

    /** 393dp Pixel 5 with the system font at 130%. */
    val PHONE_LARGE_TEXT = TestDevice("pixel5", DeviceConfig.PIXEL_5).fontScale(1.3f)

    /** 411dp Pixel 6 — the default phone of the existing shots. */
    val PHONE = TestDevice("phone", DeviceConfig.PIXEL_6)

    /** Any phone at the largest accessibility font size (200%). */
    val PHONE_HUGE_TEXT = TestDevice("phone", DeviceConfig.PIXEL_6).fontScale(2f)

    /** 600 × 900dp — an unfolded foldable / small tablet (Medium width class). */
    val FOLDABLE = TestDevice(
        "fold600",
        DeviceConfig.PIXEL_C.copy(screenWidth = 1200, screenHeight = 1800, orientation = ScreenOrientation.PORTRAIT),
    )

    /** 900 × 1280dp Pixel C held upright (Expanded, under Tailwind's lg). */
    val TABLET_PORTRAIT = TestDevice(
        "tabletPortrait",
        DeviceConfig.PIXEL_C.copy(screenWidth = 1800, screenHeight = 2560, orientation = ScreenOrientation.PORTRAIT),
    )

    /** 1280 × 900dp Pixel C in landscape (the web's desktop layout). */
    val TABLET_LANDSCAPE = TestDevice("tablet", DeviceConfig.PIXEL_C)

    /** Every width, light, default font. */
    val widths = listOf(SMALL_PHONE, PHONE, FOLDABLE, TABLET_PORTRAIT, TABLET_LANDSCAPE)

    /** Phones at the font scales the lens asks for (1.0, 1.3, 2.0) plus the 360dp phone. */
    val phoneFonts = listOf(PHONE, PHONE_LARGE_TEXT, PHONE_HUGE_TEXT, SMALL_PHONE.fontScale(1.3f))

    /**
     * The sensible default for a key screen: small phone, large-text phone,
     * phone at 200%, foldable, tablet portrait + landscape, and phone +
     * tablet in dark — eight images.
     */
    val core = listOf(
        SMALL_PHONE, PHONE_LARGE_TEXT, PHONE_HUGE_TEXT, FOLDABLE, TABLET_PORTRAIT, TABLET_LANDSCAPE,
        PHONE.dark(), TABLET_LANDSCAPE.dark(),
    )
}

/** Re-point this rule at [device] and snapshot [content] as `<test>_<device.name>`. */
fun Paparazzi.snapshotOn(device: TestDevice, content: @Composable (TestDevice) -> Unit) {
    unsafeUpdateConfig(deviceConfig = device.config)
    snapshot(device.name) { content(device) }
}

/**
 * One golden per device of [devices]. Where a screen needs per-device state
 * (a DashboardViewModel in dark mode, say), loop yourself:
 * `devices.forEach { d -> val dash = …(d.dark); snapshotOn(d) { … } }`.
 */
fun Paparazzi.matrix(devices: List<TestDevice>, content: @Composable (TestDevice) -> Unit) {
    devices.forEach { snapshotOn(it, content) }
}
