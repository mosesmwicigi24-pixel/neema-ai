package ke.co.bethanyhouse.neema.settings

import ke.co.bethanyhouse.neema.core.model.CallHoliday
import ke.co.bethanyhouse.neema.core.model.CallHours
import ke.co.bethanyhouse.neema.core.model.CallHoursSlot
import ke.co.bethanyhouse.neema.core.model.CallVoicemail
import ke.co.bethanyhouse.neema.core.model.CallingSettings
import ke.co.bethanyhouse.neema.core.model.CallingSettingsSaved
import ke.co.bethanyhouse.neema.core.model.PermissionTemplate
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.settings.CallingSettingsApi
import ke.co.bethanyhouse.neema.feature.settings.CallingSettingsModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Settings → WhatsApp calling: a save sends only what the admin changed
 * (the server merges call_hours / voicemail and re-sends the holidays),
 * nothing when nothing changed, nothing while a field is wrong — and a
 * refusal is said in the server's words.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallingSettingsModelTest {
    private val current = CallingSettings(
        status = "ENABLED", callIconVisibility = "DEFAULT", callbackPermissionStatus = "DISABLED",
        callHours = CallHours(
            "ENABLED", "Africa/Nairobi",
            listOf(CallHoursSlot("MONDAY", "0800", "1700"), CallHoursSlot("TUESDAY", "0800", "1700")),
            listOf(CallHoliday("2026-12-25", "0000", "2359")),
        ),
        voicemail = CallVoicemail("DISABLED", listOf("TIMEOUT"), 15),
    )

    private inner class FakeApi : CallingSettingsApi {
        val sent = mutableListOf<JsonObject>()
        var saveError: Exception? = null
        var reads = 0
        var template = PermissionTemplate(configured = false, wabaConfigured = true, exists = false)
        var created = 0
        override suspend fun settings(): CallingSettings { reads++; return current }
        override suspend fun save(change: JsonObject): CallingSettingsSaved {
            saveError?.let { throw it }
            sent += change
            return CallingSettingsSaved(true, null)
        }
        override suspend fun template() = template
        override suspend fun createTemplate() { created++; template = template.copy(configured = true, exists = true, status = "pending", name = "neema_call_permission", language = "en") }
    }

    private fun rig(block: suspend TestScope.(CallingSettingsModel, FakeApi, MutableSharedFlow<JsonObject>) -> Unit) = runTest {
        val api = FakeApi()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 8)
        val m = CallingSettingsModel(api, backgroundScope, frames)
        m.start(); runCurrent()
        block(m, api, frames)
    }

    @Test fun savesOnlyTheFieldsThatChanged() = rig { m, api, _ ->
        assertEquals(current, m.ui.value.loaded)
        assertFalse("nothing changed: nothing to save", m.ui.value.dirty)
        m.save(); runCurrent()
        assertTrue(api.sent.isEmpty())

        m.edit { it.copy(callbackPermissionStatus = "ENABLED") }
        assertTrue(m.ui.value.dirty)
        m.save(); runCurrent()
        assertEquals("""{"callback_permission_status":"ENABLED"}""", api.sent.last().toString())
        assertTrue(m.ui.value.saved)
        assertFalse("saved: the draft is what WhatsApp has now", m.ui.value.dirty)

        m.edit { it.copy(voicemail = it.voicemail!!.copy(status = "ENABLED", timeoutSeconds = 20)) }
        m.save(); runCurrent()
        assertEquals("""{"voicemail":{"status":"ENABLED","timeout_seconds":20}}""", api.sent.last().toString())

        // A holiday added: only the schedule goes (the server keeps the weekly hours).
        m.edit { it.copy(callHours = it.callHours!!.copy(holidays = it.callHours!!.holidays + CallHoliday("2027-01-01", "0000", "2359"))) }
        m.save(); runCurrent()
        val hours = api.sent.last()["call_hours"] as JsonObject
        assertEquals(setOf("holiday_schedule"), hours.keys)
        assertEquals(1, api.sent.last().size)

        m.edit { it.copy(callIconVisibility = "DISABLE_ALL") }
        m.edit { it.copy(callIconVisibility = "DEFAULT") }
        assertFalse("changed and changed back: nothing to send", m.ui.value.dirty)
    }

    @Test fun aWrongFieldIsSaidAndNothingIsSent() = rig { m, api, _ ->
        m.edit { it.copy(voicemail = it.voicemail!!.copy(timeoutSeconds = 45)) }
        m.edit { it.copy(callHours = it.callHours!!.copy(weekly = listOf(CallHoursSlot("MONDAY", "1700", "0800")))) }
        m.save(); runCurrent()
        assertTrue(api.sent.isEmpty())
        assertEquals("Between 0 and 30 seconds.", m.ui.value.fieldErrors["voicemail.timeout"])
        assertEquals("Closing must be after opening.", m.ui.value.fieldErrors["hours.MONDAY"])
        // Editing clears the marks; a good value goes.
        m.edit { it.copy(voicemail = it.voicemail!!.copy(timeoutSeconds = 30), callHours = current.callHours) }
        assertTrue(m.ui.value.fieldErrors.isEmpty())
        m.save(); runCurrent()
        assertEquals("""{"voicemail":{"timeout_seconds":30}}""", api.sent.single().toString())
    }

    @Test fun aRefusalIsSaidInTheServersWordsAndTheEditsStay() = rig { m, api, _ ->
        api.saveError = ApiException(503, "POST", "/admin/calls/settings",
            """{"detail":"Couldn't read the current calling settings from WhatsApp, so nothing was changed (the holiday schedule would be lost) — try again.","code":"meta_unavailable","action":"retry"}""")
        m.edit { it.copy(callbackPermissionStatus = "ENABLED") }
        m.save(); runCurrent()
        assertTrue(m.ui.value.saveError!!.startsWith("Couldn't read the current calling settings from WhatsApp"))
        assertTrue("the edit is kept for another try", m.ui.value.dirty)
        assertFalse(m.ui.value.saving)
    }

    @Test fun liveSettingsFramesReloadUnlessEditsAreUnsaved() = rig { m, api, frames ->
        assertEquals(1, api.reads)
        frames.emit(NeemaJson.parseToJsonElement("""{"type":"call_settings","value":{},"at":"2026-09-27T10:00:00Z"}""") as JsonObject); runCurrent()
        assertEquals(2, api.reads)
        m.edit { it.copy(callbackPermissionStatus = "ENABLED") }
        frames.emit(NeemaJson.parseToJsonElement("""{"type":"call_settings","value":{}}""") as JsonObject); runCurrent()
        assertEquals("an unsaved edit is never thrown away", 2, api.reads)
        assertTrue(m.ui.value.changedElsewhere)
    }

    @Test fun theTemplateCanBeCreated() = rig { m, api, _ ->
        assertEquals(false, m.ui.value.template?.exists)
        m.createTemplate(); runCurrent()
        assertEquals(1, api.created)
        assertEquals("pending", m.ui.value.template?.status)
        assertNull(m.ui.value.templateError)
    }
}
