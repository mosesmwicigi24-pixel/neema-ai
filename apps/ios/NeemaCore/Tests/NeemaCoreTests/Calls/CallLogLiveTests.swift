import Foundation
import XCTest
@testable import NeemaCore

/// The Calls console's log stays live (components/views/CallsView.tsx): a
/// reload 500 ms after `incoming_call` / `call_ended`, a 60 s fallback tick
/// that pauses in the background, and — beyond the web — an immediate
/// catch-up when the socket reconnects or the app returns to the foreground.
/// Driven through the real LiveSocket on a fake WebSocket. Android `calls/CallLogLiveTest.kt`.
@MainActor
final class CallLogLiveTests: XCTestCase {
    private var rigs: [ConsoleRig] = []

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
        AppClock.reset()
    }
    private func live(_ fake: FakeNeema = callsFake()) async -> ConsoleRig {
        let r = ConsoleRig(fake: fake, live: true)
        rigs.append(r)
        await r.loaded()
        return r
    }
    private var newRing: String {
        CallsFixtures.row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b99", "wacid.NEW", "254799999999", "Sr. Agnes Wairimu", "inbound", "ringing",
                          nil, nil, CallsFixtures.pyIso(0), nil, "none", false)
    }

    func testIncomingCallAddsTheRowHalfASecondLater() async {
        let l = await live()
        XCTAssertEqual(l.vm.calls.value?.count, 7)
        let loads = l.loads
        l.fake.on("GET", "/admin/calls", body: "[" + newRing + "," + String(CallsFixtures.calls.dropFirst()))
        l.frame(#"{"type": "incoming_call", "call_id": "wacid.NEW", "from": "254799999999", "name": "Sr. Agnes Wairimu", "at": "1790330413"}"#)
        await l.advance(499)
        XCTAssertEqual(l.loads, loads)
        await l.advance(1)
        _ = await eventually { l.loads == loads + 1 }
        XCTAssertEqual(l.loads, loads + 1)
        _ = await eventually { l.vm.calls.value?.first?.callId == "wacid.NEW" }
        XCTAssertEqual(l.vm.calls.value?.first?.callId, "wacid.NEW")
        XCTAssertEqual(l.vm.calls.value?.first?.status, "ringing")
    }

    func testCallEndedUpdatesTheRow() async {
        let l = await live()
        let loads = l.loads
        l.frame(#"{"type": "call_ended", "call_id": "\#(CallsFixtures.C2)", "status": "COMPLETED", "duration": null}"#)
        await l.advance(500)
        _ = await eventually { l.loads == loads + 1 }
        XCTAssertEqual(l.loads, loads + 1)
    }

    func testABurstOfFramesIsOneReloadNotAStorm() async {
        let l = await live()
        let loads = l.loads
        for _ in 0..<3 { l.frame(#"{"type": "incoming_call", "call_id": "wacid.NEW", "from": "254799999999", "name": null, "at": "1"}"#) }
        l.frame(#"{"type": "call_ended", "call_id": "wacid.NEW", "status": "COMPLETED", "duration": null}"#)
        l.frame(#"{"type": "call_ended", "call_id": "wacid.OTHER", "status": "COMPLETED", "duration": null}"#)
        await l.advance(500)
        _ = await eventually { l.loads == loads + 1 }
        XCTAssertEqual(l.loads, loads + 1)
        // A frame after that reload schedules the next one.
        await l.loaded()
        l.frame(#"{"type": "call_ended", "call_id": "wacid.NEW", "status": "COMPLETED", "duration": null}"#)
        await l.advance(500)
        _ = await eventually { l.loads == loads + 2 }
        XCTAssertEqual(l.loads, loads + 2)
    }

    func testACallUpdateMergesItsRowInPlaceWithoutARead() async {
        let l = await live()
        let loads = l.loads
        let row = CallsFixtures.row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b02", CallsFixtures.C2, "254722000111", "Rev. Mary Achieng", "inbound", "missed",
                                    nil, nil, CallsFixtures.pyIso(130), nil, "none", false, followUpOpen: false)
        l.vm.select(l.vm.calls.value!.first { $0.callId == CallsFixtures.C2 })
        XCTAssertEqual(l.vm.selected.value?.followUpOpen, true)
        l.frame(#"{"type":"call_update","call":\#(row)}"#)
        await l.advance(1_000)
        XCTAssertEqual(l.loads, loads, "no read: the row came whole")
        XCTAssertEqual(l.vm.calls.value?.count, 7)
        XCTAssertEqual(l.vm.calls.value!.first { $0.callId == CallsFixtures.C2 }?.followUpOpen, false)
        XCTAssertEqual(l.vm.selected.value?.followUpOpen, false, "the open call follows")
        // A new call heads the log.
        l.frame(#"{"type":"call_update","call":\#(newRing)}"#)
        await drain()
        XCTAssertEqual(l.vm.calls.value?.first?.callId, "wacid.NEW")
        XCTAssertEqual(l.vm.calls.value?.count, 8)
    }

    func testFramesThatAreNotCallLogEventsLoadNothing() async {
        let l = await live()
        let loads = l.loads
        l.frame(#"{"type": "outbound_answer", "call_id": "wacid.OUT", "sdp": "v=0"}"#)
        l.frame(#"{"type": "new_message", "conversationId": "c1", "sender": "user", "text": "hi"}"#)
        l.frame(#"{"event": "notification", "type": "intercept", "title": "t", "body": "b", "conversationId": "c1"}"#)
        await l.advance(1_000)
        XCTAssertEqual(l.loads, loads)
    }

    func testAReconnectCatchesUpWhatTheDroppedSocketMissed() async {
        let l = await live()
        let loads = l.loads
        l.host.sockets.last.fail(); await drain()
        await l.advance(2_000)          // LiveSocket retries after 2 s
        XCTAssertEqual(l.loads, loads)
        l.host.sockets.last.open(); await drain()
        _ = await eventually { l.loads == loads + 1 }
        XCTAssertEqual(l.loads, loads + 1, "reloaded on reconnect, without waiting for the 60 s tick")
    }

    func testTheFallbackTickPausesInTheBackgroundAndReturningReloadsAtOnce() async {
        let l = await live()
        let loads = l.loads
        await l.advance(60_000)
        _ = await eventually { l.loads == loads + 1 }
        XCTAssertEqual(l.loads, loads + 1)
        l.host.foreground.value = false; await drain()
        await l.advance(180_000)
        XCTAssertEqual(l.loads, loads + 1, "no ticks in the background")
        l.host.foreground.value = true; await drain()
        _ = await eventually { l.loads == loads + 2 }
        XCTAssertEqual(l.loads, loads + 2)
        await l.advance(59_000)
        XCTAssertEqual(l.loads, loads + 2, "the clock restarts on return: no double load")
        await l.advance(1_000)
        _ = await eventually { l.loads == loads + 3 }
        XCTAssertEqual(l.loads, loads + 3)
    }
}

/// The call log at a thousand rows under a busy socket: bursts of call frames,
/// polling that pauses off-screen and never stacks, and the row keys a lazy
/// list needs. Android `calls/CallsStressTest.kt` (CallsLogStressTest).
@MainActor
final class CallsLogStressTests: XCTestCase {
    private var rigs: [ConsoleRig] = []

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
        AppClock.reset()
    }

    /// A thousand-row log, every status, as list_calls would page it.
    private static var thousand: String {
        let statuses = ["completed", "missed", "declined", "callback", "no_answer", "ended"]
        var rows: [String] = []
        for i in 0..<1_000 {
            let id = String(format: "7c1d2e3f-4a5b-4c6d-8e7f-%012d", i)
            let callId = CallsFixtures.wacid(String(format: "S%05d", i))
            let wa = "2547" + String(10_000_000 + i * 7_919)
            let direction = i % 5 == 0 ? "outbound" : "inbound"
            let duration: Int? = i % 3 == 0 ? 40 + i : nil
            let agent: String? = i % 4 == 0 ? "Moses" : nil
            rows.append(CallsFixtures.row(id, callId, wa, "Customer \(i)", direction, statuses[i % statuses.count], duration, agent,
                                          CallsFixtures.pyIso(Int64(i * 11)), nil, "none", i % 7 == 0))
        }
        return "[" + rows.joined(separator: ",") + "]"
    }

    private func live() async -> ConsoleRig {
        let f = callsFake()
        f.on("GET", "/admin/calls", body: Self.thousand)
        let r = ConsoleRig(fake: f, live: true)
        rigs.append(r)
        await r.loaded()
        return r
    }

    func testAThousandCallsLoadWithUniqueStableKeys() async {
        let r = await live()
        let rows = r.vm.calls.value!
        XCTAssertEqual(rows.count, 1_000)
        let keys = rowKeys(rows)
        XCTAssertEqual(Set(keys).count, 1_000)
        XCTAssertEqual(rowKeys(Array(rows.dropFirst())), Array(keys.dropFirst()), "keys follow the row, not its position")
    }

    func testDuplicateRowsStillGetDistinctKeys() {
        let c = Call(id: "k1", callId: "wacid.1")
        XCTAssertEqual(rowKeys([c, c, Call(id: "", callId: "wacid.2"), c]), ["k1", "k1#2", "wacid.2", "k1#3"])
        let many = (0..<5_000).map { Call(id: "k\($0 % 2_500)", callId: "w\($0)") }
        for _ in 0..<3 { _ = rowKeys(many) }
        let t = Date()
        let k = rowKeys(many)
        let ms = Date().timeIntervalSince(t) * 1000
        XCTAssertEqual(Set(k).count, 5_000)
        XCTAssertTrue(ms < 200, "5,000 keys in \(ms)ms (budget 200)")
    }

    func testTwoHundredCallFramesInABurstAreOneReload() async {
        let r = await live()
        let before = r.loads
        for i in 0..<200 {
            let type = i % 2 == 0 ? "incoming_call" : "call_ended"
            r.frame(#"{"type":"\#(type)","call_id":"wacid.B\#(i)","from":"2547\#(String(format: "%08d", i))","status":"COMPLETED"}"#)
        }
        await r.advance(CallsViewModel.FRAME_RELOAD_MS)
        _ = await eventually { r.loads == before + 1 }
        XCTAssertEqual(r.loads, before + 1, "one reload for the whole burst")
        await r.advance(60_000 - CallsViewModel.FRAME_RELOAD_MS - 1)
        XCTAssertEqual(r.loads, before + 1, "and nothing queued behind it")
    }

    func testOffScreenTheLogNeitherPollsNorReloadsOnFramesAndCatchesUpOnReturn() async {
        let r = await live()
        let before = r.loads
        r.vm.life.shown.value = false; await drain()
        for i in 0..<50 { r.frame(#"{"type":"incoming_call","call_id":"wacid.X\#(i)","from":"254700000000"}"#) }
        await r.advance(5 * 60_000)
        XCTAssertEqual(r.loads, before, "another screen is showing: no ticks, no frame reloads")
        r.vm.life.shown.value = true; await drain()
        _ = await eventually { r.loads == before + 1 }
        XCTAssertEqual(r.loads, before + 1, "back on the log: one catch-up read")
        await r.loaded()
        await r.advance(60_000)
        _ = await eventually { r.loads == before + 2 }
        XCTAssertEqual(r.loads, before + 2)
    }

    func testASlowLogReadIsNeverStackedByTicksFramesAndPulls() async {
        let r = await live()
        let before = r.loads
        let hold = r.fake.hang("GET", "/admin/calls")
        r.vm.refresh(); await drain()
        await r.advance(60_000)                     // the fallback tick
        r.frame(#"{"type":"call_ended","call_id":"wacid.S1","status":"COMPLETED"}"#)
        await r.advance(CallsViewModel.FRAME_RELOAD_MS)
        r.vm.load(); await drain()
        XCTAssertEqual(hold.waiting, 1, "one read on the wire")
        hold.release()
        await drain(); _ = await eventually { !r.vm.refreshing.value && !r.vm.busy }
        XCTAssertEqual(r.loads, before + 2, "the slow read, then one that follows it — not four")
        XCTAssertFalse(r.vm.refreshing.value)
        XCTAssertEqual(r.vm.calls.value?.count, 1_000)
    }
}
