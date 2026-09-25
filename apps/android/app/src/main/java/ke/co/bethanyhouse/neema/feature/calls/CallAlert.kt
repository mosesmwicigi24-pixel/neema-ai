package ke.co.bethanyhouse.neema.feature.calls

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.Person
import androidx.core.content.ContextCompat
import ke.co.bethanyhouse.neema.R
import ke.co.bethanyhouse.neema.core.notify.Notifier
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * The ringing side of the softphone: the device ringtone + vibration while a
 * call rings (the web generates a 480 Hz beep every 2.2s instead), and — when
 * the app isn't in the foreground — a high-priority incoming-call
 * notification with a full-screen intent and Answer / Decline actions.
 *
 * - Answer opens MainActivity with [Notifier.EXTRA_CALL_ACTION] = "answer",
 *   which forwards to [CallManager.handleIntent]: answering needs the UI (the
 *   card, and the mic prompt when it hasn't been allowed yet).
 * - Decline is a broadcast to a receiver this class registers at runtime (not
 *   exported), so declining doesn't pull the app up — the web's Decline just
 *   ends the call. If the receiver can't be registered it falls back to the
 *   activity route.
 * - Android 14+ only lets an app use full-screen intents when the user allows
 *   it ([canUseFullScreenIntent]). Without it the system shows the call as a
 *   heads-up notification (still ringing and vibrating) instead of taking over
 *   the lock screen; the Calls screen offers the setting ([CallReadinessBanner]).
 * - CallStyle is validated by the system (it needs a full-screen intent or a
 *   foreground service); if the platform refuses it, the plain notification
 *   with Answer / Decline actions goes up instead.
 */
internal class CallAlert(private val context: Context, private val scope: CoroutineScope) : CallRinger {
    private var ringtone: Ringtone? = null
    private var loopJob: Job? = null
    private var vibrating = false

    /** Set by [CallManager]: the notification's Decline was tapped. */
    var onDecline: ((callId: String?) -> Unit)? = null

    private val declineReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            cancelIncoming()
            onDecline?.invoke(intent.getStringExtra(Notifier.EXTRA_CALL_ID))
        }
    }
    private var receiverRegistered = false

    override fun startRinging() {
        stopRinging()
        runCatching {
            val uri = RingtoneManager.getActualDefaultRingtoneUri(context, RingtoneManager.TYPE_RINGTONE)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            ringtone = RingtoneManager.getRingtone(context, uri)?.apply {
                audioAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
                if (Build.VERSION.SDK_INT >= 28) isLooping = true
                play()
            }
        }
        // API 26/27 have no looping ringtone: restart it when it finishes.
        if (Build.VERSION.SDK_INT < 28) loopJob = scope.launch(Dispatchers.Main) {
            while (isActive) {
                delay(1000)
                ringtone?.let { if (!it.isPlaying) runCatching { it.play() } }
            }
        }
        runCatching {
            vibrator()?.let {
                it.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 800, 1400), 0))
                vibrating = true
            }
        }
    }

    override fun stopRinging() {
        loopJob?.cancel(); loopJob = null
        runCatching { ringtone?.stop() }
        ringtone = null
        if (vibrating) { runCatching { vibrator()?.cancel() }; vibrating = false }
    }

    private fun vibrator(): Vibrator? =
        if (Build.VERSION.SDK_INT >= 31) context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        else @Suppress("DEPRECATION") context.getSystemService(Vibrator::class.java)

    private fun ensureDeclineReceiver(): Boolean {
        if (receiverRegistered) return true
        receiverRegistered = runCatching {
            ContextCompat.registerReceiver(
                context.applicationContext, declineReceiver, IntentFilter(ACTION_DECLINE), ContextCompat.RECEIVER_NOT_EXPORTED,
            )
        }.isSuccess
        return receiverRegistered
    }

    private fun activityAction(kind: String, callId: String, req: Int): PendingIntent = Notifier.openIntent(context, req) {
        putExtra(Notifier.EXTRA_CALL_ACTION, kind)
        putExtra(Notifier.EXTRA_CALL_ID, callId)
    }

    private fun declineAction(callId: String): PendingIntent =
        if (ensureDeclineReceiver()) PendingIntent.getBroadcast(
            context, REQ_DECLINE,
            Intent(ACTION_DECLINE).setPackage(context.packageName).putExtra(Notifier.EXTRA_CALL_ID, callId),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        else activityAction("decline", callId, REQ_DECLINE)

    /** The incoming-call notification (only when the app is in the background). */
    override fun postIncoming(callId: String, who: String, from: String?) {
        if (!Notifier.canPost(context)) return
        val show = activityAction("show", callId, REQ_SHOW)
        val answer = activityAction("answer", callId, REQ_ANSWER)
        val decline = declineAction(callId)
        fun base() = NotificationCompat.Builder(context, Notifier.CH_CALLS)
            .setSmallIcon(R.drawable.ic_stat_neema)
            .setContentTitle(who)
            .setContentText(if (from != null) "Incoming WhatsApp call · +$from" else "Incoming WhatsApp call")
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOngoing(true)
            .setAutoCancel(false)
            .setOnlyAlertOnce(true)
            // The server marks a call still "ringing" after 2 min as missed.
            .setTimeoutAfter(RING_TIMEOUT_MS)
            .setContentIntent(show)
            // On Android 14+ without the full-screen permission the system
            // drops this and shows a heads-up notification instead.
            .setFullScreenIntent(show, true)
        val nm = NotificationManagerCompat.from(context)
        val styled = runCatching {
            nm.notify(
                NOTIF_ID,
                base().setStyle(
                    NotificationCompat.CallStyle.forIncomingCall(
                        Person.Builder().setName(who).setImportant(true).build(), decline, answer,
                    ),
                ).build(),
            )
        }
        if (styled.isFailure) {
            Log.w("CallAlert", "CallStyle refused; posting the plain call notification", styled.exceptionOrNull())
            runCatching {
                nm.notify(
                    NOTIF_ID,
                    base().addAction(0, "Decline", decline).addAction(0, "Answer", answer).build(),
                )
            }
        }
    }

    override fun cancelIncoming() { runCatching { NotificationManagerCompat.from(context).cancel(NOTIF_ID) } }

    companion object {
        const val NOTIF_ID = 2001
        private const val REQ_SHOW = 2101
        private const val REQ_ANSWER = 2102
        private const val REQ_DECLINE = 2103
        private const val RING_TIMEOUT_MS = 120_000L
        private const val ACTION_DECLINE = "ke.co.bethanyhouse.neema.action.DECLINE_CALL"
    }
}

