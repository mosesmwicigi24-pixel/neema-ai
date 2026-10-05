package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.feature.calls.CallReadiness
import ke.co.bethanyhouse.neema.feature.calls.CallReadiness.Missing
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A call to a closed app rings only when every link holds: notifications, the
 * background connection, Android not putting that connection to sleep, and
 * (Android 14+) the lock-screen take-over. The banner asks for one at a time,
 * the most fundamental first.
 */
class CallReadinessTest {
    @Test fun readyOnlyWhenEveryLinkHolds() {
        assertTrue(CallReadiness().ready)
        assertNull(CallReadiness().missing)
        assertFalse(CallReadiness(battery = false).ready)
        assertFalse(CallReadiness(background = false).ready)
    }

    @Test fun theMostFundamentalGapIsAskedFirst() {
        assertEquals(Missing.Notifications, CallReadiness(false, false, false, false).missing)
        assertEquals(Missing.Background, CallReadiness(fullScreen = false, background = false, battery = false).missing)
        assertEquals(Missing.Battery, CallReadiness(fullScreen = false, battery = false).missing)
        assertEquals(Missing.FullScreen, CallReadiness(fullScreen = false).missing)
    }
}
