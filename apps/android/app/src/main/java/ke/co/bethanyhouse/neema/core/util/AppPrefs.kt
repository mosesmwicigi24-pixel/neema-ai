package ke.co.bethanyhouse.neema.core.util

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * How Neema sounds on this device (Profile → Sounds & vibration).
 *
 * Mute silences messages and alerts — they still arrive, in the bell and the
 * tray — for an hour, eight hours, or until turned back on. Calls have their
 * own switches and are never silenced by mute: a missed customer is costly.
 */
data class AlertSettings(
    val messageSound: Boolean = true,
    val messageVibrate: Boolean = true,
    val callRing: Boolean = true,
    val callVibrate: Boolean = true,
    /** Messages are silent until this time (epoch ms): 0 = not muted, [FOREVER] = until turned back on. */
    val mutedUntil: Long = 0,
) {
    fun muted(now: Long): Boolean = mutedUntil > now
    /** A message landing at [now] beeps. */
    fun messageSoundAt(now: Long): Boolean = messageSound && !muted(now)
    /** A message landing at [now] vibrates. */
    fun messageVibrateAt(now: Long): Boolean = messageVibrate && !muted(now)

    companion object {
        const val FOREVER = Long.MAX_VALUE
    }
}

/** Small device-level preferences (not secrets). Features may add their own keys via [raw]. */
class AppPrefs(context: Context, override: android.content.SharedPreferences? = null) {
    val raw: android.content.SharedPreferences = override ?: context.getSharedPreferences("neema_prefs", Context.MODE_PRIVATE)

    private val _dark = MutableStateFlow(raw.getString("theme", "light") == "dark")
    val dark: StateFlow<Boolean> = _dark.asStateFlow()
    fun setDark(v: Boolean) { _dark.value = v; raw.edit().putString("theme", if (v) "dark" else "light").apply() }

    /** Keep the live connection (and notifications/incoming calls) running in the background. */
    private val _backgroundLive = MutableStateFlow(raw.getBoolean("background_live", true))
    val backgroundLive: StateFlow<Boolean> = _backgroundLive.asStateFlow()
    fun setBackgroundLive(v: Boolean) { _backgroundLive.value = v; raw.edit().putBoolean("background_live", v).apply() }

    private val _alerts = MutableStateFlow(
        AlertSettings(
            messageSound = raw.getBoolean("alert_message_sound", true),
            messageVibrate = raw.getBoolean("alert_message_vibrate", true),
            callRing = raw.getBoolean("alert_call_ring", true),
            callVibrate = raw.getBoolean("alert_call_vibrate", true),
            mutedUntil = raw.getLong("alert_muted_until", 0),
        ),
    )
    val alerts: StateFlow<AlertSettings> = _alerts.asStateFlow()

    fun setAlerts(next: AlertSettings) {
        _alerts.value = next
        raw.edit()
            .putBoolean("alert_message_sound", next.messageSound)
            .putBoolean("alert_message_vibrate", next.messageVibrate)
            .putBoolean("alert_call_ring", next.callRing)
            .putBoolean("alert_call_vibrate", next.callVibrate)
            .putLong("alert_muted_until", next.mutedUntil)
            .apply()
    }

    /** Mute messages for [ms] from [now]; null = until turned back on. */
    fun muteFor(ms: Long?, now: Long = AppClock.now()) =
        setAlerts(_alerts.value.copy(mutedUntil = ms?.let { now + it } ?: AlertSettings.FOREVER))

    fun unmute() = setAlerts(_alerts.value.copy(mutedUntil = 0))
}
