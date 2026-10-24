package ke.co.bethanyhouse.neema.core.notify

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import ke.co.bethanyhouse.neema.NeemaApplication

/**
 * Where Firebase delivers a call event when the app may not be running
 * (see [Push]). Android starts the process for it — NeemaApplication.onCreate
 * builds the container and starts the call manager first — and a high-priority
 * message may start a foreground service, so the live connection comes back
 * too: the call then rings, and is answered, exactly as with the app open.
 */
class NeemaPushService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        val app = application as? NeemaApplication ?: return
        runCatching { app.container.push.onNewToken(token) }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val app = application as? NeemaApplication ?: return
        runCatching {
            val c = app.container
            if (c.sessionStore.session.value == null) return     // signed out: never ring
            val frame = Push.frameOf(message.data, System.currentTimeMillis()) ?: return
            c.calls.onPush(frame)
            // Bring the live connection back while the call is on (the answer and
            // media need it); the high-priority message allows this start.
            if (message.data["type"] == "incoming_call" &&
                LiveService.wanted(true, c.prefs.backgroundLive.value)) {
                LiveService.start(this)
            }
            c.socket.nudge()
        }.onFailure {
            ke.co.bethanyhouse.neema.core.crash.CrashVault.recordNonFatal(it, "push-message")
        }
    }
}
