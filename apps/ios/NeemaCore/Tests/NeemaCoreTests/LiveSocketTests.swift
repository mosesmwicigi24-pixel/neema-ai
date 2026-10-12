import XCTest
@testable import NeemaCore

/// lib/websocket.tsx createNativeWs(): /ws/{agent_id}, ping every 25 s, reconnect 2 s after any close.
final class LiveSocketTests: XCTestCase {
    private var factory: FakeSocketFactory!
    private var clock: VirtualClock!

    override func setUp() {
        factory = FakeSocketFactory()
        clock = VirtualClock()
    }

    private func socket(_ base: String = "https://neema.test", token: @escaping () -> String? = { nil }) -> LiveSocket {
        LiveSocket(factory: factory, baseUrl: base, token: token, sleep: clock.sleeper)
    }

    private func advance(_ ms: Int64) async { await clock.advance(by: ms) }

    func testTheUrlIsTheWsTwinOfTheOriginWithoutApi() {
        XCTAssertEqual("wss://neema.test/ws/a1", socket().url("a1"))
        XCTAssertEqual("ws://10.0.2.2:8000/ws/a1", socket("http://10.0.2.2:8000/api/").url("a1"))
        XCTAssertEqual("wss://x.test/ws/a1", socket("https://x.test/").url("a1"))
    }

    /// The server opens the feed only for a signed-in agent: the access token rides in the query.
    func testTheUrlCarriesTheCurrentTokenAndEachRetryRereadsIt() async {
        var token = "tok.en+1/="
        let s = socket(token: { token })
        XCTAssertEqual("wss://neema.test/ws/a1?token=tok.en%2B1%2F%3D", s.url("a1"))

        s.connect("a1")
        XCTAssertTrue(factory.last.urlText.hasSuffix("/ws/a1?token=tok.en%2B1%2F%3D"))
        token = "refreshed"
        factory.last.fail()
        await advance(2_001)
        XCTAssertEqual(2, factory.count)
        XCTAssertTrue(factory.last.urlText.hasSuffix("/ws/a1?token=refreshed"), "a retry after a refresh uses the new token")
    }

    func testConnectOpensOnceAndIsIdempotentPerAgent() {
        let s = socket()
        s.connect("a1"); s.connect("a1")
        XCTAssertEqual(1, factory.count)
        XCTAssertTrue(factory.last.urlText.hasSuffix("://neema.test/ws/a1"), factory.last.urlText)
        XCTAssertFalse(s.connected.value, "not connected until the server accepts")
        factory.last.open()
        XCTAssertTrue(s.connected.value)

        s.connect("a2")
        XCTAssertEqual(1000, factory[0].closedWith, "switching agent closes the old socket")
        XCTAssertTrue(factory.last.urlText.hasSuffix("://neema.test/ws/a2"))
    }

