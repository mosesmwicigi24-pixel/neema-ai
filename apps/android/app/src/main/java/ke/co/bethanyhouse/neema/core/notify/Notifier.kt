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
import androidx.compose.ui.graphics.toArgb
import ke.co.bethanyhouse.neema.core.ui.theme.Brand

/**
 * One system notification the notification centre wants shown — built as
 * plain data so what is posted (channel, text, tap target, grouping) can be
 * tested without Android's notification manager.
 */
data class SystemAlert(
    /** The notification id: one per conversation, so a thread's alerts replace each other. */
    val id: Int,
    val channel: String,
    val title: String,
    val body: String,
    /** NotificationCompat.PRIORITY_* (pre-O devices; channels decide on O+). */
    val priority: Int,
    /** Tap opens this conversation (wa_id / external_id / conversation id). */
    val convKey: String? = null,
    /** …or this view (a web `?view=` name). */
    val view: String? = null,
    /** The bell entry, marked read when the notification is tapped. */
    val notificationId: String? = null,
)

/** Where [NotificationCenter] sends system notifications; a recorder in tests. */
interface AlertSink {
    /** False when Android won't show them (POST_NOTIFICATIONS denied, or switched off). */
    fun canPost(): Boolean
    fun post(alert: SystemAlert)
    fun cancel(id: Int)
    /** Ids of our notifications still in the tray (the agent may have swiped some away); null if unknown. */
    fun active(): Set<Int>? = null
    /** The group's summary row ("3 Neema alerts") once two or more are in the tray. */
    fun summary(count: Int, lines: List<String>)
    fun cancelSummary()
}

/** System notification channels + posting helpers. */
object Notifier {
    const val CH_ALERTS = "neema_alerts"
    const val CH_MESSAGES = "neema_messages"
    const val CH_UPDATES = "neema_updates"
    const val CH_CALLS = "neema_calls"
    const val CH_LIVE = "neema_live"

    /** Every bell alert shares one group, so a burst stacks under one summary. */
    const val GROUP_ALERTS = "ke.co.bethanyhouse.neema.ALERTS"
    const val SUMMARY_ID = 1002

    const val EXTRA_OPEN_CONV = "open_conv"       // wa_id / external_id / conversation id
    const val EXTRA_VIEW = "view"                 // a ViewId name
    const val EXTRA_NOTIFICATION = "notification" // the bell entry's id, marked read on tap
    const val EXTRA_CALL_ID = "call_id"
    const val EXTRA_CALL_ACTION = "call_action"   // "show" | "answer" | "decline"

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH_ALERTS, "Alerts", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Escalations, transfers, new conversations, drafts and order updates"
        })
        nm.createNotificationChannel(NotificationChannel(CH_MESSAGES, "Customer messages", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "SMS to the business number"
        })
        nm.createNotificationChannel(NotificationChannel(CH_UPDATES, "Team updates", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Chats released to Neema, the morning standup and system checks"
        })
        nm.createNotificationChannel(NotificationChannel(CH_CALLS, "Incoming calls", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "WhatsApp voice calls ringing the team"
        })
        nm.createNotificationChannel(NotificationChannel(CH_LIVE, "Live connection", NotificationManager.IMPORTANCE_MIN).apply {
            description = "Keeps Neema connected so alerts and calls arrive in the background"
            setShowBadge(false)
        })
    }

    /** POST_NOTIFICATIONS granted (Android 13+) and notifications not switched off for the app. */
    fun canPost(ctx: Context): Boolean =
        (Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
            runCatching { NotificationManagerCompat.from(ctx).areNotificationsEnabled() }.getOrDefault(true)

    fun openIntent(ctx: Context, requestCode: Int, extras: Intent.() -> Unit = {}): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            extras()
        }
        return PendingIntent.getActivity(ctx, requestCode, i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    fun post(ctx: Context, a: SystemAlert) {
        if (!canPost(ctx)) return
        val n = NotificationCompat.Builder(ctx, a.channel)
            .setSmallIcon(R.drawable.ic_stat_neema)
            .setColor(Brand.Amber.toArgb())
            .setContentTitle(a.title)
            .setContentText(a.body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(a.body))
            .setAutoCancel(true)
            .setPriority(a.priority)
            .setWhen(ke.co.bethanyhouse.neema.core.util.AppClock.now())
            .setShowWhen(true)
            .setGroup(GROUP_ALERTS)
            .setContentIntent(openIntent(ctx, a.id) {
                a.convKey?.let { putExtra(EXTRA_OPEN_CONV, it) }
                a.view?.let { putExtra(EXTRA_VIEW, it) }
                a.notificationId?.let { putExtra(EXTRA_NOTIFICATION, it) }
            })
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify(a.id, n) }
    }

    private fun postSummary(ctx: Context, count: Int, lines: List<String>) {
        if (!canPost(ctx)) return
        val style = NotificationCompat.InboxStyle().setSummaryText("$count alerts")
        lines.take(5).forEach { style.addLine(it) }
        val n = NotificationCompat.Builder(ctx, CH_ALERTS)
            .setSmallIcon(R.drawable.ic_stat_neema)
            .setColor(Brand.Amber.toArgb())
            .setContentTitle("$count Neema alerts")
            .setContentText(lines.firstOrNull() ?: "")
            .setStyle(style)
            .setGroup(GROUP_ALERTS)
            .setGroupSummary(true)
            // The children already alerted; the summary only gathers them.
            .setGroupAlertBehavior(NotificationCompat.GROUP_ALERT_CHILDREN)
            .setAutoCancel(true)
            .setContentIntent(openIntent(ctx, SUMMARY_ID))
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify(SUMMARY_ID, n) }
    }

    fun cancel(ctx: Context, id: Int) = runCatching { NotificationManagerCompat.from(ctx).cancel(id) }.let { }

    /** The real [AlertSink]. */
    fun sink(ctx: Context): AlertSink = object : AlertSink {
        override fun canPost() = canPost(ctx)
        override fun post(alert: SystemAlert) = post(ctx, alert)
        override fun cancel(id: Int) = cancel(ctx, id)
        override fun active(): Set<Int>? =
            runCatching { NotificationManagerCompat.from(ctx).activeNotifications.map { it.id }.toSet() }.getOrNull()
        override fun summary(count: Int, lines: List<String>) = postSummary(ctx, count, lines)
        override fun cancelSummary() = cancel(ctx, SUMMARY_ID)
    }
}
