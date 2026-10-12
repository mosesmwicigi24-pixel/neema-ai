import Foundation
import XCTest
@testable import NeemaCore

/// The call console's state (components/views/CallsView.tsx) against the fake backend. Android `calls/CallsViewModelTest.kt`.
@MainActor
final class CallsViewModelTests: XCTestCase {
    private var rigs: [ConsoleRig] = []
    private let C1 = CallsFixtures.C1, C3 = CallsFixtures.C3, C5 = CallsFixtures.C5, C6 = CallsFixtures.C6

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
        AppClock.reset()
    }

    private func rig(_ fake: FakeNeema = callsFake()) async -> ConsoleRig {
        let r = ConsoleRig(fake: fake)
        rigs.append(r)
        await r.loaded()
        return r
    }
    private func transcriptLoaded(_ r: ConsoleRig) async { _ = await eventually { r.vm.transcript.value?.data != nil || r.vm.transcript.value?.loadErr != nil } }
    private func transcribed(_ r: ConsoleRig) async { await drain(); _ = await eventually { r.vm.transcript.value?.busy == false } }

    func testLoadsTheLogAndFallsBackToEmptyOnError() async {
        let r = await rig()
        XCTAssertEqual(r.vm.calls.value?.count, 7)
        let f = Fixtures.withFixtures(); f.on("GET", "/admin/calls", code: 500, body: "{}")
        let r2 = await rig(f)
        XCTAssertEqual(r2.vm.calls.value, [])
    }

    func testDeepLinkFocusPicksTheNewestCallOfThatCustomer() async {
        let r = await rig()
        r.host.callsFocusKey.value = "+254712345678"
        r.vm.consumeFocus("+254712345678")
        XCTAssertEqual(r.vm.selected.value?.id, CallsFixtures.K1)
        XCTAssertNil(r.host.callsFocusKey.value)
        r.vm.consumeFocus("254799999999"); await drain()
        XCTAssertEqual(r.vm.selected.value?.id, CallsFixtures.K1)
    }

    func testTranscriptPanelLoadsTogglesAndTranscribes() async {
        let r = await rig()
        r.vm.toggleTranscript(C5); await transcriptLoaded(r)
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "recorded")
        r.vm.runTranscribe(); await transcribed(r)
        XCTAssertTrue(r.fake.called("POST", CallsFixtures.path(C5, "transcribe")))
        XCTAssertEqual(r.vm.transcript.value?.busy, false)
        r.vm.toggleTranscript(C5)
        XCTAssertNil(r.vm.transcript.value)
    }

    func testTranscribeErrorsUseTheWebCopy() async {
        let r = await rig()
        r.fake.on("POST", CallsFixtures.route(C5, "transcribe"), code: 409, body: #"{"detail":"off"}"#)
        r.vm.toggleTranscript(C5); await transcriptLoaded(r); r.vm.runTranscribe(); await transcribed(r)
        XCTAssertEqual(r.vm.transcript.value?.err, "Turn on transcription on the server first (WHISPER_ENABLED).")
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "recorded")
        r.fake.on("POST", CallsFixtures.route(C5, "transcribe"), code: 502, body: "{}")
        r.vm.runTranscribe(); await transcribed(r)
        XCTAssertEqual(r.vm.transcript.value?.err, "Couldn't start transcription.")
    }

    func testTranscribeTellsTheTwo409sApart() async {
        // routers/admin.py calls_transcribe raises 409 when Whisper is off AND
        // when the call has no recording; only the first is a server setting.
        let r = await rig()
        r.fake.on("POST", CallsFixtures.route(C6, "transcribe"), code: 409, body: CallsFixtures.WHISPER_OFF)
        r.vm.toggleTranscript(C6); await transcriptLoaded(r); r.vm.runTranscribe(); await transcribed(r)
        XCTAssertEqual(r.vm.transcript.value?.err, "Turn on transcription on the server first (WHISPER_ENABLED).")
        r.fake.on("POST", CallsFixtures.route(C6, "transcribe"), code: 409, body: CallsFixtures.NO_RECORDING)
        r.vm.runTranscribe(); await transcribed(r)
        XCTAssertEqual(r.vm.transcript.value?.err, "No recording was captured for this call.")
        r.fake.on("POST", CallsFixtures.route(C6, "transcribe"), code: 404, body: #"{"detail":"Call not found"}"#)
        r.vm.runTranscribe(); await transcribed(r)
        XCTAssertEqual(r.vm.transcript.value?.err, "Couldn't start transcription.")
    }

    func testTranscribeAlreadyRunningIsASuccess() async {
        // calls_transcribe returns {"ok":true,"status":"pending"} without re-queuing.
        let r = await rig()
        r.fake.on("POST", CallsFixtures.route(C3, "transcribe"), body: "{\"ok\":true,\"call_id\":\"\(C3)\",\"status\":\"pending\"}")
        r.vm.toggleTranscript(C3); await transcriptLoaded(r); r.vm.runTranscribe(); await transcribed(r)
        XCTAssertNil(r.vm.transcript.value?.err)
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "pending")
        XCTAssertEqual(r.fake.callsTo("POST", CallsFixtures.path(C3, "transcribe")).last?.body, "{}")
    }

    func testFollowUpsAreTheCallsStillOwedAndCanBeMarkedDone() async {
        let r = await rig()
        let owed = r.vm.calls.value!.filter { $0.followUpOpen }
        XCTAssertEqual(owed.map { $0.status }, ["missed", "callback", "missed"])
        let first = owed[0]
        r.vm.markFollowUpDone(first); await drain()
        XCTAssertEqual(r.fake.callsTo("POST", CallsFixtures.path(first.callId, "follow-up-done")).map { $0.body }, ["{}"])
        XCTAssertEqual(r.vm.calls.value!.filter { $0.followUpOpen }.count, 2)
        r.vm.markFollowUpDone(first); await drain()
        XCTAssertEqual(r.fake.callsTo("POST", CallsFixtures.path(first.callId, "follow-up-done")).count, 1, "not owed any more: nothing sent")
        // Refused: it goes back on the list.
        let second = r.vm.calls.value!.first { $0.followUpOpen }!
        r.fake.on("POST", CallsFixtures.route(second.callId, "follow-up-done"), code: 404, body: #"{"detail":"Call not found"}"#)
        r.vm.markFollowUpDone(second); await drain()
        XCTAssertEqual(r.vm.calls.value!.filter { $0.followUpOpen }.count, 2)
        XCTAssertTrue(r.vm.doneBusy.value.isEmpty)
    }

    func testFollowUpsFilterSurvivesProcessDeathKeys() async {
        let r = await rig()
        r.vm.followUpsOnly.value = true
        XCTAssertEqual(JSONValue.parse(r.vm.saveUi())?["followUps"]?.boolValue, true)
    }

    func testShowFullTranscriptToggles() async {
        let r = await rig()
        r.vm.toggleTranscript(C1)
        r.vm.toggleFull()
        XCTAssertEqual(r.vm.transcript.value?.showFull, true)
    }
}

