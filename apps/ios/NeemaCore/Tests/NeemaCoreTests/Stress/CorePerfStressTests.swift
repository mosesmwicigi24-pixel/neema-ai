import XCTest
@testable import NeemaCore

/// Round 8 (Android `CorePerfStressTest`) — the core under load: a thousand
/// requests through the HTTP client, the bell under a storm of alerts, the
/// coalescer from many threads, and rough time bounds on the hot pure
/// helpers. Cancellation reaching the transport and the socket's bursts are
/// pinned in `NeemaHTTPTests` and `LiveSocketTests`.
final class CorePerfStressTests: XCTestCase {
    private final class Tokens: TokenProvider, @unchecked Sendable {
        func validAccessToken() async throws -> String? { "tok" }
        func forceRefresh() async throws -> String? { nil }
        func onRejected(_ token: String?) {}
    }

    private final class Counter: @unchecked Sendable {
        private let lock = NSLock()
        private var n = 0
        var value: Int { lock.lock(); defer { lock.unlock() }; return n }
        func bump() { lock.lock(); n += 1; lock.unlock() }
    }

    // ── NeemaHTTP under a thousand requests ──────────────────────────────────

    func testAThousandRequestsAllCompleteAndNoneIsLost() async throws {
        let fake = FakeNeema()
        fake.on("GET", "/admin/orders", body: "{}")
        let http = NeemaHTTP(baseUrl: "https://neema.test", tokens: Tokens(), transport: fake)
        http.gate = fake
        let ok = await withTaskGroup(of: Bool.self) { group -> Int in
            for _ in 0..<1_000 { group.addTask { (try? await http.raw("GET", "/admin/orders")) == "{}" } }
            var n = 0
            for await r in group where r { n += 1 }
            return n
        }
        XCTAssertEqual(1_000, ok)
        XCTAssertEqual(1_000, fake.callsTo("GET", "/admin/orders").count)
    }

    func testATransportFailureAndATimeoutReadAsStatusZeroWithTheirWords() async {
        let fake = FakeNeema()
        fake.offline = true
        let http = NeemaHTTP(baseUrl: "https://neema.test", tokens: Tokens(), transport: fake)
        http.gate = fake
        do { _ = try await http.raw("GET", "/admin/me"); XCTFail("expected a failure") }
        catch let e as ApiError { XCTAssertEqual(0, e.status); XCTAssertFalse(e.timedOut); XCTAssertEqual(ErrorText.OFFLINE, ErrorText.of(e)) }
        catch { XCTFail("\(error)") }
        fake.offline = false
        fake.timeout("GET", "/admin/me")
        do { _ = try await http.raw("GET", "/admin/me"); XCTFail("expected a failure") }
        catch let e as ApiError { XCTAssertEqual(0, e.status); XCTAssertTrue(e.timedOut); XCTAssertEqual(ErrorText.TIMED_OUT, ErrorText.of(e)) }
        catch { XCTFail("\(error)") }
    }

    // ── The bell under a storm ───────────────────────────────────────────────

    @MainActor
    func testAStormOf500AlertsKeepsTheBellBoundedNewestFirstAndPersistsTheLatest() async {
        let events = Signal<JSONValue>(buffer: 64)
        let store = MemoryPrefs()
        let nc = AgentNotifications(events: events, appPrefs: AppPrefs(store: MemoryPrefs()), store: store, sink: RecordingTray())
        nc.start(foreground: Watched(true))
        let t0 = Date()
        for i in 0..<500 {
            events.emit(JSONValue.parse(#"{"event":"notification","type":"new_conversation","title":"Chat \#(i)","body":"hi","wa_id":"2547\#(i)"}"#)!)
        }
        await drain()
        let ms = Date().timeIntervalSince(t0) * 1000
        let items = nc.items.value
        XCTAssertEqual(AgentNotifications.MAX_ITEMS, items.count)
        XCTAssertEqual("Chat 499", items.first?.title)
        XCTAssertEqual("Chat 440", items.last?.title)
        XCTAssertEqual(items.count, Set(items.map { $0.id }).count, "ids stay unique")
        let saved = store.string("neema_notifications.items") ?? ""
        XCTAssertTrue(saved.contains("Chat 499") && !saved.contains("\"Chat 439\""), "the disk copy is the latest list")
        XCTAssertLessThan(ms, 2_000, "500 alerts handled in \(ms) ms")
        nc.stop()
    }

    // ── Coalescer ────────────────────────────────────────────────────────────

    func testTenThousandKicksFromEightThreadsCostOneRun() async {
        let runs = Counter()
        let c = Coalescer(windowMs: 50) { runs.bump() }
        let group = DispatchGroup()
        for _ in 0..<8 {
            group.enter()
            DispatchQueue.global().async { for _ in 0..<1_250 { c.kick() }; group.leave() }
        }
        group.wait()
        _ = await eventually { runs.value >= 1 }
        try? await Task.sleep(nanoseconds: 80_000_000)
        XCTAssertEqual(1, runs.value)
    }

    func testAnImmediateCoalescerStillCoalescesWhileItsRunIsSuspended() async {
        let gate = Deferred<Void>()
        let runs = Counter()
        let c = Coalescer(windowMs: 0) { runs.bump(); try await gate.value() }
        c.kick()
        _ = await eventually { runs.value == 1 }
        c.kick()   // run 1 is suspended: this one is queued behind it, not dropped
        await settle(ms: 30)
        XCTAssertEqual(1, runs.value)
        _ = gate.complete(())
        _ = await eventually { runs.value == 2 }
        XCTAssertEqual(2, runs.value)
    }

    // ── Hot pure helpers ─────────────────────────────────────────────────────

    func testFormattingFiveThousandRowsIsCheap() {
        let phones = (0..<5_000).map { String(format: "2547%08d", $0) }
        let stamps = (0..<5_000).map { String(format: "2026-09-%02dT%02d:15:00Z", 1 + $0 % 28, $0 % 24) }
        _ = Fmt.formatPhone(phones[0]); _ = Fmt.millis(stamps[0])   // warm up
        let t0 = Date()
        let out = phones.map { Fmt.formatPhone($0) }
        let ms = stamps.map { Fmt.millis($0) }
        let took = Date().timeIntervalSince(t0) * 1000
        XCTAssertEqual(5_000, out.count)
        XCTAssertTrue(ms.allSatisfy { ($0 ?? 0) > 0 })
        XCTAssertLessThan(took, 500, "5k phones + 5k timestamps took \(took) ms")
    }

    func testErrorTextForAHugeErrorPageIsBoundedAndQuick() {
        let html = "<!doctype html><html>" + String(repeating: "x", count: 2_000_000) + "</html>"
        let t0 = Date()
        let msg = ErrorText.of(ApiError(status: 502, method: "GET", path: "/admin/orders", body: html))
        let took = Date().timeIntervalSince(t0) * 1000
        XCTAssertFalse(msg.contains("<html"), "never shows the page")
        XCTAssertLessThan(msg.count, 300)
        XCTAssertLessThan(took, 500, "took \(took) ms")
    }

    func testFiveThousandCallRowKeysAreUniqueAndCheap() {
        var many: [Call] = []
        for i in 0..<5_000 { many.append(Call(id: "k\(i % 2_500)", callId: "w\(i)")) }
        for _ in 0..<3 { _ = rowKeys(many) }
        let t0 = Date()
        let k = rowKeys(many)
        let ms = Date().timeIntervalSince(t0) * 1000
        XCTAssertEqual(5_000, Set(k).count)
        XCTAssertLessThan(ms, 200, "5,000 keys in \(ms) ms (budget 200)")
    }
}
