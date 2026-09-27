package ke.co.bethanyhouse.neema.feature.settings

import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.model.CallHoliday
import ke.co.bethanyhouse.neema.core.model.CallHours
import ke.co.bethanyhouse.neema.core.model.CallHoursSlot
import ke.co.bethanyhouse.neema.core.model.CallVoicemail
import ke.co.bethanyhouse.neema.core.model.CallingSettings
import ke.co.bethanyhouse.neema.core.model.CallingSettingsSaved
import ke.co.bethanyhouse.neema.core.model.PermissionTemplate
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.ws.str
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** The routes the "WhatsApp calling" card uses (manage_settings) — an interface so the rules run on the JVM. */
interface CallingSettingsApi {
    suspend fun settings(): CallingSettings
    suspend fun save(change: JsonObject): CallingSettingsSaved
    suspend fun template(): PermissionTemplate
    suspend fun createTemplate()
}

class NeemaCallingSettingsApi(private val api: NeemaApi) : CallingSettingsApi {
    override suspend fun settings() = api.calls.settings()
    override suspend fun save(change: JsonObject) = api.calls.saveSettings(change)
    override suspend fun template() = api.calls.permissionTemplate()
    override suspend fun createTemplate() { api.calls.createPermissionTemplate() }
}

/** The card's state: what WhatsApp has ([loaded]), what the admin is changing ([draft]), and how saving went. */
data class CallingSettingsUi(
    val loaded: CallingSettings? = null,
    val draft: CallingSettings? = null,
    val loading: Boolean = false,
    val loadError: String? = null,
    val saving: Boolean = false,
    /** Why the last save failed (the server's sentence). */
    val saveError: String? = null,
    /** "Saved — …" after a save went through. */
    val saved: Boolean = false,
    /** Field → what is wrong with it (checked before anything is sent). */
    val fieldErrors: Map<String, String> = emptyMap(),
    /** WhatsApp said the settings changed (`call_settings`) while edits were unsaved. */
    val changedElsewhere: Boolean = false,
    val template: PermissionTemplate? = null,
    val templateError: String? = null,
    val templateBusy: Boolean = false,
) {
    val dirty: Boolean get() = loaded != null && draft != null && CallingSettingsModel.changes(loaded, draft).isNotEmpty()
}

/**
 * Settings → WhatsApp calling (CALLING_UX.md §2.1): the number's calling
 * settings as WhatsApp holds them — callback permission, the call icon,
 * voicemail, weekly call hours and holidays, Meta's restrictions (read only)
 * — plus the call-request template used outside the 24 h window.
 *
 * A save sends ONLY the fields the admin changed (the server merges
 * call_hours / voicemail over the current ones and always re-sends the
 * holiday schedule); nothing is sent when nothing changed. Changes can take
 * up to 7 days to reach customers' phones.
 */