/// The call log and the transcript panel on a bad network (the fake throwing
/// what the transport throws: no connection, a timeout; or answering 4xx/5xx/HTML).
/// Android `calls/CallsViewModelNetworkTest.kt`.
@MainActor
final class CallsViewModelNetworkTests: XCTestCase {
    private var rigs: [ConsoleRig] = []
    private let C1 = CallsFixtures.C1, C3 = CallsFixtures.C3, C5 = CallsFixtures.C5

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
        AppClock.reset()
    }

    private func rig(_ fake: FakeNeema = callsFake()) async -> ConsoleRig {
        let r = ConsoleRig(fake: fake)
        rigs.append(r)
        await r.loaded()
        return r
    }
    private func transcriptLoaded(_ r: ConsoleRig) async { _ = await eventually { r.vm.transcript.value?.data != nil || r.vm.transcript.value?.loadErr != nil } }
    private func transcribed(_ r: ConsoleRig) async { await drain(); _ = await eventually { r.vm.transcript.value?.busy == false } }

    // ── The call log ─────────────────────────────────────────────────────
    func testOfflineFirstLoadSaysSoAndRetryRecovers() async {
        let f = callsFake(); f.drop("GET", "/admin/calls")
        let r = await rig(f)
        XCTAssertEqual(r.vm.calls.value, [])
        XCTAssertEqual(r.vm.loadError.value, "No connection — check your internet and try again.")
        f.on("GET", "/admin/calls", body: CallsFixtures.calls)
        r.vm.refresh(); await drain(); _ = await eventually { !r.vm.refreshing.value }
        XCTAssertEqual(r.vm.calls.value?.count, 7)
        XCTAssertNil(r.vm.loadError.value)
        XCTAssertFalse(r.vm.refreshing.value)
    }

    func testAFailedRefreshKeepsTheLogOnScreen() async {
        let r = await rig()
        XCTAssertEqual(r.vm.calls.value?.count, 7)
        r.fake.timeout("GET", "/admin/calls")
        r.vm.load(); await drain(); _ = await eventually { r.vm.loadError.value != nil }
        XCTAssertEqual(r.vm.calls.value?.count, 7, "cached rows stay")
        XCTAssertEqual(r.vm.loadError.value, "The server took too long to answer — try again.")
        r.vm.refresh(); await drain(); _ = await eventually { !r.vm.refreshing.value }
        XCTAssertEqual(r.vm.calls.value?.count, 7)
        XCTAssertFalse(r.vm.refreshing.value, "the spinner stops")
    }

    func testServerErrorsNeverShowRawHtml() async {
        for (code, msg) in [(502, "The server had a problem — try again shortly."), (503, "The server had a problem — try again shortly."),
                            (500, "The server had a problem — try again shortly."), (429, "Too many requests — wait a moment and try again."),
                            (403, "You don't have access to calls."), (404, "Couldn't load calls.")] {
            let f = callsFake(); f.on("GET", "/admin/calls", code: code, body: "<html><body><h1>\(code) Bad Gateway</h1></body></html>")
            let r = await rig(f)
            XCTAssertEqual(r.vm.loadError.value, msg, "\(code)")
            XCTAssertFalse(r.vm.loadError.value?.contains("<") ?? true)
        }
    }

    func testMalformedBodyIsAnErrorNotACrash() async {
        let f = callsFake(); f.on("GET", "/admin/calls", body: #"{"not":"a list"}"#)
        let r = await rig(f)
        XCTAssertEqual(r.vm.calls.value, [])
        XCTAssertNotNil(r.vm.loadError.value)
        let f2 = callsFake(); f2.on("GET", "/admin/calls", body: "")
        let r2 = await rig(f2)
        XCTAssertEqual(r2.vm.calls.value, [])
    }

    func testASuccessfulPollClearsTheError() async {
        let f = callsFake(); f.drop("GET", "/admin/calls")
        let r = await rig(f)
        XCTAssertNotNil(r.vm.loadError.value)
        f.on("GET", "/admin/calls", body: CallsFixtures.calls)
        await r.advance(60_001)
        _ = await eventually { r.vm.calls.value?.count == 7 }
        XCTAssertEqual(r.vm.calls.value?.count, 7)
        XCTAssertNil(r.vm.loadError.value)
    }

    // ── The transcript panel ─────────────────────────────────────────────
    func testAFlakyPollKeepsTheTranscriptStatusAndKeepsPolling() async {
        let r = await rig()
        r.vm.toggleTranscript(C3); await transcriptLoaded(r)
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "pending")
        r.fake.drop("GET", CallsFixtures.route(C3, "transcript"))
        await r.advance(5_001)
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "pending", "the failed poll changed nothing")
        XCTAssertNil(r.vm.transcript.value?.loadErr)
        r.fake.on("GET", CallsFixtures.route(C3, "transcript"), body: CallsFixtures.transcript(C3, "done"))
        await r.advance(5_001)
        _ = await eventually { r.vm.transcript.value?.data?.status == "done" }
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "done", "the poll went on and landed the result")
    }

    func testATranscriptThatCannotLoadSaysWhyAndRetries() async {
        let f = callsFake(); f.drop("GET", CallsFixtures.route(C5, "transcript"))
        let r = await rig(f)
        r.vm.toggleTranscript(C5); await transcriptLoaded(r)
        XCTAssertNil(r.vm.transcript.value?.data)
        XCTAssertEqual(r.vm.transcript.value?.loadErr, "No connection — couldn't load the transcript.")
        f.on("GET", CallsFixtures.route(C5, "transcript"), body: CallsFixtures.transcript(C5, "recorded"))
        r.vm.retryTranscript(); await transcriptLoaded(r)
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "recorded")
        XCTAssertNil(r.vm.transcript.value?.loadErr)
    }

    func testATranscriptForADeletedCallSaysSo() async {
        let f = callsFake(); f.on("GET", CallsFixtures.route(C5, "transcript"), code: 404, body: #"{"detail":"Call not found"}"#)
        let r = await rig(f)
        r.vm.toggleTranscript(C5); await transcriptLoaded(r)
        XCTAssertEqual(r.vm.transcript.value?.loadErr, "This call is no longer in the log.")
    }

    func testClosingThePanelMidRequestLandsNothing() async {
        let r = await rig()
        let vm = r.vm
        r.fake.on("GET", CallsFixtures.route(C1, "transcript")) { _, _ in
            onMainSync { vm.toggleTranscript(CallsFixtures.C1) }   // closed while the request is in flight
            return (200, CallsFixtures.transcript(CallsFixtures.C1, "done"))
        }
        r.vm.toggleTranscript(C1); await drain(); await settle(ms: 60)
        XCTAssertNil(r.vm.transcript.value)
    }

    func testTranscribeDoubleTapSendsOneRequest() async {
        let r = await rig()
        let vm = r.vm
        r.vm.toggleTranscript(C5); await transcriptLoaded(r)
        let busyInside = Ref(false)
        r.fake.on("POST", CallsFixtures.route(C5, "transcribe")) { _, _ in
            onMainSync { busyInside.value = vm.transcript.value?.busy == true; vm.runTranscribe() }   // a second tap while the first is in flight
            return (200, "{\"ok\":true,\"call_id\":\"\(CallsFixtures.C5)\",\"status\":\"pending\"}")
        }
        r.vm.runTranscribe(); await transcribed(r)
        XCTAssertTrue(busyInside.value)
        XCTAssertEqual(r.fake.callsTo("POST", CallsFixtures.path(C5, "transcribe")).count, 1)
        XCTAssertFalse(r.vm.transcript.value?.busy ?? true)
    }

    func testTranscribeTimedOutButStartedShowsTheTruth() async {
        let r = await rig()
        r.vm.toggleTranscript(C5); await transcriptLoaded(r)
        r.fake.timeout("POST", CallsFixtures.route(C5, "transcribe"))
        // The job started server-side even though the answer never came back.
        r.fake.on("GET", CallsFixtures.route(C5, "transcript"), body: CallsFixtures.transcript(C5, "pending"))
        r.vm.runTranscribe(); await transcribed(r)
        XCTAssertNil(r.vm.transcript.value?.err, "no failure claimed")
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "pending")
        XCTAssertFalse(r.vm.transcript.value?.busy ?? true)
    }

    func testTranscribeOfflineSaysSo() async {
        let r = await rig()
        r.vm.toggleTranscript(C5); await transcriptLoaded(r)
        r.fake.drop("POST", CallsFixtures.route(C5, "transcribe"))
        r.vm.runTranscribe(); await transcribed(r)
        XCTAssertEqual(r.vm.transcript.value?.err, "No connection — couldn't start transcription.")
        XCTAssertEqual(r.vm.transcript.value?.data?.status, "recorded")
    }
}

