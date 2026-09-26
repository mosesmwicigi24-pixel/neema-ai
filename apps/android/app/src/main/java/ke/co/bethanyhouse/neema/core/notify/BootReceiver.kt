package ke.co.bethanyhouse.neema.core.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import ke.co.bethanyhouse.neema.NeemaApplication

/**
 * Brings [LiveService] back after a reboot (`BOOT_COMPLETED`) or an app
 * update (`MY_PACKAGE_REPLACED`) — both kill the process, and without this
 * alerts and ringing calls would stop until the agent happened to open the
 * app. Only when someone is signed in and "Stay connected in background" is
 * on; otherwise it does nothing.
 *
 * Manifest: needs `android.permission.RECEIVE_BOOT_COMPLETED` (a normal,
 * install-time permission — no prompt). Both broadcasts are on Android's
 * list of exemptions that may start a foreground service from the
 * background; on Android 15 a BOOT_COMPLETED receiver may not start a
 * `dataSync` service, which is why LiveService uses `remoteMessaging` on
 * API 34+. The encrypted session store isn't readable before the first
 * unlock, so LOCKED_BOOT_COMPLETED is deliberately not handled.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in ACTIONS) return
        val c = (context.applicationContext as? NeemaApplication)?.container ?: return
        // Creating the process already ran NeemaApplication.onCreate, whose
        // LiveLifecycle starts the service a moment later — but only the
        // receiver's own few seconds are exempt from the background-start
        // limits, so start it here, synchronously.
        if (LiveService.wanted(c.sessionStore.current != null, c.prefs.backgroundLive.value)) LiveService.start(context)
    }

    companion object {
        val ACTIONS = setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED)
    }
}
