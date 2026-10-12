import Foundation
import XCTest
@testable import NeemaCore

/// A call must ring the agent in every realistic situation. End to end: the
/// real `LiveSocket` on a fake WebSocket, the real HTTP client on a stateful
/// fake backend that behaves like routers/whatsapp_webhook.py +
/// routers/admin.py (the call log, the redis answer lock, the 2-minute stale
/// sweep), and one `CallManager` per phone. Only the device (WebRTC, speaker,
/// ringtone, the alert) is faked. Android `calls/CallRingsEverywhereTest.kt`.
@MainActor
final class CallRingsEverywhereTests: XCTestCase {
    nonisolated static let BASE: Int64 = 1_790_409_600_000   // 2026-09-26T08:00:00Z

    /// WhatsApp Cloud API + the Neema backend, for calls.
    final class Backend: @unchecked Sendable {
        final class Row: @unchecked Sendable {
            let callId: String; let waId: String?; let name: String?; let direction: String; var status: String; let startedAt: Int64
            init(_ callId: String, _ waId: String?, _ name: String?, _ direction: String, _ status: String, _ startedAt: Int64) {
                self.callId = callId; self.waId = waId; self.name = name; self.direction = direction; self.status = status; self.startedAt = startedAt
            }
        }
        let fake: FakeNeema
        let clock = VirtualClock()
        private let lock = NSLock()
        private var _rows: [Row] = []
        var rows: [Row] { lock.sync { _rows } }
        var phones: [Phone] = []
        /// The redis `wa:call:answered:{id}` lock (calls_answer): set once per call.
        private var _answeredBy: [String: String] = [:]
        var answeredBy: [String: String] { lock.sync { _answeredBy } }
        var now: Int64 { CallRingsEverywhereTests.BASE + clock.now }

        private static func id(_ path: String) -> String {
            let parts = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
            return parts.count > 3 ? (parts[3].removingPercentEncoding ?? parts[3]) : ""
        }