/** What a call needs from the system to ring this phone like the web's take-over card. */
data class CallReadiness(
    /** Notifications allowed (app-wide and the "Incoming calls" channel): calls ring in the background. */
    val notifications: Boolean = true,
    /** Android 14+: full-screen intents allowed, so a call takes over the lock screen. */
    val fullScreen: Boolean = true,
) {
    val ready: Boolean get() = notifications && fullScreen

    companion object {
        fun of(ctx: Context): CallReadiness = CallReadiness(
            notifications = runCatching {
                val nm = NotificationManagerCompat.from(ctx)
                Notifier.canPost(ctx) && nm.areNotificationsEnabled() &&
                    nm.getNotificationChannelCompat(Notifier.CH_CALLS)?.importance != NotificationManagerCompat.IMPORTANCE_NONE
            }.getOrDefault(true),
            fullScreen = canUseFullScreenIntent(ctx),
        )
    }
}

/** NotificationManager.canUseFullScreenIntent (Android 14+); always true before. */
fun canUseFullScreenIntent(ctx: Context): Boolean =
    Build.VERSION.SDK_INT < 34 ||
        runCatching { ctx.getSystemService(NotificationManager::class.java)?.canUseFullScreenIntent() }.getOrNull() ?: true

/** The system page where the user allows full-screen notifications for Neema (Android 14+). */
fun fullScreenIntentSettings(ctx: Context): Intent =
    if (Build.VERSION.SDK_INT >= 34) Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:${ctx.packageName}"))
    else notificationSettings(ctx)

/** Neema's notification settings page. */
fun notificationSettings(ctx: Context): Intent =
    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
