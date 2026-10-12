import Foundation
import XCTest
@testable import NeemaCore

/// Settings → WhatsApp calling: a save sends only what the admin changed
/// (the server merges call_hours / voicemail and re-sends the holidays),
/// nothing when nothing changed, nothing while a field is wrong — and a
/// refusal is said in the server's words (Android `CallingSettingsModelTest`).
@MainActor
final class CallingSettingsModelTests: XCTestCase {
    private let current = CallingSettings(
        status: "ENABLED", callIconVisibility: "DEFAULT", callbackPermissionStatus: "DISABLED",
        callHours: CallHours(
            status: "ENABLED", timezoneId: "Africa/Nairobi",
            weekly: [CallHoursSlot(dayOfWeek: "MONDAY", openTime: "0800", closeTime: "1700"), CallHoursSlot(dayOfWeek: "TUESDAY", openTime: "0800", closeTime: "1700")],
            holidays: [CallHoliday(date: "2026-12-25", startTime: "0000", endTime: "2359")]
        ),
        voicemail: CallVoicemail(status: "DISABLED", triggers: ["TIMEOUT"], timeoutSeconds: 15)
    )

    private final class FakeApi: CallingSettingsApi, @unchecked Sendable {
        let lock = NSLock()
        var current: CallingSettings
        var sent: [JSONValue] = []
        var saveError: Error?
        var reads = 0
        var template = PermissionTemplate(configured: false, wabaConfigured: true, exists: false)
        var created = 0
        init(_ c: CallingSettings) { current = c }
        func settings() async throws -> CallingSettings { lock.sync { reads += 1 }; return current }
        func save(_ change: JSONValue) async throws -> CallingSettingsSaved {
            if let e = saveError { throw e }
            lock.sync { sent.append(change) }
            return CallingSettingsSaved(ok: true, settings: nil)
        }
        func template() async throws -> PermissionTemplate { template }
        func createTemplate() async throws {
            created += 1
            template.configured = true; template.exists = true; template.status = "pending"; template.name = "neema_call_permission"; template.language = "en"
        }
    }

    private var models: [CallingSettingsModel] = []

    override func tearDown() async throws {
        for m in models { m.close() }
        models = []
        try await super.tearDown()
    }

    private func rig() async -> (CallingSettingsModel, FakeApi, Signal<JSONValue>) {
        let api = FakeApi(current)
        let frames = Signal<JSONValue>(buffer: 8)
        let m = CallingSettingsModel(api: api, events: frames)
        models.append(m)
        m.start()
        await settledModel(m)
        return (m, api, frames)
    }

    private func settledModel(_ m: CallingSettingsModel) async {
        await drain()
        _ = await eventually(timeout: 5) { !m.ui.loading && !m.ui.saving && !m.ui.templateBusy }
        await drain()
    }

    private func el(_ s: String) -> JSONValue? { JSONValue.parse(s) }

