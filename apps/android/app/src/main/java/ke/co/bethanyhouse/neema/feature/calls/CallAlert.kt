package ke.co.bethanyhouse.neema.feature.calls

import android.content.Context
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.Person
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
 * The actions open MainActivity with [Notifier.EXTRA_CALL_ACTION], which
 * forwards to [CallManager.handleIntent] (the foundation has no broadcast
 * receiver for calls, and answering needs the UI for the mic permission).
 */
internal class CallAlert(private val context: Context, private val scope: CoroutineScope) {
    private var ringtone: Ringtone? = null
    private var loopJob: Job? = null
    private var vibrating = false

    fun startRinging() {
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

    fun stopRinging() {
        loopJob?.cancel(); loopJob = null
        runCatching { ringtone?.stop() }
        ringtone = null
        if (vibrating) { runCatching { vibrator()?.cancel() }; vibrating = false }
    }

    private fun vibrator(): Vibrator? =
        if (Build.VERSION.SDK_INT >= 31) context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        else @Suppress("DEPRECATION") context.getSystemService(Vibrator::class.java)

    /** The incoming-call notification (only when the app is in the background). */
    fun postIncoming(callId: String, who: String, from: String?) {
        if (!Notifier.canPost(context)) return
        fun action(kind: String, req: Int) = Notifier.openIntent(context, req) {
            putExtra(Notifier.EXTRA_CALL_ACTION, kind)
            putExtra(Notifier.EXTRA_CALL_ID, callId)
        }
        val show = action("show", REQ_SHOW)
        val answer = action("answer", REQ_ANSWER)
        val decline = action("decline", REQ_DECLINE)
        val base = NotificationCompat.Builder(context, Notifier.CH_CALLS)
            .setSmallIcon(R.drawable.ic_stat_neema)
            .setContentTitle(who)
            .setContentText(if (from != null) "Incoming WhatsApp call · +$from" else "Incoming WhatsApp call")
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOngoing(true)
            .setAutoCancel(false)
            .setOnlyAlertOnce(true)
            .setContentIntent(show)
            .setFullScreenIntent(show, true)
        // CallStyle gives the system's call UI; fall back to plain actions if the
        // platform refuses it (it validates the full-screen intent on API 31+).
        val n = runCatching {
            base.setStyle(
                NotificationCompat.CallStyle.forIncomingCall(Person.Builder().setName(who).setImportant(true).build(), decline, answer),
            ).build()
        }.getOrElse {
            base.setStyle(null)
                .addAction(0, "Decline", decline)
                .addAction(0, "Answer", answer)
                .build()
        }
        runCatching { NotificationManagerCompat.from(context).notify(NOTIF_ID, n) }
    }

    fun cancelIncoming() { runCatching { NotificationManagerCompat.from(context).cancel(NOTIF_ID) } }

    companion object {
        const val NOTIF_ID = 2001
        private const val REQ_SHOW = 2101
        private const val REQ_ANSWER = 2102
        private const val REQ_DECLINE = 2103
    }
}
