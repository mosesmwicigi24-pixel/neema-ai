import XCTest
@testable import NeemaCore

/// Android `CrashHardeningTest` (the crash fixes of 2026-09-27) and the vault's
/// own file rules: every lazy list key stays unique whatever the server sends,
/// a crash leaves a report on disk, and the report reaches the server.
final class CrashTests: XCTestCase {
    private var dir: URL!
    private var vault: CrashVault!
    private var clockMs: Int64 = 1_790_330_400_000

    override func setUp() {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("neema-crash-\(UUID().uuidString)")
        let ms = { self.clockMs }
        vault = CrashVault(dir: dir, now: { Date(timeIntervalSince1970: Double(ms()) / 1000) })
    }

    override func tearDown() { try? FileManager.default.removeItem(at: dir) }

    private func call(_ id: String, _ iso: String?) -> Call {
        Call(callId: id, waId: "2547000000" + String(id.suffix(2)).leftPad(2), direction: "inbound", status: "completed", startedAt: iso)
    }

    // ── The Calls log: a live update for an OLD call ─────────────────────────

    func testAnUpdateForACallOlderThanAFullLogIsLeftForTheNextRead() {
        let rows = (0..<CALL_LOG_PAGE).map { i -> Call in
            let iso = i < 24 ? String(format: "2026-09-27T%02d:00:00Z", 23 - i % 24) : String(format: "2026-09-26T%02d:00:00Z", 23 - (i - 24) % 24)
            return call("c\(i)", iso)
        }
        XCTAssertNil(insertByTime(rows, call("old", "2026-09-12T10:00:00Z")), "not at the head of the log")
    }

    func testAnUpdateGoesInAtItsPlaceByTime() {
        let rows = [call("a", "2026-09-27T12:00:00Z"), call("b", "2026-09-26T12:00:00Z"), call("c", "2026-09-25T12:00:00Z")]
        let mid = insertByTime(rows, call("m", "2026-09-26T18:00:00+03:00"))!
        XCTAssertEqual(["a", "m", "b", "c"], mid.map { $0.callId })
        let newest = insertByTime(rows, call("n", "2026-09-28T01:00:00Z"))!
        XCTAssertEqual("n", newest.first?.callId)
        // A short log holds every call: an older one is simply last.
        XCTAssertEqual("o", insertByTime(rows, call("o", "2026-01-01T00:00:00Z"))!.last?.callId)
    }

    // ── Other lazy keys the audit found ──────────────────────────────────────

    func testUniqueKeysSurviveIdsThatLookLikeTheirOwnSuffix() {
        let keys = ReportsRules.uniqueKeys(["a#2", "a", "a", "a", "a#2"])
        XCTAssertEqual(keys.count, Set(keys).count)
        let keys2 = CatalogRules.uniqueKeys(["a#2", "a", "a", "a", "a#2"])
        XCTAssertEqual(keys2.count, Set(keys2).count)
    }

    func testLeadStagesNeverRepeat() {
        let ids = LeadsRules.buildStages(["Quoted", "Quoted", " ", "won", "Site visit"]).map { $0.id }
        XCTAssertEqual(ids.count, Set(ids).count)
    }

    func testCallRowKeysAndDayHeadingsNeverRepeatEvenOutOfOrder() {
        // What used to crash: a row from an earlier day at the head of the log, and the same call twice.
        let c = Call(id: "k1", callId: "wacid.1")
        XCTAssertEqual(["k1", "k1#2", "wacid.2", "k1#3"], rowKeys([c, c, Call(id: "", callId: "wacid.2"), c]))
    }

    // ── The vault's files ────────────────────────────────────────────────────