    func testSavesOnlyTheFieldsThatChanged() async {
        let (m, api, _) = await rig()
        XCTAssertEqual(m.ui.loaded, current)
        XCTAssertFalse(m.ui.dirty, "nothing changed: nothing to save")
        m.save()
        await settledModel(m)
        XCTAssertTrue(api.sent.isEmpty)

        m.edit { var d = $0; d.callbackPermissionStatus = "ENABLED"; return d }
        XCTAssertTrue(m.ui.dirty)
        m.save()
        await settledModel(m)
        XCTAssertEqual(api.sent.last, el(#"{"callback_permission_status":"ENABLED"}"#))
        XCTAssertTrue(m.ui.saved)
        XCTAssertFalse(m.ui.dirty, "saved: the draft is what WhatsApp has now")

        m.edit { var d = $0; d.voicemail?.status = "ENABLED"; d.voicemail?.timeoutSeconds = 20; return d }
        m.save()
        await settledModel(m)
        XCTAssertEqual(api.sent.last, el(#"{"voicemail":{"status":"ENABLED","timeout_seconds":20}}"#))

        // A holiday added: only the schedule goes (the server keeps the weekly hours).
        m.edit { var d = $0; d.callHours?.holidays.append(CallHoliday(date: "2027-01-01", startTime: "0000", endTime: "2359")); return d }
        m.save()
        await settledModel(m)
        let hours = api.sent.last?["call_hours"]?.objectValue ?? [:]
        XCTAssertEqual(Set(hours.keys), ["holiday_schedule"])
        XCTAssertEqual(api.sent.last?.objectValue?.count, 1)
        XCTAssertEqual(hours["holiday_schedule"], el(#"[{"date":"2026-12-25","start_time":"0000","end_time":"2359"},{"date":"2027-01-01","start_time":"0000","end_time":"2359"}]"#))

        m.edit { var d = $0; d.callIconVisibility = "DISABLE_ALL"; return d }
        m.edit { var d = $0; d.callIconVisibility = "DEFAULT"; return d }
        XCTAssertFalse(m.ui.dirty, "changed and changed back: nothing to send")
    }

    func testAWrongFieldIsSaidAndNothingIsSent() async {
        let (m, api, _) = await rig()
        m.edit { var d = $0; d.voicemail?.timeoutSeconds = 45; return d }
        m.edit { var d = $0; d.callHours?.weekly = [CallHoursSlot(dayOfWeek: "MONDAY", openTime: "1700", closeTime: "0800")]; return d }
        m.save()
        await settledModel(m)
        XCTAssertTrue(api.sent.isEmpty)
        XCTAssertEqual(m.ui.fieldErrors["voicemail.timeout"], "Between 0 and 30 seconds.")
        XCTAssertEqual(m.ui.fieldErrors["hours.MONDAY"], "Closing must be after opening.")
        // Editing clears the marks; a good value goes.
        let hours = current.callHours
        m.edit { var d = $0; d.voicemail?.timeoutSeconds = 30; d.callHours = hours; return d }
        XCTAssertTrue(m.ui.fieldErrors.isEmpty)
        m.save()
        await settledModel(m)
        XCTAssertEqual(api.sent.count, 1)
        XCTAssertEqual(api.sent.first, el(#"{"voicemail":{"timeout_seconds":30}}"#))
    }

    func testARefusalIsSaidInTheServersWordsAndTheEditsStay() async {
        let (m, api, _) = await rig()
        api.saveError = ApiError(status: 503, method: "POST", path: "/admin/calls/settings",
            body: #"{"detail":"Couldn't read the current calling settings from WhatsApp, so nothing was changed (the holiday schedule would be lost) — try again.","code":"meta_unavailable","action":"retry"}"#)
        m.edit { var d = $0; d.callbackPermissionStatus = "ENABLED"; return d }
        m.save()
        await settledModel(m)
        XCTAssertTrue(m.ui.saveError?.hasPrefix("Couldn't read the current calling settings from WhatsApp") == true, m.ui.saveError ?? "nil")
        XCTAssertTrue(m.ui.dirty, "the edit is kept for another try")
        XCTAssertFalse(m.ui.saving)
    }

    func testLiveSettingsFramesReloadUnlessEditsAreUnsaved() async {
        let (m, api, frames) = await rig()
        XCTAssertEqual(api.reads, 1)
        frames.emit(el(#"{"type":"call_settings","value":{},"at":"2026-09-27T10:00:00Z"}"#)!)
        await settledModel(m)
        _ = await eventually { api.reads == 2 }
        XCTAssertEqual(api.reads, 2)
        m.edit { var d = $0; d.callbackPermissionStatus = "ENABLED"; return d }
        frames.emit(el(#"{"type":"call_settings","value":{}}"#)!)
        await settledModel(m)
        XCTAssertEqual(api.reads, 2, "an unsaved edit is never thrown away")
        XCTAssertTrue(m.ui.changedElsewhere)
        // Other frames are not the card's business.
        frames.emit(el(#"{"type":"message","value":{}}"#)!)
        await settledModel(m)
        XCTAssertEqual(api.reads, 2)
    }

    func testTheTemplateCanBeCreated() async {
        let (m, api, _) = await rig()
        XCTAssertEqual(m.ui.template?.exists, false)
        m.createTemplate()
        await settledModel(m)
        XCTAssertEqual(api.created, 1)
        XCTAssertEqual(m.ui.template?.status, "pending")
        XCTAssertNil(m.ui.templateError)
    }

    // ── Rules on their own ───────────────────────────────────────────────────

    func testTimesReadAndShow() {
        XCTAssertEqual(CallingSettingsModel.showTime("0900"), "09:00")
        XCTAssertEqual(CallingSettingsModel.showTime(nil), "")
        XCTAssertEqual(CallingSettingsModel.showTime("9"), "9")
        XCTAssertEqual(CallingSettingsModel.readTime("09:00"), "0900")
        XCTAssertEqual(CallingSettingsModel.readTime("900"), "0900")
        XCTAssertEqual(CallingSettingsModel.readTime("17:30:59"), "1730")
    }

    func testReasonsAndRestrictionWords() {
        XCTAssertEqual(CallingSettingsModel.reason(ApiError(status: 0, method: "GET", path: "/x", body: "timed out after 30s"), fallback: "f"), "The server took too long — try again.")
        XCTAssertEqual(CallingSettingsModel.reason(ApiError(status: 0, method: "GET", path: "/x", body: "Connection reset"), fallback: "f"), "No connection — try again.")
        XCTAssertEqual(CallingSettingsModel.reason(ApiError(status: 403, method: "GET", path: "/x", body: #"{"detail":"Missing permission"}"#), fallback: "f"), "Only admins can change calling settings.")
        XCTAssertEqual(CallingSettingsModel.reason(ApiError(status: 502, method: "GET", path: "/x", body: "<html>502</html>"), fallback: "f"), "f")
        XCTAssertEqual(CallingSettingsModel.reason(PlainError("x"), fallback: "f"), "f")
        XCTAssertEqual(CallingSettingsModel.restrictionWords(.string("RESTRICTED_CALLING_OUTBOUND")), "Restricted calling outbound")
        XCTAssertEqual(CallingSettingsModel.restrictionWords(el(#"{"restriction_type":"RESTRICTED_CALLING","description":"Too many declined calls","expiration":"2026-10-20"}"#)!),
                       "Restricted calling — Too many declined calls — until 2026-10-20")
    }
}
