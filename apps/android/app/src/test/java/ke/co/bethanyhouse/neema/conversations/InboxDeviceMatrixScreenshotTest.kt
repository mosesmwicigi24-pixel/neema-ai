package ke.co.bethanyhouse.neema.conversations

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader
import android.graphics.drawable.BitmapDrawable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import coil.Coil
import coil.ImageLoader
import com.android.resources.ScreenOrientation
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsScreen
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxPolishFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 7 — the inbox and the thread across devices: a 360dp phone at font
 * scale 1.3 and 2.0, a Pixel 5 at 1.3, a ~600dp foldable, tablet portrait and
 * landscape, light and dark; long names, 44 rows, Swahili + emoji, unbroken
 * URLs, six-digit shillings; and the composer squeezed to the height left when
 * the keyboard is up (Paparazzi cannot raise an IME, so the window is simply
 * as short as an IME would leave it).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxDeviceMatrixScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_5, showSystemUi = false, maxPercentDifference = 0.1)

    private val sched = TestCoroutineScheduler()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        val b = Bitmap.createBitmap(800, 600, Bitmap.Config.ARGB_8888)
        Canvas(b).drawRect(0f, 0f, 800f, 600f, Paint().apply {
            shader = LinearGradient(0f, 0f, 800f, 600f, 0xFFB9C7AE.toInt(), 0xFF6F8566.toInt(), Shader.TileMode.CLAMP)
        })
        val img = BitmapDrawable(paparazzi.context.resources, b)
        Coil.setImageLoader(
            ImageLoader.Builder(paparazzi.context)
                .components { add(coil.intercept.Interceptor { chain -> coil.request.SuccessResult(img, chain.request, coil.decode.DataSource.MEMORY) }) }
                .placeholder(img).build(),
        )
    }

    @After fun tearDown() = Dispatchers.resetMain()

    private class Owner : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }
    private class Screen(val dash: DashboardViewModel, val vm: ConversationsViewModel, val owner: ViewModelStoreOwner)

    private fun screen(long: Boolean = true): Screen {
        val fake = FakeNeema.withFixtures().also(InboxFixtures::install).also { if (long) InboxPolishFixtures.install(it) }
        val dash = dashboard(paparazzi.context, fake, "admin", true)
        val owner = Owner()
        val vm = ViewModelProvider.create(owner, viewModelFactory { initializer { ConversationsViewModel(dash) } })[ConversationsViewModel::class]
        check(vm.rows.value.isNotEmpty()) { "rows not ready" }
        return Screen(dash, vm, owner)
    }

    private fun Screen.snap(device: DeviceConfig, dark: Boolean = false) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        paparazzi.snapshot {
            AppFrame(dark) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides owner) { ConversationsScreen(dash) }
            }
        }
    }

    private val smallPhone = DeviceConfig.NEXUS_5                     // 360 × 640 dp
    private val pixel5 = DeviceConfig.PIXEL_5                         // 393 × 851 dp
    private val foldable = DeviceConfig.NEXUS_7                       // 600 × 960 dp
    private val tabletPortrait = DeviceConfig.NEXUS_10.copy(orientation = ScreenOrientation.PORTRAIT, screenWidth = 1600, screenHeight = 2560)
    private val tabletLandscape = DeviceConfig.PIXEL_C                // 1280 × 900 dp

    /** A Pixel 5 with the keyboard up: ~ 400 dp of window left above the IME. */
    private val pixel5Keyboard = DeviceConfig.PIXEL_5.copy(screenHeight = 1100)

    // ═══════════════ The list ═══════════════

    @Test fun list_smallPhone_font13() = screen().snap(smallPhone.copy(fontScale = 1.3f))
    @Test fun list_smallPhone_font20() = screen().snap(smallPhone.copy(fontScale = 2.0f))
    @Test fun list_smallPhone_font20_dark() = screen().snap(smallPhone.copy(fontScale = 2.0f), dark = true)
    @Test fun list_pixel5_font13_dark() = screen().snap(pixel5.copy(fontScale = 1.3f), dark = true)
    @Test fun list_bulkSelect_smallPhone_font13() = screen().apply { vm.enterSelect("lp1") }.snap(smallPhone.copy(fontScale = 1.3f))

    // ═══════════════ The thread (phone) ═══════════════

    @Test fun thread_long_pixel5() = screen().apply { vm.select("lp1") }.snap(pixel5)
    @Test fun thread_long_pixel5_dark() = screen().apply { vm.select("lp1") }.snap(pixel5, dark = true)
    @Test fun thread_long_smallPhone_font20() = screen().apply { vm.select("lp1") }.snap(smallPhone.copy(fontScale = 2.0f))
    @Test fun thread_long_smallPhone_font13_dark() = screen().apply { vm.select("lp1") }.snap(smallPhone.copy(fontScale = 1.3f), dark = true)

    /** Keyboard up, with the AI draft open and a quote: the text box must stay on screen. */
    @Test fun composer_keyboardUp_draftAndQuote() = screen().apply {
        vm.select("lp1"); vm.generateDraft(); vm.beginReplyTo(vm.thread.value.messages["lp1"]!!.first { it.id == "l6" })
    }.snap(pixel5Keyboard)

    @Test fun composer_keyboardUp_draftAndQuote_font20_dark() = screen().apply {
        vm.select("lp1"); vm.generateDraft(); vm.beginReplyTo(vm.thread.value.messages["lp1"]!!.first { it.id == "l6" })
    }.snap(pixel5Keyboard.copy(fontScale = 2.0f), dark = true)

    @Test fun composer_keyboardUp_typing_smallPhone() = screen().apply {
        vm.select("lp1"); vm.setReplyText("Asante Padre 🙏 Tutatuma leo — tracking: https://www.bethanyhouse.co.ke/track/BH-ORD-2026-000184")
    }.snap(smallPhone.copy(screenHeight = 1000))

    // ═══════════════ Foldable & tablet ═══════════════

    @Test fun foldable_twoPane() = screen().apply { vm.select("lp1") }.snap(foldable)
    @Test fun foldable_twoPane_dark_font13() = screen().apply { vm.select("lp1") }.snap(foldable.copy(fontScale = 1.3f), dark = true)
    @Test fun tablet_portrait_long() = screen().apply { vm.select("lp1") }.snap(tabletPortrait)
    @Test fun tablet_landscape_long_dark() = screen().apply { vm.select("lp1"); vm.setActivityOpen(true) }.snap(tabletLandscape, dark = true)
    @Test fun tablet_landscape_font20() = screen().apply { vm.select("lp1") }.snap(tabletLandscape.copy(fontScale = 2.0f))
}