class CallingSettingsModel(
    private val api: CallingSettingsApi,
    private val scope: CoroutineScope,
    /** Live frames: `call_settings` reloads the card. */
    private val events: Flow<JsonObject> = emptyFlow(),
) {
    private val _ui = MutableStateFlow(CallingSettingsUi())
    val ui: StateFlow<CallingSettingsUi> = _ui.asStateFlow()
    private var started = false
    private var loadJob: Job? = null

    /** The card came on screen: read once, then follow `call_settings`. */
    fun start() {
        if (started) return
        started = true
        load()
        loadTemplate()
        scope.launch {
            events.collect { e ->
                if (e.str("type") != "call_settings") return@collect
                if (_ui.value.dirty) _ui.update { it.copy(changedElsewhere = true) } else load()
            }
        }
    }

    /** Pull-to-refresh on Settings: read again, unless the admin has unsaved changes. */
    fun refreshIfShown() { if (started && !_ui.value.dirty) { load(); loadTemplate() } }

    fun load() {
        if (loadJob?.isActive == true) return
        _ui.update { it.copy(loading = true, loadError = null) }
        loadJob = scope.launch {
            try {
                val s = api.settings()
                _ui.update { it.copy(loaded = s, draft = s, loading = false, changedElsewhere = false, fieldErrors = emptyMap()) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update { it.copy(loading = false, loadError = reason(e, "Couldn't read the calling settings from WhatsApp.")) }
            }
        }
    }

    fun loadTemplate() {
        scope.launch {
            try {
                val t = api.template()
                _ui.update { it.copy(template = t, templateError = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update { it.copy(templateError = reason(e, "Couldn't check the call-request template.")) }
            }
        }
    }

    /** Change the draft (a toggle, a field). */
    fun edit(change: (CallingSettings) -> CallingSettings) {
        _ui.update { u -> u.draft?.let { u.copy(draft = change(it), saved = false, saveError = null, fieldErrors = emptyMap()) } ?: u }
    }

    fun discard() { _ui.update { it.copy(draft = it.loaded, fieldErrors = emptyMap(), saveError = null, changedElsewhere = false) } }

    /** Save what changed — and only that. */
    fun save() {
        val u = _ui.value
        val loaded = u.loaded ?: return
        val draft = u.draft ?: return
        if (u.saving) return
        val errors = validate(draft)
        if (errors.isNotEmpty()) { _ui.update { it.copy(fieldErrors = errors) }; return }
        val change = changes(loaded, draft)
        if (change.isEmpty()) return
        _ui.update { it.copy(saving = true, saveError = null, saved = false) }
        scope.launch {
            try {
                val r = api.save(change)
                val fresh = r.settings ?: draft
                _ui.update { it.copy(saving = false, saved = true, loaded = fresh, draft = fresh, changedElsewhere = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update { it.copy(saving = false, saveError = reason(e, "Couldn't save the calling settings.")) }
            }
        }
    }

    /** "Create template": the server's default wording; Meta reviews it before requests use it. */
    fun createTemplate() {
        if (_ui.value.templateBusy) return
        _ui.update { it.copy(templateBusy = true, templateError = null) }
        scope.launch {
            try {
                api.createTemplate()
                val t = runCatching { api.template() }.getOrNull()
                _ui.update { it.copy(templateBusy = false, template = t ?: it.template?.copy(configured = true, exists = true, status = "pending")) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update { it.copy(templateBusy = false, templateError = reason(e, "Couldn't create the template.")) }
            }
        }
    }

    companion object {
        val DAYS = listOf("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")

        /**
         * The body of POST /calls/settings: only what differs between what
         * WhatsApp has and the draft. call_hours / voicemail carry only their
         * changed keys (the server merges them over the current ones).
         */
        fun changes(loaded: CallingSettings, draft: CallingSettings): JsonObject = buildJsonObject {
            if (draft.callbackPermissionStatus != loaded.callbackPermissionStatus && draft.callbackPermissionStatus != null) {
                put("callback_permission_status", draft.callbackPermissionStatus)
            }
            if (draft.callIconVisibility != loaded.callIconVisibility && draft.callIconVisibility != null) {
                put("call_icon_visibility", draft.callIconVisibility)
            }
            val lv = loaded.voicemail ?: CallVoicemail()
            val dv = draft.voicemail ?: CallVoicemail()
            val vm = buildJsonObject {
                if (dv.status != lv.status && dv.status != null) put("status", dv.status)
                if (dv.timeoutSeconds != lv.timeoutSeconds && dv.timeoutSeconds != null) put("timeout_seconds", dv.timeoutSeconds)
            }
            if (vm.isNotEmpty()) put("voicemail", vm)
            val lh = loaded.callHours ?: CallHours()
            val dh = draft.callHours ?: CallHours()
            val hours = buildJsonObject {
                if (dh.status != lh.status && dh.status != null) put("status", dh.status)
                if (dh.timezoneId != lh.timezoneId && dh.timezoneId != null) put("timezone_id", dh.timezoneId)
                if (dh.weekly != lh.weekly) put("weekly_operating_hours", NeemaJson.encodeToJsonElement(ListSerializer(CallHoursSlot.serializer()), dh.weekly))
                if (dh.holidays != lh.holidays) put("holiday_schedule", NeemaJson.encodeToJsonElement(ListSerializer(CallHoliday.serializer()), dh.holidays))
            }
            if (hours.isNotEmpty()) put("call_hours", hours)
        }

        private val HHMM = Regex("^([01]\\d|2[0-3])[0-5]\\d$")
        private val DATE = Regex("^\\d{4}-\\d{2}-\\d{2}$")

        /** What would be refused, by field — said next to the field before anything is sent. */
        fun validate(d: CallingSettings): Map<String, String> {
            val out = LinkedHashMap<String, String>()
            d.voicemail?.timeoutSeconds?.let { if (it !in 0..30) out["voicemail.timeout"] = "Between 0 and 30 seconds." }
            val h = d.callHours ?: return out
            h.weekly.forEach { s ->
                val key = "hours.${s.dayOfWeek}"
                val o = s.openTime.orEmpty(); val c = s.closeTime.orEmpty()
                when {
                    !HHMM.matches(o) || !HHMM.matches(c) -> out[key] = "Use 24-hour times like 09:00."
                    o >= c -> out[key] = "Closing must be after opening."
                }
            }
            if (h.holidays.size > 20) out["holidays"] = "At most 20 holidays."
            h.holidays.forEachIndexed { i, x ->
                val key = "holiday.$i"
                when {
                    !DATE.matches(x.date.orEmpty()) -> out[key] = "Use a date like 2026-12-25."
                    !HHMM.matches(x.startTime.orEmpty()) || !HHMM.matches(x.endTime.orEmpty()) -> out[key] = "Use 24-hour times like 09:00."
                    x.startTime.orEmpty() >= x.endTime.orEmpty() -> out[key] = "The end must be after the start."
                }
            }
            if (h.status == "ENABLED" && h.timezoneId.isNullOrBlank()) out["hours.timezone"] = "Choose a time zone (e.g. Africa/Nairobi)."
            return out
        }

        /** "0900" ⇄ "09:00" for the time fields. */
        fun showTime(hhmm: String?): String = hhmm?.takeIf { it.length == 4 }?.let { "${it.take(2)}:${it.drop(2)}" } ?: hhmm.orEmpty()
        fun readTime(text: String): String = text.filter { it.isDigit() }.take(4).let { if (it.length == 3) "0$it" else it }

        /** The server's sentence for a refusal (its `detail`), else plain words for the failure. */
        fun reason(e: Throwable, fallback: String): String {
            val a = e as? ApiException ?: return fallback
            return when {
                a.status == 0 && a.timedOut -> "The server took too long — try again."
                a.status == 0 -> "No connection — try again."
                a.status == 403 -> "Only admins can change calling settings."
                else -> a.detail.trim().takeIf { it.isNotEmpty() && !ApiException.looksLikeHtml(it) && it.length <= 300 } ?: fallback
            }
        }

        /** A restriction as Meta sends it (shape undocumented), in words. */
        fun restrictionWords(e: kotlinx.serialization.json.JsonElement): String = when (e) {
            is JsonPrimitive -> e.content.replace('_', ' ').lowercase().replaceFirstChar { it.uppercase() }
            is JsonObject -> listOfNotNull(
                (e["type"] ?: e["restriction_type"] ?: e["reason"])?.let { (it as? JsonPrimitive)?.content }
                    ?.replace('_', ' ')?.lowercase()?.replaceFirstChar { it.uppercase() },
                (e["description"] ?: e["message"])?.let { (it as? JsonPrimitive)?.content },
                (e["expiration"] ?: e["expiration_time"] ?: e["expires_at"])?.let { (it as? JsonPrimitive)?.content }?.let { "until $it" },
            ).joinToString(" — ").ifEmpty { e.toString() }
            else -> e.toString()
        }
    }
}