    func testPingsEvery25SecondsWhileOpen() async {
        let s = socket()
        s.connect("a1"); factory.last.open()
        await advance(24_999)
        XCTAssertTrue(factory.last.sentFrames.isEmpty)
        await advance(2)
        await eventually { self.factory.last.sentCount == 1 }
        XCTAssertEqual([#"{"type":"ping"}"#], factory.last.sentFrames)
        await advance(25_000)
        await eventually { self.factory.last.sentCount == 2 }
        XCTAssertEqual(2, factory.last.sentCount)
    }

    func testFramesAreEmittedPongsAndGarbageAreNot() {
        let s = socket()
        var got: [JSONValue] = []
        let sub = s.events.observe { got.append($0) }
        defer { sub.cancel() }
        s.connect("a1"); factory.last.open()
        factory.last.frame(#"{"type":"pong"}"#)
        factory.last.frame("not json")
        factory.last.frame("[1,2]")
        factory.last.frame(#"{"event":"notification","type":"intercept","title":"Picked up"}"#)
        factory.last.frame(#"{"type":"new_message","conversationId":"c1"}"#)
        XCTAssertEqual(["notification", nil], got.map { $0.str("event") })
        XCTAssertEqual("c1", got[1].str("conversationId"))
    }

    func testADroppedSocketReconnectsAfterTwoSeconds() async {
        let s = socket()
        s.connect("a1"); factory.last.open()
        factory.last.fail()
        XCTAssertFalse(s.connected.value)
        await advance(1_999)
        XCTAssertEqual(1, factory.count)
        await advance(2)
        await eventually { self.factory.count == 2 }
        factory.last.open()
        XCTAssertTrue(s.connected.value)
        // The dead socket's ping stopped with it.
        await advance(25_001)
        await eventually { self.factory[1].sentCount == 1 }
        XCTAssertTrue(factory[0].sentFrames.isEmpty)
        XCTAssertEqual(1, factory[1].sentCount)
    }

    func testACleanServerCloseAlsoReconnects() async {
        let s = socket()
        s.connect("a1")
        factory.last.open(); factory.last.serverClose()
        await advance(2_001)
        await eventually { self.factory.count == 2 }
        XCTAssertEqual(2, factory.count)
        XCTAssertFalse(s.connected.value)
    }

    func testARefusedHandshakeKeepsRetryingBackingOffTo30Seconds() async {
        let s = socket()
        s.connect("a1")
        // 2 s like the web, then 4, 8, 16, 30, 30 … while the server stays away.
        for (i, wait) in [2_000, 4_000, 8_000, 16_000, 30_000, 30_000].enumerated() {
            factory.last.fail()
            await advance(Int64(wait) - 1)
            XCTAssertEqual(i + 1, factory.count, "retry \(i + 1) waits \(wait)ms")
            await advance(2)
            await eventually { self.factory.count == i + 2 }
            XCTAssertEqual(i + 2, factory.count)
        }
        XCTAssertEqual([2_000, 4_000, 8_000, 16_000, 30_000, 30_000], (1...6).map(s.backoff))
    }

    func testAnOpenSocketResetsTheBackoff() async {
        let s = socket()
        s.connect("a1")
        for _ in 0..<4 { factory.last.fail(); await advance(40_000) }
        await eventually { self.factory.count == 5 }
        factory.last.open()
        factory.last.fail()
        await advance(2_001)
        await eventually { self.factory.count == 6 }
        XCTAssertEqual(6, factory.count, "back to 2 s after a good connection")
        XCTAssertFalse(s.connected.value)
    }

    func testNudgeSkipsALongBackoff() async {
        let s = socket()
        s.connect("a1")
        for _ in 0..<5 { factory.last.fail(); await advance(40_000) }
        await eventually { self.factory.count == 6 }
        factory.last.fail() // now 30 s away
        s.nudge() // the network came back / the app came to the front
        XCTAssertEqual(7, factory.count)
        factory.last.fail()
        await advance(2_001)
        await eventually { self.factory.count == 8 }
        XCTAssertEqual(8, factory.count, "and the backoff starts over")
    }

    // ── The "reconnected" signal: frames may have been missed ───────────────

    private final class Counter { var n = 0 }

    private func reconnects(_ s: LiveSocket) -> (Counter, Subscription) {
        let c = Counter()
        let sub = s.reconnected.observe { c.n += 1 }
        return (c, sub)
    }

    func testTheFirstOpenIsNotAReconnect() {
        let s = socket(); let (got, sub) = reconnects(s); defer { sub.cancel() }
        s.connect("a1"); factory.last.open()
        XCTAssertEqual(0, got.n)
    }

    func testEveryReopenAfterADropSignalsAReconnect() async {
        let s = socket(); let (got, sub) = reconnects(s); defer { sub.cancel() }
        s.connect("a1"); factory.last.open()
        factory.last.fail(); await advance(2_001)
        await eventually { self.factory.count == 2 }
        XCTAssertEqual(0, got.n, "not until it is actually open again")
        factory.last.open()
        XCTAssertEqual(1, got.n)
        factory.last.serverClose(); await advance(2_001)
        await eventually { self.factory.count == 3 }
        factory.last.open()
        XCTAssertEqual(2, got.n)
    }

    func testFailedRetriesSignalOnceWhenTheyFinallyConnect() async {
        let s = socket(); let (got, sub) = reconnects(s); defer { sub.cancel() }
        s.connect("a1"); factory.last.open()
        for _ in 0..<3 { factory.last.fail(); await advance(40_000) }
        await eventually { self.factory.count == 4 }
        factory.last.open()
        XCTAssertEqual(1, got.n)
    }

    func testReopeningAfterABackgroundCloseIsAReconnect() {
        let s = socket(); let (got, sub) = reconnects(s); defer { sub.cancel() }
        s.connect("a1"); factory.last.open()
        s.disconnect() // backgrounded without live mode
        s.connect("a1"); factory.last.open()
        XCTAssertEqual(1, got.n, "frames were missed while closed")
    }

    func testANewAgentOrANewSignInIsNotAReconnect() {
        let s = socket(); let (got, sub) = reconnects(s); defer { sub.cancel() }
        s.connect("a1"); factory.last.open()
        s.connect("a2"); factory.last.open()
        s.signOut()
        s.connect("a2"); factory.last.open()
        XCTAssertEqual(0, got.n)
    }

    func testAfterSignOutNothingReconnects() async {
        let s = socket()
        s.connect("a1"); factory.last.open()
        s.signOut()
        factory.last.fail(); s.nudge()
        await advance(120_000)
        XCTAssertEqual(1, factory.count)
        XCTAssertFalse(s.connected.value)
    }

    func testAReplacedSocketThatOpensLateIsCancelledAndIgnored() {
        let s = socket(); let (got, sub) = reconnects(s); defer { sub.cancel() }
        s.connect("a1"); let stale = factory.last
        s.connect("a2"); let live = factory.last
        stale.open()
        XCTAssertTrue(stale.cancelled, "the stale handshake is torn down")
        XCTAssertFalse(s.connected.value)
        live.open()
        XCTAssertTrue(s.connected.value)
        XCTAssertEqual(0, got.n)
    }

    func testAReplacedSocketStillDrainingDoesNotDoubleFrames() async {
        let s = socket()
        var got = 0
        let sub = s.events.observe { _ in got += 1 }
        defer { sub.cancel() }
        s.connect("a1"); let old = factory.last; old.open()
        old.fail(); await advance(2_001)
        await eventually { self.factory.count == 2 }
        factory.last.open()
        old.frame(#"{"type":"new_message","conversationId":"c1"}"#)
        factory.last.frame(#"{"type":"new_message","conversationId":"c1"}"#)
        XCTAssertEqual(1, got)
    }

    func testABurstOfFramesArrivesInOrder() async {
        let s = socket()
        let stream = s.eventStream()
        s.connect("a1"); factory.last.open()
        for i in 0..<200 { factory.last.frame(#"{"type":"new_message","conversationId":"c\#(i)"}"#) }
        var got: [String] = []
        for await v in stream {
            got.append(v.str("conversationId")!)
            if got.count == 200 { break }
        }
        XCTAssertEqual((0..<200).map { "c\($0)" }, got)
        XCTAssertEqual(0, s.droppedFrames)
    }

    func testALaggingCollectorLosesFramesAndSaysSo() async {
        let s = socket()
        let stream = s.eventStream()
        s.connect("a1"); factory.last.open()
        for i in 0..<(LiveSocket.EVENT_BUFFER + 5) { factory.last.frame(#"{"type":"new_message","conversationId":"c\#(i)"}"#) }
        XCTAssertEqual(5, s.droppedFrames)
        var first: String?
        for await v in stream { first = v.str("conversationId"); break }
        XCTAssertEqual("c0", first, "the oldest frames are kept, the newest dropped")
    }

    func testDisconnectStopsReconnectingAndPinging() async {
        let s = socket()
        s.connect("a1"); factory.last.open()
        s.disconnect()
        XCTAssertEqual(1000, factory.last.closedWith)
        XCTAssertFalse(s.connected.value)
        factory.last.fail() // the close handshake reports back late
        await advance(60_000)
        XCTAssertEqual(1, factory.count)
        XCTAssertTrue(factory.last.sentFrames.isEmpty)
    }

    func testNudgeReconnectsAtOnceWhenDown() async {
        let s = socket()
        s.connect("a1"); factory.last.open(); factory.last.fail()
        s.nudge()
        XCTAssertEqual(2, factory.count, "no 2 s wait when the app comes back")
        await advance(2_001)
        XCTAssertEqual(2, factory.count, "the pending timer was cancelled")

        s.disconnect(); s.nudge()
        XCTAssertEqual(2, factory.count, "a socket closed on purpose (signed out) stays closed")
    }

    func testNudgeWhileConnectedDoesNothing() {
        let s = socket()
        s.connect("a1"); factory.last.open()
        s.nudge()
        XCTAssertEqual(1, factory.count)
    }

    func testCallbacksFromAReplacedSocketAreIgnored() async {
        let s = socket()
        s.connect("a1"); let old = factory.last; old.open()
        s.connect("a2"); factory.last.open()
        old.fail()
        XCTAssertTrue(s.connected.value, "the old socket's failure must not mark the new one down")
        await advance(2_001)
        XCTAssertEqual(2, factory.count)
    }
}