/// The acceptance scenarios that end in the Calls view (17, 19, 22) and the
/// Messenger history words (M6). Android `calls/CallAcceptanceTest.kt` (CallAcceptanceHistoryTest).
@MainActor
final class CallAcceptanceHistoryTests: XCTestCase {
    private var rigs: [ConsoleRig] = []
    private let grace = "7788990011", peter = "254712345678"

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
        AppClock.reset()
    }
    private func rig() async -> ConsoleRig {
        let r = ConsoleRig(fake: callsFake())
        rigs.append(r)
        await r.loaded()
        return r
    }

    func testS17TheSummaryReachesTheHistoryRow() async {
        let r = await rig()
        let before = r.vm.calls.value!.first { $0.callId == CallsFixtures.C1 }!
        let row = CallsFixtures.row(before.id, CallsFixtures.C1, before.waId, before.name, "inbound", "completed", 184, "Moses Mwicigi",
                                    before.startedAt, "Wants two shirts by Friday.", "done", true,
                                    insights: #"{"next_action":"Send the price list","follow_up_message":"Here are the prices, Father."}"#)
        r.vm.mergeRow(JSONValue.parse(row)!)
        let after = r.vm.calls.value!.first { $0.callId == CallsFixtures.C1 }!
        XCTAssertEqual(after.summary, "Wants two shirts by Friday.")
        XCTAssertEqual(after.transcriptStatus, "done")
        XCTAssertEqual(after.insights?.followUpMessage, "Here are the prices, Father.")
        XCTAssertEqual(r.vm.calls.value!.filter { $0.callId == CallsFixtures.C1 }.count, 1, "merged in place, not duplicated")
    }

    func testS19FollowUpDoneLeavesFollowUps() async {
        let r = await rig()
        let owed = r.vm.calls.value!.filter { $0.followUpOpen }
        XCTAssertFalse(owed.isEmpty)
        let first = owed[0]
        r.vm.markFollowUpDone(first); await drain()
        XCTAssertEqual(r.fake.callsTo("POST", CallsFixtures.path(first.callId, "follow-up-done")).count, 1)
        XCTAssertFalse(r.vm.calls.value!.first { $0.callId == first.callId }!.followUpOpen, "off the Follow-ups list")
        XCTAssertEqual(r.vm.calls.value!.filter { $0.followUpOpen }.count, owed.count - 1)
    }

    func testS22VoicemailReachesTheLog() async {
        let r = await rig()
        let c2 = r.vm.calls.value!.first { $0.callId == CallsFixtures.C2 }!
        XCTAssertFalse(c2.hasVoicemail)
        let row = CallsFixtures.row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b02", CallsFixtures.C2, "254722000111", "Rev. Mary Achieng",
                                    "inbound", "missed", nil, nil, CallsFixtures.pyIso(130), nil, "none", false)
            .replacingOccurrences(of: "\"has_recording\":false", with: "\"has_recording\":false,\"has_voicemail\":true")
        r.vm.mergeRow(JSONValue.parse(row)!)
        XCTAssertTrue(r.vm.calls.value!.first { $0.callId == CallsFixtures.C2 }!.hasVoicemail)
    }

    func testM6HistoryAndThreadSayWhichApp() async {
        let row = Call(callId: "c_1", waId: nil, channel: "messenger", externalId: grace, direction: "outbound", status: "rejected")
        XCTAssertEqual(callRowWords(row).label, "Declined by customer")
        XCTAssertEqual(rowWho(row), "Messenger caller")
        XCTAssertEqual(callHandle(row), grace)
        XCTAssertEqual(channelLabel(row.channel), "Messenger")
        XCTAssertEqual(channelLabel(nil), "WhatsApp")
        let wa = Call(callId: "w_1", waId: peter, direction: "inbound", status: "completed")
        XCTAssertEqual(callHandle(wa), peter)
        XCTAssertEqual(rowWho(wa), "+\(peter)")
        // A live row lands in the log with its channel.
        let r = await rig()
        r.vm.mergeRow(JSONValue.parse(#"{"call_id":"c_2","channel":"messenger","external_id":"\#(grace)","wa_id":null,"name":null,"direction":"inbound","status":"missed","started_at":"2026-09-26T10:00:00+00:00"}"#)!)
        let landed = r.vm.calls.value!.first { $0.callId == "c_2" }!
        XCTAssertEqual(landed.channel, "messenger")
        XCTAssertEqual(rowWho(landed), "Messenger caller")
        XCTAssertFalse(r.vm.canCallBack(landed), "Messenger calls back only while Messenger can call")
        XCTAssertTrue(r.vm.canCallBack(r.vm.calls.value!.first { !($0.waId ?? "").isEmpty }!))
    }
}

/// The Calls console's UI state across process death, and the caller deep link on a stale log.
/// Android `calls/CallLifecycleTest.kt` (CallsConsoleLifecycleTest).
@MainActor
final class CallsConsoleLifecycleTests: XCTestCase {
    private var rigs: [ConsoleRig] = []

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
        AppClock.reset()
    }
    private func rig(_ fake: FakeNeema = callsFake()) async -> ConsoleRig {
        let r = ConsoleRig(fake: fake)
        rigs.append(r)
        await r.loaded()
        return r
    }
    private func warned(_ r: ConsoleRig) -> Bool { r.host.toasts.contains { $0.message.hasPrefix("No calls with this customer") } }

    func testFollowUpsFilterAndOpenCallSurviveProcessDeath() async {
        let a = await rig()
        a.vm.followUpsOnly.value = true
        a.vm.select(a.vm.calls.value!.first { $0.id == CallsFixtures.K1 })
        // The new process: the log hasn't loaded when the screen restores.
        let f = callsFake()
        f.on("GET", "/admin/calls", code: 500, body: "{}")
        let b = await rig(f)
        b.vm.restoreIfFresh(a.vm.saveUi())
        XCTAssertTrue(b.vm.followUpsOnly.value)
        XCTAssertNil(b.vm.selected.value, "waits for its row")
        f.on("GET", "/admin/calls", body: CallsFixtures.calls)
        b.vm.refresh(); await drain(); _ = await eventually { !b.vm.refreshing.value }
        XCTAssertEqual(b.vm.selected.value?.id, CallsFixtures.K1, "opened once the log is read")
    }

    func testACallerLinkOnAStaleLogReadsItAgainBeforeSayingThereAreNoCalls() async {
        let r = await rig()
        // A new caller rang after the log was read: the missed-call alert names them.
        let fresh = CallsFixtures.row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b99", "wacid.NEW", "254711000999", "Mama Wanjiku", "inbound", "missed",
                                      nil, nil, CallsFixtures.pyIso(1), nil, "none", false)
        r.fake.on("GET", "/admin/calls", body: "[" + fresh + "," + String(CallsFixtures.calls.dropFirst()))
        r.host.callsFocusKey.value = "254711000999"
        r.vm.consumeFocus("254711000999"); await drain()
        _ = await eventually { r.vm.selected.value != nil }
        XCTAssertEqual(r.vm.selected.value?.callId, "wacid.NEW")
        XCTAssertFalse(warned(r), "no false 'no calls yet'")
        XCTAssertNil(r.host.callsFocusKey.value)
    }

    func testACallerLinkWhenTheLogCantBeReadSaysNothingFalse() async {
        let r = await rig()
        r.fake.on("GET", "/admin/calls", code: 503, body: "{}")
        r.host.callsFocusKey.value = "254711000999"
        r.vm.consumeFocus("254711000999"); await drain()
        _ = await eventually { r.host.callsFocusKey.value == nil }
        XCTAssertNil(r.vm.selected.value)
        XCTAssertFalse(warned(r))
        XCTAssertNil(r.host.callsFocusKey.value, "consumed: the log's own error explains")
    }

    func testACallerWithNoCallsStillGetsTheWebsWarningAfterAFreshRead() async {
        let r = await rig()
        let before = r.loads
        r.host.callsFocusKey.value = "254799999999"
        r.vm.consumeFocus("254799999999"); await drain()
        _ = await eventually { self.warned(r) }
        XCTAssertEqual(r.loads, before + 1, "read again first")
        XCTAssertTrue(r.host.toasts.contains { $0.message == "No calls with this customer yet — showing the full call log." })
    }
}
