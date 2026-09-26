package ke.co.bethanyhouse.neema.core.util

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

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
}