        init() {
            fake = Fixtures.withFixtures()
            CallsFixtures.install(fake)
            // list_calls: the stale sweep, then newest first.
            fake.on("GET", "/admin/calls") { [unowned self] _, _ in
                let t = self.now
                let rows: [Row] = self.lock.sync {
                    for r in self._rows where r.status == "ringing" && t - r.startedAt > 120_000 { r.status = "missed" }
                    return self._rows
                }
                let body = "[" + rows.sorted { $0.startedAt > $1.startedAt }.map { r in
                    CallsFixtures.row("k-\(r.callId)", r.callId, r.waId, r.name, r.direction, r.status, nil, nil, Fmt.iso(r.startedAt), nil, "none", false)
                }.joined(separator: ",") + "]"
                return (200, body)
            }
            fake.on("GET", "/admin/calls/[^/]+/offer") { req, _ in (200, CallsFixtures.offer(Backend.id(req.path))) }
            // calls_answer: one phone wins the lock; the others get 409.
            fake.on("POST", "/admin/calls/[^/]+/answer") { [unowned self] req, _ in
                let cid = Backend.id(req.path)
                let won: Bool = self.lock.sync {
                    if self._answeredBy[cid] != nil { return false }
                    self._answeredBy[cid] = "agent"
                    if let r = self._rows.first(where: { $0.callId == cid && $0.status == "ringing" }) { r.status = "answered" }
                    return true
                }
                return won ? (200, "{\"ok\":true,\"call_id\":\"\(cid)\"}") : (409, #"{"detail":"call already answered"}"#)
            }
            // calls_terminate: Meta ends the call, then its terminate webhook publishes call_ended.
            fake.on("POST", "/admin/calls/[^/]+/terminate") { [unowned self] req, _ in
                let cid = Backend.id(req.path)
                self.markEnded(cid)
                onMain { self.publish(#"{"type": "call_ended", "call_id": "\#(cid)", "status": "COMPLETED", "duration": null}"#) }
                return (200, "{\"ok\":true,\"call_id\":\"\(cid)\"}")
            }
            fake.on("POST", "/admin/calls/[^/]+/recording") { req, _ in
                (200, "{\"ok\":true,\"call_id\":\"\(Backend.id(req.path))\",\"will_transcribe\":false}")
            }
        }

        /// A customer rings: record_ringing, then publish incoming_call to every connected dashboard.
        @MainActor func ring(_ cid: String, from: String = "254712345678", name: String? = "Fr. Peter Kamau") {
            lock.sync { _rows.append(Row(cid, from, name, "inbound", "ringing", now)) }
            let n = name.map { "\"\($0)\"" } ?? "null"
            publish(#"{"type": "incoming_call", "call_id": "\#(cid)", "from": "\#(from)", "name": \#(n), "at": "\#(now / 1000)"}"#)
        }

        private func markEnded(_ cid: String) {
            lock.sync {
                if let r = _rows.first(where: { $0.callId == cid }), !["ended", "missed", "declined", "callback"].contains(r.status) {
                    r.status = r.status == "answered" ? "ended" : "missed"
                }
            }
        }

        /// Meta's terminate webhook: mark_ended, then call_ended.
        @MainActor func metaTerminate(_ cid: String) {
            markEnded(cid)
            publish(#"{"type": "call_ended", "call_id": "\#(cid)", "status": "COMPLETED", "duration": null}"#)
        }

        /// websocket.py: every frame to every CONNECTED socket (a dropped one hears nothing).
        @MainActor func publish(_ json: String) {
            for p in phones where p.host.socket.connected.value { p.host.sockets.last.frame(json) }
        }
    }

    @MainActor
    final class Phone {
        let backend: Backend
        let host: TestHost
        let ringer = FakeRinger()
        let media = FakeMedia()
        let audio = FakeAudio()
        let calls: CallManager
        init(_ backend: Backend, foreground: Bool = true) {
            self.backend = backend
            host = TestHost(fake: backend.fake, clock: backend.clock)
            host.foreground.value = foreground
            let h = host
            calls = CallManager(api: NeemaCallApi(host.api), events: host.socket.events, connected: host.socket.connected, foreground: host.foreground,
                                signedIn: { h.session.value != nil }, media: media, ringer: ringer, audio: audio, micGranted: { true },
                                now: { backend.now }, sleep: backend.clock.sleeper)
            backend.phones.append(self)
        }
        var state: CallUiState { calls.state.value }
        var polls: Int { backend.fake.callsTo("GET", "/admin/calls").count }
        func start() { calls.start() }
        /// The session watcher opens the socket; the server accepts it.
        func connect() { host.socket.connect(Fixtures.ME_ID); host.sockets.last.open() }
        /// The network drops; reconnect attempts every 2 s are refused until `restore`.
        func dropNetwork() { host.sockets.last.fail() }
        func restore() async { await backend.clock.advance(by: 2_000); host.sockets.last.open(); await drain() }
    }

    private var phones: [Phone] = []

    override func setUp() async throws { AppClock.pin(to: Date(timeIntervalSince1970: TimeInterval(Self.BASE) / 1000)) }
    override func tearDown() async throws {
        for p in phones { p.calls.stop(); p.host.logout() }
        phones.removeAll()
        await drain()
        AppClock.reset()
    }

    private func phone(_ backend: Backend = Backend(), foreground: Bool = true) async -> Phone {
        let p = Phone(backend, foreground: foreground)
        phones.append(p)
        p.start(); p.connect()
        await drain()
        return p
    }
    private func advance(_ b: Backend, _ ms: Int64) async { await b.clock.advance(by: ms); await drain() }

    // ── 1. The app in front ──────────────────────────────────────────────
    func testAppInFrontRingsTheInstantTheFrameArrives() async {
        let p = await phone()
        p.backend.ring("wacid.F1"); await drain()
        XCTAssertEqual(p.state.phase, .ringing)
        XCTAssertEqual(p.state.callId, "wacid.F1")
        XCTAssertEqual(p.state.name, "Fr. Peter Kamau")
        XCTAssertTrue(p.ringer.ringing)
        XCTAssertTrue(p.ringer.posted.isEmpty, "the card is the alert: no system notification in front")
    }

    // ── 2. Backgrounded, socket live ─────────────────────────────────────
    func testBackgroundedWithTheSocketLiveRingsAndNotifies() async {
        let p = await phone(foreground: false)
        p.backend.ring("wacid.B1", name: nil); await drain()
        XCTAssertEqual(p.state.phase, .ringing)
        XCTAssertTrue(p.ringer.ringing)
        XCTAssertEqual(p.ringer.posted.count, 1)
        XCTAssertEqual(p.ringer.posted[0].callId, "wacid.B1"); XCTAssertEqual(p.ringer.posted[0].who, "+254712345678"); XCTAssertEqual(p.ringer.posted[0].from, "254712345678")
        // Tapping the alert's Answer routes back through the app.
        p.host.foreground.value = true
        p.calls.handleAction("answer", id: "wacid.B1"); await drain()
        XCTAssertEqual(p.state.phase, .connecting)
        XCTAssertFalse(p.ringer.showing)
        XCTAssertTrue(p.backend.fake.called("POST", "/admin/calls/wacid.B1/answer"))
    }

    // ── 3. The socket is down when the call arrives ──────────────────────
    func testSocketDownThePollCatchesTheCallWithinTheWebsCadence() async {
        let p = await phone()
        await advance(p.backend, 1_000)
        p.dropNetwork(); await drain()
        p.backend.ring("wacid.D1"); await drain()
        XCTAssertEqual(p.state.phase, .idle, "the frame was lost")
        await advance(p.backend, 11_000)   // the 12 s idle poll started when the app did
        XCTAssertEqual(p.state.phase, .ringing)
        XCTAssertEqual(p.state.callId, "wacid.D1")
        XCTAssertTrue(p.ringer.ringing)
    }

    func testSocketDownTheReconnectCatchesTheCallAtOnce() async {
        let p = await phone()
        await advance(p.backend, 1_000)
        p.dropNetwork(); await drain()
        p.backend.ring("wacid.D2"); await drain()
        let polls = p.polls
        await p.restore()   // 2 s later, well before the 12 s tick
        XCTAssertEqual(p.polls, polls + 1)
        XCTAssertEqual(p.state.phase, .ringing)
        XCTAssertEqual(p.state.callId, "wacid.D2")
    }

    func testSocketDownTheCustomersHangUpIsCaughtWithin2500ms() async {
        let p = await phone()
        p.backend.ring("wacid.D3"); await drain()
        p.dropNetwork(); await drain()
        await advance(p.backend, 700)
        p.backend.metaTerminate("wacid.D3"); await drain()   // call_ended lost; the row is "missed" now
        await advance(p.backend, 2_500)
        XCTAssertEqual(p.state.phase, .ended)
        XCTAssertEqual(p.state.outcome, .missed())
        XCTAssertFalse(p.ringer.ringing)
    }

    // ── 4. Process killed; started again ─────────────────────────────────
    func testProcessRestartedRingsACallAlreadyRinging() async {
        let backend = Backend()
        backend.ring("wacid.R1")   // rang while the process was dead: nobody heard the frame
        await advance(backend, 4_000)
        // The new process: no screen (background), a stored session, a ringing alert left behind by the dead process.
        let p = Phone(backend, foreground: false)
        phones.append(p)
        p.ringer.showing = true
        p.start(); await drain()
        XCTAssertFalse(p.ringer.showing, "the dead process's alert is cleared")
        XCTAssertEqual(p.state.phase, .idle)
        p.connect(); await drain()   // the socket reconnects from the stored session
        XCTAssertEqual(p.state.phase, .ringing, "found by the catch-up poll, not 12 s later")
        XCTAssertEqual(p.ringer.posted.count, 1)
        XCTAssertEqual(p.ringer.posted[0].callId, "wacid.R1"); XCTAssertEqual(p.ringer.posted[0].who, "Fr. Peter Kamau"); XCTAssertEqual(p.ringer.posted[0].from, "254712345678")
    }

    func testAfterSignOutNothingIsPolledOrRung() async {
        let p = await phone()
        p.host.logout(); await drain()
        let polls = p.polls
        p.backend.ring("wacid.S1"); await drain()
        await advance(p.backend, 60_000)
        XCTAssertEqual(p.polls, polls)
        XCTAssertEqual(p.state.phase, .idle)
    }

    // ── 5. The screen is locked ──────────────────────────────────────────
    func testScreenLockedRingsThroughTheAlert() async {
        let p = await phone()
        // Locking the screen stops the scene: the app is no longer in front.
        p.host.foreground.value = false; await drain()
        p.backend.ring("wacid.L1", name: "Rev. Mary Achieng"); await drain()
        XCTAssertTrue(p.ringer.ringing)
        XCTAssertEqual(p.ringer.posted.count, 1)
        XCTAssertEqual(p.ringer.posted[0].callId, "wacid.L1", "the alert carries the call")
        XCTAssertTrue(p.ringer.showing)
        // Unlocked into the app: the card takes over, the alert goes.
        p.host.foreground.value = true; await drain()
        XCTAssertFalse(p.ringer.showing)
        XCTAssertEqual(p.state.phase, .ringing)
        XCTAssertTrue(p.ringer.ringing)
    }

    func testScreenLockedWithTheSocketAsleepStillRings() async {
        let p = await phone()
        p.host.foreground.value = false; await drain()
        p.dropNetwork(); await drain()   // the system cut the connection
        p.backend.ring("wacid.L2"); await drain()
        await advance(p.backend, 12_000)
        XCTAssertEqual(p.state.phase, .ringing)
        XCTAssertEqual(p.ringer.posted.count, 1)
        XCTAssertEqual(p.ringer.posted[0].callId, "wacid.L2")
    }

    // ── 6. Two agents, two phones ────────────────────────────────────────
    func testWhenOnePhoneAnswersTheOtherStopsRingingWithin2500ms() async {
        let backend = Backend()
        let a = await phone(backend)
        let b = await phone(backend, foreground: false)
        await advance(backend, 5_000)   // mid-way through both phones' 12 s idle wait
        backend.ring("wacid.T1"); await drain()
        XCTAssertEqual(a.state.phase, .ringing)
        XCTAssertEqual(b.state.phase, .ringing)
        XCTAssertTrue(b.ringer.showing)
        a.calls.answer(); await drain()
        XCTAssertEqual(a.state.phase, .connecting)
        XCTAssertEqual(Array(backend.answeredBy.keys), ["wacid.T1"])
        // No frame tells B; its 2.5 s ringing poll sees the row "answered".
        await advance(backend, 2_500)
        XCTAssertEqual(b.state.phase, .ended)
        XCTAssertEqual(b.state.outcome, .answeredElsewhere(agent: nil))
        XCTAssertFalse(b.ringer.ringing)
        XCTAssertFalse(b.ringer.showing)
        XCTAssertFalse(backend.fake.called("POST", "/admin/calls/wacid.T1/terminate"), "B must not end A's live call")
        XCTAssertEqual(a.state.phase, .connecting)
    }

    func testBothPhonesAnswerAtOnceTheLoserBacksOffQuietly() async {
        let backend = Backend()
        let a = await phone(backend)
        let b = await phone(backend)
        backend.ring("wacid.T2"); await drain()
        // A's answer reaches the server a moment before B's (the lock decides the rest).
        a.calls.answer(); await drain()
        b.calls.answer(); await drain()
        XCTAssertEqual(b.state.phase, .ended)
        XCTAssertEqual(b.state.outcome, .answeredElsewhere(agent: nil))
        XCTAssertFalse(backend.fake.called("POST", "/admin/calls/wacid.T2/terminate"))
        await advance(backend, 4_000)
        XCTAssertEqual(b.state.phase, .idle, "a neutral wrap-up closes by itself")
        XCTAssertEqual(a.state.phase, .connecting)
    }

    // ── 7. The customer hangs up while it rings ──────────────────────────
    func testCustomerHangsUpWhileRingingOnEveryPhone() async {
        let backend = Backend()
        let a = await phone(backend)
        let b = await phone(backend, foreground: false)
        backend.ring("wacid.H1"); await drain()
        backend.metaTerminate("wacid.H1"); await drain()
        for p in [a, b] {
            XCTAssertEqual(p.state.phase, .ended)
            XCTAssertFalse(p.ringer.ringing); XCTAssertFalse(p.ringer.showing)
        }
        await advance(backend, 1_000)
        XCTAssertEqual(a.state.outcome, .missed())
        XCTAssertEqual(b.state.outcome, .missed())
        XCTAssertFalse(backend.fake.called("POST", "/admin/calls/wacid.H1/terminate"))
    }

    // ── 8. A second call during a live call ──────────────────────────────
    func testASecondCallDuringALiveCallWaitsThenRingsWhenTheFirstEnds() async {
        let p = await phone()
        p.backend.ring("wacid.C1"); await drain()
        p.calls.answer(); await drain()
        p.media.peer.onEvent(.connected); await drain()
        XCTAssertEqual(p.state.phase, .inCall)
        p.backend.ring("wacid.C2", from: "254799999999", name: "Sr. Agnes Wairimu"); await drain()
        // As the web: the live call is untouched, nothing rings over it.
        XCTAssertEqual(p.state.phase, .inCall)
        XCTAssertEqual(p.state.callId, "wacid.C1")
        XCTAssertEqual(p.ringer.ringStarts, 1)
        XCTAssertEqual(p.state.waiting?.callId, "wacid.C2", "a banner, not a take-over")
        await advance(p.backend, 30_000)
        p.calls.hangup(); await drain()
        await eventually { p.state.phase == .ringing }
        XCTAssertEqual(p.state.phase, .ringing, "the waiting customer rings through at once")
        XCTAssertEqual(p.state.callId, "wacid.C2")
        XCTAssertEqual(p.state.name, "Sr. Agnes Wairimu")
        await eventually { p.backend.fake.called("POST", "/admin/calls/wacid.C1/recording") }
        XCTAssertTrue(p.backend.fake.called("POST", "/admin/calls/wacid.C1/recording"))
    }

    // ── 9. call_ended for a call we never saw ────────────────────────────
    func testCallEndedForACallNeverSeenChangesNothing() async {
        let p = await phone()
        let before = p.backend.fake.calls.count
        p.backend.publish(#"{"type": "call_ended", "call_id": "wacid.X1", "status": "COMPLETED", "duration": 12}"#); await drain()
        XCTAssertEqual(p.state.phase, .idle)
        XCTAssertEqual(p.backend.fake.calls.count, before, "no request")
        XCTAssertEqual(p.ringer.ringStarts, 0)
        // And a ringing call carries on through someone else's end.
        p.backend.ring("wacid.X2"); await drain()
        p.backend.publish(#"{"type": "call_ended", "call_id": "wacid.X3", "status": "COMPLETED", "duration": 12}"#); await drain()
        XCTAssertEqual(p.state.phase, .ringing)
    }
}
