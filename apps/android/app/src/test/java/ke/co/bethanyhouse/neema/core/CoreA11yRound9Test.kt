package ke.co.bethanyhouse.neema.core

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.ui.components.SearchField
import ke.co.bethanyhouse.neema.testing.A11yProbe
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.snapshotOn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Round 9: core's SearchField is a 48dp touch target (its box keeps the web's 40dp), and so is its ✕. */
class CoreA11yRound9Test {
    private val probe = A11yProbe()

    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false, renderExtensions = setOf(probe))

    @Test fun searchFieldTouchTargets() = listOf(DeviceMatrix.PHONE, DeviceMatrix.PHONE_HUGE_TEXT).forEach { d ->
        paparazzi.snapshotOn(d) {
            AppFrame {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SearchField("", {}, placeholder = "Search orders…")
                    SearchField("Njeri", {})
                }
            }
        }
        probe.assertAccessible()
        val clear = probe.tappables.single { it.label == "Clear" }
        assertEquals(48f, clear.heightDp, 0.5f)
        assertTrue(probe.tappables.toString(), probe.tappables.count { it.heightDp >= 47.5f } == probe.tappables.size)
    }
}