    func testAReportIsWrittenBoundedWithTheAppsLines() {
        CrashVault.appVersion = "1.0.0"; CrashVault.build = "7"; CrashVault.device = "Apple iPhone16,1"; CrashVault.sdk = 18
        defer { CrashVault.appVersion = ""; CrashVault.build = ""; CrashVault.device = ""; CrashVault.sdk = 0 }
        let r = vault.record(kind: "crash", summary: String(repeating: "s", count: 900), trace: String(repeating: "t", count: 60_000), thread: "main")
        XCTAssertEqual(500, r.summary.count)
        XCTAssertEqual(CrashVault.MAX_TRACE, r.trace.count)
        XCTAssertEqual("1.0.0", r.appVersion); XCTAssertEqual("7", r.build); XCTAssertEqual(18, r.sdk)
        XCTAssertEqual("2026-09-25T10:00:00Z", r.at)
        let pending = vault.pending()
        XCTAssertEqual(1, pending.count)
        XCTAssertEqual(r, pending[0].report)
        XCTAssertEqual(r, vault.latest())
        XCTAssertEqual(r, vault.unseenFatal())
        let text = CrashVault.asText(r)
        XCTAssertTrue(text.hasPrefix("Neema crash report\n"))
        XCTAssertTrue(text.contains("Apple iPhone16,1 · iOS 18 · v1.0.0 (7)"))
        XCTAssertLessThanOrEqual(text.count, CrashVault.MAX_TEXT)
    }

    func testASummaryIsTakenFromTheTraceWhenNoneIsGiven() {
        let r = vault.record(kind: "crash", summary: "", trace: "Fatal error: boom\n0 Neema 0x1 main", thread: nil)
        XCTAssertEqual("Fatal error: boom", r.summary)
    }

    func testOnlyTheNewestTenReportsAreKeptOldestFirst() {
        for i in 0..<12 { clockMs += 1_000; vault.record(kind: i % 2 == 0 ? "crash" : "nonfatal", summary: "r\(i)", trace: "", thread: nil) }
        let pending = vault.pending()
        XCTAssertEqual(CrashVault.MAX_FILES, pending.count)
        XCTAssertEqual("r2", pending.first?.report.summary)
        XCTAssertEqual("r11", pending.last?.report.summary)
        XCTAssertEqual("r11", vault.latest()?.summary, "last.txt is the newest, whatever its kind")
        XCTAssertEqual("r10", vault.unseenFatal()?.summary, "last-fatal.txt is the newest crash")
    }

    func testANonFatalNeverRaisesTheNextLaunchNotice() {
        vault.recordNonFatal(ApiError(status: 500, method: "GET", path: "/admin/x", body: "{}"), where: "orders-poll")
        XCTAssertNil(vault.unseenFatal())
        XCTAssertEqual("nonfatal", vault.latest()?.kind)
        XCTAssertEqual("orders-poll", vault.latest()?.thread)
        XCTAssertTrue(vault.latest()!.summary.hasPrefix("ApiError:"))
    }

    func testSeenAndDeliveredRemoveTheirFiles() {
        vault.record(kind: "crash", summary: "boom", trace: "", thread: nil)
        XCTAssertNotNil(vault.unseenFatal())
        vault.seen()
        XCTAssertNil(vault.unseenFatal())
        XCTAssertNotNil(vault.latest(), "last.txt stays for Settings")
        let p = vault.pending()
        vault.delivered(p[0].file)
        XCTAssertTrue(vault.pending().isEmpty)
    }

    func testAnUnreadableFileIsDroppedNotACrash() throws {
        try "not json".write(to: dir.appendingPathComponent("0000000000001-000-crash.json"), atomically: true, encoding: .utf8)
        vault.record(kind: "crash", summary: "ok", trace: "", thread: nil)
        let p = vault.pending()
        XCTAssertEqual(1, p.count)
        XCTAssertEqual("ok", p[0].report.summary)
        XCTAssertFalse(FileManager.default.fileExists(atPath: dir.appendingPathComponent("0000000000001-000-crash.json").path))
    }

