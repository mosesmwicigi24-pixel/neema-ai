package ke.co.bethanyhouse.neema.app

import androidx.lifecycle.SavedStateHandle
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.testContainer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 10 (core carry-over): page.tsx's toast — one at a time, replaced by
 * the next, gone after 3.5 s — held by the dashboard rather than the shell's
 * composition, so a rotation or a recreated activity never drops or replays
 * one, a process death brings the pending one back, and the 3.5 s only count
 * while the agent can see it.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ToastLifecycleTest {
    // Only for a Context (layoutlib); nothing is rendered here.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private fun SavedStateHandle.afterProcessDeath() = SavedStateHandle(keys().associateWith { get<Any?>(it) })

    private fun dash(handle: SavedStateHandle = SavedStateHandle()) =
        DashboardViewModel(testContainer(paparazzi.context, FakeNeema.withFixtures()), handle).also {
            it.toastClock = { scheduler.currentTime }
        }

    private val DashboardViewModel.shown get() = currentToast.value?.message

    @Test fun aToastShowsForThreeAndAHalfSecondsInFront() {
        val d = dash()
        d.toast("Order updated")
        assertEquals("Order updated", d.shown)
        assertEquals(ToastType.Success, d.currentToast.value?.type)
        advance(3_499); assertEquals("Order updated", d.shown)
        advance(2); assertNull(d.shown)
    }

    @Test fun theNextToastReplacesItAndGetsItsOwnFullTime() {
        val d = dash()
        d.toast("First")
        advance(3_000)
        d.toast("Second", ToastType.Error)
        // The web's first timer would clear the second 500 ms in; each gets its 3.5 s here.
        advance(1_000); assertEquals("Second", d.shown)
        advance(2_499); assertEquals("Second", d.shown)
        advance(2); assertNull(d.shown)
    }

    @Test fun aToastRaisedWithNoShellWatchingIsStillThereWhenItComesBack() {
        // The old shell collected a SharedFlow in composition: a toast raised
        // while the activity was being recreated went nowhere.
        val d = dash()
        d.toast("Saved")
        advance(100)
        assertEquals("the shell reads the same state after a rotation", "Saved", d.currentToast.value?.message)
    }

    @Test fun aToastRaisedInTheBackgroundWaitsForTheAgent() {
        val d = dash()
        d.container.foreground.value = false
        d.toast("New message: Mama Njeri", ToastType.Info)
        advance(10 * 60_000)
        assertEquals("ten minutes away: still waiting", "New message: Mama Njeri", d.shown)
        d.container.foreground.value = true
        advance(3_499); assertNotNull("its full time once back", d.shown)
        advance(2); assertNull(d.shown)
    }

    @Test fun leavingMidwayKeepsWhatWasLeftAndAtLeastASecondAndAHalf() {
        val d = dash()
        val fg = d.container.foreground
        d.toast("Saved")
        advance(1_000)
        fg.value = false
        advance(60_000)
        fg.value = true
        advance(2_499); assertEquals("2.5 s were left", "Saved", d.shown)
        advance(2); assertNull(d.shown)

        d.toast("Sent")
        advance(3_400)
        fg.value = false; advance(5_000); fg.value = true
        advance(1_499); assertEquals("100 ms would be a flicker: 1.5 s", "Sent", d.shown)
        advance(2); assertNull(d.shown)
    }

    @Test fun thePendingToastSurvivesProcessDeath() {
        val handle = SavedStateHandle()
        val d = dash(handle)
        d.toast("Couldn't save — check your connection", ToastType.Error)
        advance(1_000)
        val again = dash(handle.afterProcessDeath())
        assertEquals("Couldn't save — check your connection", again.shown)
        assertEquals(ToastType.Error, again.currentToast.value?.type)
        advance(3_499); assertNotNull(again.shown)
        advance(2); assertNull(again.shown)
    }

    @Test fun anExpiredToastIsNotRestored() {
        val handle = SavedStateHandle()
        val d = dash(handle)
        d.toast("Saved")
        advance(3_600)
        assertNull(dash(handle.afterProcessDeath()).shown)
    }

    @Test fun signingOutTakesTheLastAgentsToastWithIt() {
        val d = dash()
        d.endCall = {}
        d.toast("Order BH-2001 marked paid")
        d.logout()
        advance(10)
        assertNull(d.shown)
    }
}
