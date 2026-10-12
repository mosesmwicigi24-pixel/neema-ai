import Foundation
import XCTest
@testable import NeemaCore

/// The reports model against the fake backend: which endpoints it calls with
/// which parameters, the real row shapes, and the ~13 MB download on a bad
/// phone network (the reports rows of Android `AreaViewModelTest`,
/// `ApiContractTest` and `InsightsNetworkTest`).
final class ReportsViewModelTests: ReportsTestCase {
    // ── Requests ─────────────────────────────────────────────────────────────

    func testFetchesEveryConversationUnpaged() async {
        let vm = await vm()
        XCTAssertEqual(vm.ui.allConvs?.count, 9)
        // No limit/cursor/tab: the legacy full array the API keeps for Reports.
        XCTAssertEqual(gets("/admin/conversations"), [nil])
        XCTAssertTrue(errors.isEmpty)
        XCTAssertNotNil(vm.ui.report)
        XCTAssertEqual(vm.ui.report?.convs.count, 8)
    }

    /// admin.py list_conversations: no `limit` → the full legacy array. Nothing else is sent.
    func testTheRequestIsOneBareGet() async {
        _ = await vm()
        let calls = fake.callsTo("GET", "/admin/conversations")
        XCTAssertEqual(calls.count, 1)
        XCTAssertNil(calls[0].query)
        XCTAssertNil(calls[0].body)
        XCTAssertTrue(calls[0].header("Authorization")?.hasPrefix("Bearer ") == true)
    }

    /// Pull-to-refresh: the orders, the team and every conversation again, the spinner down once all have landed.
    func testRefreshRereadsOrdersAgentsAndEveryConversation() async {
        let vm = await vm()
        let before = reads("/admin/orders")
        vm.refresh()
        XCTAssertTrue(vm.ui.refreshing)
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        XCTAssertEqual(downloads(), 2)
        XCTAssertGreaterThan(reads("/admin/orders"), before)
        XCTAssertGreaterThanOrEqual(reads("/admin/agents"), 1)
        XCTAssertFalse(vm.ui.refreshing)
    }

    /// The 30 s ceiling would cut the full list short on a phone link: the download runs on the long one.
    func testTheDownloadUsesTheLongCeiling() {
        XCTAssertGreaterThanOrEqual(NeemaConfig.uploadTimeout, 10 * 60)
    }

    // ── /admin/conversations (no limit) ──────────────────────────────────────

    /// Every key `_conversation_rows()` emits decodes; "+00:00" offsets with microseconds parse.
    func testDecodesTheRealRowShape() async {
        let vm = await vm()
        let rows = vm.ui.allConvs ?? []
        XCTAssertEqual(rows.count, 9)
        let r1 = rows.first { $0.id == "r1" }
        XCTAssertEqual(r1?.personId, "p0000001-0000-4000-8000-000000000001")
        XCTAssertEqual(r1?.assignedAgentName, "Moses Mwicigi")
        XCTAssertEqual(r1?.ordersCount, 2)
        XCTAssertEqual(r1?.tags, ["clergy"])
        // "…T06:59:59.876544+00:00": offset and microseconds both honoured.
        XCTAssertEqual(Fmt.millis(r1?.lastMessageAt), Self.NOW_MS - 2 * 3_600_000 - 124)
        // A Messenger thread: no wa_id, the PSID is the handle.
        let r2 = rows.first { $0.id == "r2" }
        XCTAssertNil(r2?.waId)
        XCTAssertEqual(r2?.handle, "7012345678901234")
        // No messages yet: last_message_at is null, dated by created_at.
        XCTAssertNil(rows.first { $0.id == "r9" }?.lastMessageAt)
        XCTAssertTrue(host.toasts.isEmpty)
    }

    /// Should the server ever answer the paged envelope, Reports still reads every row (never an error for a 200).
    func testAcceptsThePagedEnvelope() async {
        fake.on("GET", "/admin/conversations", body: "{\"items\":[\(ReportsFixtures.conversations.joined(separator: ","))],\"next_cursor\":\"eyJ4Ijoi\"}")
        let vm = await vm()
        XCTAssertEqual(vm.ui.allConvs?.count, 9)
        XCTAssertTrue(host.toasts.isEmpty)
    }

