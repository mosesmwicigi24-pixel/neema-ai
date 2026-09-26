package ke.co.bethanyhouse.neema.testing

import android.content.SharedPreferences
import java.util.concurrent.ConcurrentHashMap

/** A working in-memory SharedPreferences for JVM tests (layoutlib's are stubs). */
class MemoryPrefs : SharedPreferences {
    private val map = ConcurrentHashMap<String, Any>()
    private val listeners = mutableSetOf<SharedPreferences.OnSharedPreferenceChangeListener>()

    override fun getAll(): Map<String, *> = HashMap(map)
    override fun getString(key: String, defValue: String?) = map[key] as? String ?: defValue
    @Suppress("UNCHECKED_CAST")
    override fun getStringSet(key: String, defValues: Set<String>?) = map[key] as? Set<String> ?: defValues
    override fun getInt(key: String, defValue: Int) = map[key] as? Int ?: defValue
    override fun getLong(key: String, defValue: Long) = map[key] as? Long ?: defValue
    override fun getFloat(key: String, defValue: Float) = map[key] as? Float ?: defValue
    override fun getBoolean(key: String, defValue: Boolean) = map[key] as? Boolean ?: defValue
    override fun contains(key: String) = map.containsKey(key)
    override fun registerOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener) { listeners += l }
    override fun unregisterOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener) { listeners -= l }

    override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
        private val puts = HashMap<String, Any?>()
        private var clear = false
        override fun putString(k: String, v: String?) = apply { puts[k] = v }
        override fun putStringSet(k: String, v: Set<String>?) = apply { puts[k] = v }
        override fun putInt(k: String, v: Int) = apply { puts[k] = v }
        override fun putLong(k: String, v: Long) = apply { puts[k] = v }
        override fun putFloat(k: String, v: Float) = apply { puts[k] = v }
        override fun putBoolean(k: String, v: Boolean) = apply { puts[k] = v }
        override fun remove(k: String) = apply { puts[k] = null }
        override fun clear() = apply { clear = true }
        override fun commit(): Boolean { apply(); return true }
        override fun apply() {
            if (clear) map.clear()
            puts.forEach { (k, v) -> if (v == null) map.remove(k) else map[k] = v }
        }
    }
}
