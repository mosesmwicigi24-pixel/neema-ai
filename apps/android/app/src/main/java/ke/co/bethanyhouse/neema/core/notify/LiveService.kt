package ke.co.bethanyhouse.neema.core.notify

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.R

/**
 * Keeps the process (and so the live socket) alive while the app is in the
 * background, so escalations and ringing calls still reach the agent — the
 * web gets this for free from an open browser tab. There is no FCM in the
 * backend; this is the Android equivalent of "leave the dashboard open".
 *
 * During a call the [CallManager] re-promotes the service with the
 * microphone type (see [startForCall]) so Android keeps capturing audio.
 */
class LiveService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val inCall = intent?.getBooleanExtra(EXTRA_IN_CALL, false) == true
        val n = NotificationCompat.Builder(this, Notifier.CH_LIVE)
            .setSmallIcon(R.drawable.ic_stat_neema)
            .setContentTitle(if (inCall) "Neema call in progress" else "Neema is connected")
            .setContentText(if (inCall) "Tap to return to the call" else "Alerts and calls will reach you")
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setContentIntent(Notifier.openIntent(this, 1))
            .build()
        val type = when {
            Build.VERSION.SDK_INT < 29 -> 0
            inCall && Build.VERSION.SDK_INT >= 30 -> ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            Build.VERSION.SDK_INT >= 34 -> ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING
            else -> ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        }
        runCatching { ServiceCompat.startForeground(this, NOTIF_ID, n, type) }
            .recoverCatching {
                // The microphone type throws on API 34+ without RECORD_AUDIO; keep the
                // live connection alive with the plain type rather than dropping it.
                if (type == 0 || !inCall) throw it
                val plain = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING
                    else ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                ServiceCompat.startForeground(this, NOTIF_ID, n, plain)
            }
            .onFailure { stopSelf() }
        return START_STICKY
    }

    companion object {
        private const val NOTIF_ID = 1001
        private const val EXTRA_IN_CALL = "in_call"

        fun start(ctx: Context) = launch(ctx, false)
        fun startForCall(ctx: Context) = launch(ctx, true)

        private fun launch(ctx: Context, inCall: Boolean) {
            runCatching {
                ContextCompat.startForegroundService(ctx, Intent(ctx, LiveService::class.java).putExtra(EXTRA_IN_CALL, inCall))
            }
        }

        fun stop(ctx: Context) { runCatching { ctx.stopService(Intent(ctx, LiveService::class.java)) } }
    }
}
