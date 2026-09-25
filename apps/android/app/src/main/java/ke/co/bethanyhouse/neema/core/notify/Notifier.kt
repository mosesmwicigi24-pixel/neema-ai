package ke.co.bethanyhouse.neema.core.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.MainActivity
import ke.co.bethanyhouse.neema.R

/** System notification channels + posting helpers. */
object Notifier {
    const val CH_ALERTS = "neema_alerts"
    const val CH_MESSAGES = "neema_messages"
    const val CH_CALLS = "neema_calls"
    const val CH_LIVE = "neema_live"

    const val EXTRA_OPEN_CONV = "open_conv"       // wa_id / external_id / conversation id
    const val EXTRA_VIEW = "view"                 // a ViewId name
    const val EXTRA_CALL_ID = "call_id"
    const val EXTRA_CALL_ACTION = "call_action"   // "show" | "answer" | "decline"

    fun createChannels(ctx: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH_ALERTS, "Alerts", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Escalations, transfers, new conversations and order updates"
        })
        nm.createNotificationChannel(NotificationChannel(CH_MESSAGES, "Customer messages", NotificationManager.IMPORTANCE_DEFAULT))
        nm.createNotificationChannel(NotificationChannel(CH_CALLS, "Incoming calls", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "WhatsApp voice calls ringing the team"
        })
        nm.createNotificationChannel(NotificationChannel(CH_LIVE, "Live connection", NotificationManager.IMPORTANCE_MIN).apply {
            description = "Keeps Neema connected so alerts and calls arrive in the background"
            setShowBadge(false)
        })
    }

    fun canPost(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    fun openIntent(ctx: Context, requestCode: Int, extras: Intent.() -> Unit = {}): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            extras()
        }
        return PendingIntent.getActivity(ctx, requestCode, i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    fun post(
        ctx: Context, id: Int, channel: String, title: String, body: String,
        convKey: String? = null, view: String? = null,
    ) {
        if (!canPost(ctx)) return
        val n = NotificationCompat.Builder(ctx, channel)
            .setSmallIcon(R.drawable.ic_stat_neema)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(openIntent(ctx, id) {
                convKey?.let { putExtra(EXTRA_OPEN_CONV, it) }
                view?.let { putExtra(EXTRA_VIEW, it) }
            })
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify(id, n) }
    }

    fun cancel(ctx: Context, id: Int) = NotificationManagerCompat.from(ctx).cancel(id)
}