    func testTheCrashHookRecordsAndTellsTheReporter() async {
        let after = Ref(0)
        CrashHooks.install(vault) { after.mutate { $0 += 1 } }
        defer { CrashHooks.recordNonFatal = nil }
        rtcGuard("ice") { throw DeviceCallError("native assert") }
        XCTAssertEqual(1, after.value)
        XCTAssertEqual("nonfatal", vault.latest()?.kind)
        XCTAssertEqual("webrtc-ice", vault.latest()?.thread)
    }

    // ── Crash reports reach the server ───────────────────────────────────────

    private final class Tok: TokenProvider, @unchecked Sendable {
        func validAccessToken() async throws -> String? { "tok" }
        func forceRefresh() async throws -> String? { nil }
        func onRejected(_ token: String?) {}
    }

    private func report(_ id: String) -> CrashReport {
        CrashReport(id: id, at: "2026-09-27T18:35:00Z", kind: "crash", summary: "boom", trace: "boom\n\tat x")
    }

    func testSavedReportsAreSentOnceSignedInAndRemovedWhenDelivered() async {
        let fake = FakeNeema()
        fake.on("POST", "/admin/client-crashes", body: #"{"ok":true}"#)
        let http = NeemaHTTP(baseUrl: "https://neema.test", tokens: Tok(), transport: fake)
        http.gate = fake
        let waiting = Ref([(file: URL(fileURLWithPath: "/r1"), report: report("r1")), (file: URL(fileURLWithPath: "/r2"), report: report("r2"))])
        let signedIn = Watched(false)
        let reporter = CrashReporter(http: http, signedIn: signedIn, pending: { waiting.value }, delivered: { f in waiting.mutate { $0.removeAll { $0.file == f } } })
        let none = await reporter.flush()
        XCTAssertEqual(0, none, "signed out: nothing is sent")
        signedIn.value = true
        let sent = await reporter.flush()
        XCTAssertEqual(2, sent)
        XCTAssertTrue(waiting.value.isEmpty)
        let posts = fake.callsTo("POST", "/admin/client-crashes")
        XCTAssertEqual(2, posts.count)
        XCTAssertTrue(posts[0].body!.contains(#""id":"r1""#) && posts[0].body!.contains(#""kind":"crash""#) && posts[0].body!.contains(#""app_version""#), posts[0].body!)
    }

    func testAReportThatCannotBeSentStaysForTheNextTry() async {
        let fake = FakeNeema()
        fake.on("POST", "/admin/client-crashes", code: 503, body: "down")
        let http = NeemaHTTP(baseUrl: "https://neema.test", tokens: Tok(), transport: fake)
        http.gate = fake
        let waiting = Ref([(file: URL(fileURLWithPath: "/r1"), report: report("r1"))])
        let reporter = CrashReporter(http: http, signedIn: Watched(true), pending: { waiting.value }, delivered: { f in waiting.mutate { $0.removeAll { $0.file == f } } })
        let sent = await reporter.flush()
        XCTAssertEqual(0, sent)
        XCTAssertEqual(1, waiting.value.count)
    }

    func testSigningInFlushesTheVault() async {
        let fake = FakeNeema()
        fake.on("POST", "/admin/client-crashes", body: #"{"ok":true}"#)
        let http = NeemaHTTP(baseUrl: "https://neema.test", tokens: Tok(), transport: fake)
        http.gate = fake
        vault.record(kind: "crash", summary: "boom", trace: "", thread: nil)
        let signedIn = Watched(false)
        let reporter = CrashReporter(http: http, signedIn: signedIn, vault: vault)
        reporter.start()
        await drain()
        XCTAssertTrue(fake.callsTo("POST", "/admin/client-crashes").isEmpty)
        signedIn.value = true
        let went = await eventually { fake.callsTo("POST", "/admin/client-crashes").count == 1 }
        XCTAssertTrue(went)
        _ = await eventually { self.vault.pending().isEmpty }
        XCTAssertTrue(vault.pending().isEmpty)
        reporter.stop()
    }
}

private extension String {
    func leftPad(_ n: Int) -> String { count >= n ? self : String(repeating: "0", count: n - count) + self }
}