    /// Naive datetimes are UTC; nulls for defaulted fields and a missing optional key are tolerated.
    func testNaiveDatesNullsAndMissingKeys() async {
        fake.on("GET", "/admin/conversations", body: """
            [{"id":"n1","wa_id":"254700000001","intercept_mode":"human","status":"open","channel":null,"unread":null,
              "tags":null,"last_message_at":"2026-09-25T06:00:00","created_at":"2026-09-01T06:00:00"}]
            """)
        let vm = await vm()
        guard let row = vm.ui.allConvs?.first, vm.ui.allConvs?.count == 1 else { return XCTFail("one row") }
        XCTAssertEqual(row.channel, "whatsapp")
        XCTAssertEqual(row.unread, 0)
        XCTAssertEqual(row.tags, [])
        XCTAssertEqual(Fmt.millis(row.lastMessageAt), Int64(ISO8601DateFormatter().date(from: "2026-09-25T06:00:00Z")!.timeIntervalSince1970 * 1000))
        let r = ReportsRules.buildReport([row], orders: [], agents: [], range: .d7, customFrom: nil, customTo: nil, now: Self.NOW_MS, zone: Self.NAIROBI)
        XCTAssertEqual(r.humanConvs, 1)
    }

    /// A 500's FastAPI `{"detail": …}` and a proxy's HTML 502 read the same: no list, the reason with Retry (no markup, no stock text).
    func testErrorBodies() async {
        for (code, body) in [(500, #"{"detail":"Internal Server Error"}"#), (502, "<html>Bad Gateway</html>")] {
            fake.on("GET", "/admin/conversations", code: code, body: body)
            let vm = await vm()
            XCTAssertNil(vm.ui.allConvs)
            XCTAssertEqual(vm.ui.loadError, code == 502 ? FriendlyErrors.DOWN_TEXT : "Could not load conversations for this report.")
            XCTAssertNil(vm.ui.report)
        }
    }

    /// Deliberate fix: the web falls back to an empty list, so a failed download
    /// reads as a true "0 conversations". Here there is no list and the screen
    /// says why, with Retry; the server's "boom" is not a sentence for people.
    func testLoadFailureShowsTheReasonNotZeros() async {
        fake.on("GET", "/admin/conversations", code: 500, body: #"{"detail":"boom"}"#)
        let vm = await vm()
        XCTAssertNil(vm.ui.allConvs)
        XCTAssertEqual(vm.ui.loadError, "Could not load conversations for this report.")
    }

    func testRefreshFailureKeepsTheRowsAlreadyShown() async {
        let vm = await vm()
        fake.on("GET", "/admin/conversations", code: 503, body: "{}")
        vm.refresh()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertEqual(vm.ui.allConvs?.count, 9)
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertEqual(errors.count, 1)
        XCTAssertNotNil(vm.ui.report, "the report stays")
    }

    // ── The ~13 MB download on a bad network ─────────────────────────────────

    func testDownloadTimesOutSaysSoWithRetryThenRetryLoads() async {
        let fail = Ref(true)
        let real = fullBody
        fullList { if fail.value { throw TransportError.timedOut } else { return (200, real) } }
        let vm = await vm()
        XCTAssertNil(vm.ui.allConvs, "no zeros")
        XCTAssertEqual(vm.ui.loadError, "The download timed out — this report needs every conversation, a large download. Try again on a stronger connection.")
        fail.value = false
        vm.retry()
        XCTAssertNil(vm.ui.loadError, "back to the loading state")
        await landed(vm)
        XCTAssertEqual(vm.ui.allConvs?.count, 9)
        XCTAssertNil(vm.ui.loadError)
    }

    func testDownloadCutOffHalfwaySaysSo() async {
        // The connection died mid-body: what arrived is half a JSON array.
        let all = fullBody
        let half = String(all.prefix(all.count / 2))
        fullList { (200, half) }
        let vm = await vm()
        XCTAssertNil(vm.ui.allConvs)
        XCTAssertEqual(vm.ui.loadError, "The download arrived incomplete — try again on a stronger connection.")
    }

    func testTheConnectionDroppingMidDownloadSaysSo() async {
        fullList { throw TransportError.network("unexpected end of stream on https://neema.test/...") }
        let vm = await vm()
        XCTAssertNil(vm.ui.allConvs)
        XCTAssertEqual(vm.ui.loadError, "The download was cut off partway — try again on a stronger connection.")
    }

    func testCaptivePortalPageIsNotReadAsZeroConversations() async {
        fullList { (200, "<html><body>Log in to Safaricom Wi-Fi</body></html>") }
        let vm = await vm()
        XCTAssertNil(vm.ui.allConvs)
        XCTAssertFalse((vm.ui.loadError ?? "").trimmingCharacters(in: .whitespaces).isEmpty)
        XCTAssertFalse((vm.ui.loadError ?? "").contains("<"))
    }

    func testOfflineAndEveryServerStatusGetPlainWords() async {
        let html502 = "<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>nginx</center></body></html>"
        let cases: [(() throws -> (Int, String), String)] = [
            ({ throw TransportError.network("Failed to connect to neema.test/10.0.0.1:443") }, FriendlyErrors.OFFLINE_TEXT),
            ({ (502, html502) }, FriendlyErrors.DOWN_TEXT),
            ({ (429, "") }, "Too many requests — wait a moment, then try again."),
            ({ (403, #"{"detail":"Not enough permissions"}"#) }, "Not enough permissions"),
            ({ (403, #"{"detail":"Forbidden"}"#) }, "Could not load conversations for this report — you don't have permission to see them."),
        ]
        for (setup, want) in cases {
            fullList(setup)
            let vm = await vm()
            XCTAssertEqual(vm.ui.loadError, want)
            XCTAssertFalse((vm.ui.loadError ?? "").contains("<"))
            vm.close()
        }
    }

    func testRefreshFailingKeepsTheReportAndToasts() async {
        let vm = await vm()
        fullList { throw TransportError.timedOut }
        vm.refresh()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertEqual(vm.ui.allConvs?.count, 9)
        XCTAssertEqual(errors, ["Could not load conversations for this report."])
        XCTAssertFalse(vm.ui.refreshing)
    }

    /// Pulls and taps while the first download is on the wire join it: one download.
    func testImpatientRefreshesDownloadOnce() async {
        let vm = await vm()
        let count = Ref(0)
        let real = fullBody
        let vmRef = Ref<ReportsViewModel?>(vm)
        fake.on("GET", "/admin/conversations") { r, _ in
            if r.param("limit") != nil { return (200, #"{"items":[],"next_cursor":null}"#) }
            count.mutate { $0 += 1 }
            onMainSync { vmRef.value?.refresh(); vmRef.value?.retry() }
            return (200, real)
        }
        vm.refresh()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertEqual(count.value, 1)
    }

    /// The screen was closed (the agent signed out) mid-download: the failure that lands after is never toasted.
    func testLeavingMidDownloadMeansNoToast() async {
        let vm = await vm()
        let vmRef = Ref<ReportsViewModel?>(vm)
        fullList { onMainSync { vmRef.value?.close() }; return (500, "Internal Server Error") }
        vm.refresh()
        await drain()
        await settle(ms: 100)
        XCTAssertTrue(errors.isEmpty)
    }

    // ── CSV export with nowhere to write ─────────────────────────────────────

    func testExportWithNoStorageSaysWhatToDo() async throws {
        // A regular file where the directory should be: nothing can be created under it.
        let blocker = tempDir("blocker")
        try "x".write(to: blocker, atomically: true, encoding: .utf8)
        XCTAssertThrowsError(try ReportsRules.writeReportCsv(dir: blocker.appendingPathComponent("reports"), orders: [], range: .d30)) { e in
            XCTAssertEqual(ReportsRules.exportFailureText(e), "Couldn't save the report file — free up some storage on this phone and try again.")
        }
    }

    func testExportWritesTheFile() async throws {
        let dir = tempDir()
        let file = try ReportsRules.writeReportCsv(dir: dir.appendingPathComponent("reports"), orders: [], range: .d7)
        XCTAssertEqual(file.lastPathComponent, "neema-report-7d.csv")
        XCTAssertEqual(try String(contentsOf: file, encoding: .utf8), "Date,Customer,Amount,Status\n")
    }

    func testExportFromTheModelHandsTheFileBack() async throws {
        let vm = await vm()
        let dir = tempDir()
        vm.exportCsv(dir: dir)
        XCTAssertTrue(vm.ui.exporting)
        _ = await eventually(timeout: 10) { vm.ui.readyExport != nil }
        let ready = try XCTUnwrap(vm.ui.readyExport)
        XCTAssertEqual(ready.range, .d30)
        XCTAssertFalse(vm.ui.exporting)
        let text = try String(contentsOf: ready.file, encoding: .utf8)
        XCTAssertEqual(text, ReportsRules.reportCsv(vm.ui.report!.orders))
        XCTAssertEqual(text.split(separator: "\n").count, 7)
    }
}
