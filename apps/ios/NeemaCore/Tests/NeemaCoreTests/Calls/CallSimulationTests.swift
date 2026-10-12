import Foundation
import XCTest
@testable import NeemaCore

/// Seeded random simulations of an agent's day on the softphone: WhatsApp and
/// Messenger, placing and answering, with the taps, server frames, network
/// failures, device failures, slow servers and timing a real phone sees, in
/// random order. After every step, and at the end of every run:
///
/// - nothing escapes (initiateCall returns, never throws; no task fails);
/// - no WebRTC peer is ever used after close() (on a phone: a native crash);
/// - with no call up, the call audio and the microphone are let go and every
///   peer is closed;
/// - once the dust settles, a clean call on each channel still connects.
///
/// A failure prints its seed and the steps that led there, so it replays
/// exactly. Android `calls/CallSimulationTest.kt` runs 2 000 days and 200
/// long shifts; the virtual clock here settles in real time, so the default
/// is 30 days and 3 shifts (`NEEMA_SIM_RUNS` scales it up; 100 took ~5 min).
@MainActor
final class CallSimulationTests: XCTestCase {
    /// SplitMix64: a small seeded generator with the same sequence on every platform.
    struct Rng {
        private var s: UInt64
        init(_ seed: Int) { s = UInt64(truncatingIfNeeded: seed) &* 0x9E37_79B9_7F4A_7C15 &+ 0x1234_5678 }
        mutating func next() -> UInt64 {
            s &+= 0x9E37_79B9_7F4A_7C15
            var z = s
            z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
            z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
            return z ^ (z >> 31)
        }
        mutating func int(_ n: Int) -> Int { Int(next() % UInt64(n)) }
        mutating func bool() -> Bool { next() & 1 == 1 }
        mutating func pick<T>(_ a: [T]) -> T { a[int(a.count)] }
    }

    @MainActor
    final class Sim {
        let fake = FakeCallApi()
        let throwing: CallResilienceTests.ThrowingApi
        let media = CallResilienceTests.FlakyMedia()
        let r: CallRig
        var rnd: Rng
        var log: [String] = []
        var placed: [Task<Result<Void, Error>, Never>] = []
        var incoming = 0
        var calls: CallManager { r.calls }
        var api: FakeCallApi { fake }
        var peers: [FakePeer] { media.peers.map { $0.inner } }

        init(seed: Int) {
            rnd = Rng(seed)
            let t = CallResilienceTests.ThrowingApi(fake)
            throwing = t
            r = CallRig(api: fake, wrap: { _ in t }, media: media)
        }

        func emit(_ kv: (String, String)...) {
            var o: [String: JSONValue] = [:]
            for (k, v) in kv { o[k] = .string(v) }
            r.frames.emit(.object(o))
        }
        var state: CallUiState { r.state }

        /// The ids a frame could be about: the live call, the last placed ones, a stranger's.
        func someId() -> String {
            rnd.pick([state.callId ?? "wacid.none", api.connectId, api.messengerConnectId, "wacid.in\(incoming)", "c_msg.in\(incoming)", "wacid.stranger"])
        }

        /// Lets the step's work land: lighter than `drain()` (thousands of steps).
        func settle() async {
            for _ in 0..<3 {
                for _ in 0..<20 { await Task.yield() }
                try? await Task.sleep(nanoseconds: 2_000_000)
            }
        }

        func check(_ where: String) -> String? {
            for (i, p) in peers.enumerated() where !p.usedAfterClose.isEmpty { return "\(`where`): peer \(i) used after close \(p.usedAfterClose)" }
            let s = state
            if s.phase == .idle || s.phase == .ended {
                if r.audio.inCall { return "\(`where`): call audio held with no call (\(s.phase))" }
                if r.audio.micService { return "\(`where`): microphone service up with no call (\(s.phase))" }
                for (i, p) in peers.enumerated() where !p.closed { return "\(`where`): peer \(i) still open with no call" }
            }
            return nil
        }

        func step(_ n: Int) async -> String? {
            let s = state
            var what = ""
            switch rnd.int(100) {
            case 0...11:
                let ch = rnd.bool() ? CallWords.WHATSAPP : CallWords.MESSENGER
                let name = rnd.pick(["Fr. Peter Kamau", "", nil] as [String?])
                let to = ch == CallWords.MESSENGER ? "7788990011" : "254712345678"
                placed.append(Task { await self.calls.initiateCall(to: to, name: name, conversationId: nil, channel: ch) })
                what = "place \(ch)"
            case 12...19: calls.hangup(); what = "hang up"
            case 20...25: calls.answer(); what = "answer"
            case 26...33:
                incoming += 1
                let m = rnd.bool()
                let id = m ? "c_msg.in\(incoming)" : "wacid.in\(incoming)"
                if m { api.messengerCalls.insert(id) }
                if m { emit(("type", "incoming_call"), ("call_id", id), ("from", "7788990011"), ("name", "Grace"), ("channel", CallWords.MESSENGER)) }
                else { emit(("type", "incoming_call"), ("call_id", id), ("from", "254712345678"), ("name", "Fr. Peter Kamau")) }
                what = "ring \(id)"
            case 34...40: let id = someId(); emit(("type", "outbound_answer"), ("call_id", id), ("sdp", "v=0 their-answer")); what = "answer frame \(id)"
            case 41...45:
                let id = someId()
                emit(("type", "call_status"), ("call_id", id), ("status", rnd.pick(["ringing", "accepted", "rejected", "completed", "failed"])))
                what = "status \(id)"
            case 46...51: let id = someId(); emit(("type", "call_ended"), ("call_id", id)); what = "ended \(id)"
            case 52...55:
                let id = someId()
                emit(("type", "call_answered"), ("call_id", id), ("by", rnd.pick(["Moses", "Grace Wanjiru"])))
                what = "answered elsewhere \(id)"
            case 56...58: let id = someId(); emit(("type", "media_update"), ("call_id", id), ("sdp", "v=0 renegotiate")); what = "media_update \(id)"
            case 59...66:
                guard let p = media.peers.last?.inner else { log.append("\(n): (no peer)"); return nil }
                let ev = rnd.pick([PeerEvent.connected, .connected, .interrupted, .ended])
                p.onEvent(ev); what = "peer \(ev)"
            case 67...72:
                // A device failure somewhere in the next WebRTC step.
                let st = rnd.pick(CallResilienceTests.Step.allCases); media.arm(st); what = "arm native fault \(st)"
            case 73...77:
                switch rnd.int(5) {
                case 0: api.connectError = apiError(409, "POST", "/admin/calls/connect", #"{"detail":"This customer hasn't granted call permission yet."}"#); what = "server: no permission"
                case 1: api.connectError = ApiError(status: 0, method: "POST", path: "/admin/calls/connect", body: "Connection reset"); what = "server: connection drop on connect"
                case 2: api.answerError = apiError(409, "POST", "/admin/calls/x/answer", #"{"detail":"call already answered by Grace"}"#); what = "server: taken elsewhere"
                case 3: throwing.connectFault = DeviceCallError("response"); what = "server: device error on connect"
                default: api.connectError = nil; api.answerError = nil; what = "server: healthy"
                }
            case 78...80:
                // A slow server: the next connect waits until released a few steps later.
                if api.connectGate == nil { api.connectGate = Deferred<Void>(); what = "server: slow connect" }
                else { api.connectGate?.complete(()); api.connectGate = nil; what = "server: slow connect answers" }
            case 81...83:
                if media.inner.sdpGate == nil { media.inner.sdpGate = Deferred<Void>(); what = "webrtc: slow SDP" }
                else { media.inner.sdpGate?.complete(()); media.peers.forEach { $0.inner.sdpGate?.complete(()) }; media.inner.sdpGate = nil; what = "webrtc: SDP done" }
            case 84...85: r.mic.toggle(); what = "mic permission \(r.mic ? "on" : "off")"
            case 86: calls.onMicResult(rnd.bool()); what = "mic prompt answered"
            case 87: r.foreground.value.toggle(); what = "app \(r.foreground.value ? "foreground" : "background")"
            case 88: r.connected.value.toggle(); what = "socket \(r.connected.value ? "up" : "down")"
            case 89...90: calls.toggleMute(); calls.toggleSpeaker(); what = "mute + speaker"
            case 91: calls.minimise(); calls.expand(); what = "minimise + expand"
            case 92: calls.redial(); what = "redial"
            case 93: calls.callback(); what = "call back"
            case 94: calls.dismiss(); what = "dismiss wrap-up"
            case 95: calls.endAndAnswer(); what = "end and answer waiting"
            case 96: calls.declineWaiting(); what = "decline waiting"
            default:
                let ms = rnd.pick([100, 1_000, 2_500, 5_000, 13_000] as [Int64])
                await r.clock.advance(by: ms); what = "wait \(ms)ms"
            }
            await settle()
            log.append("\(n): \(what) → \(state.phase)\(state.callId.map { " \($0)" } ?? "")")
            return check("step \(n) (\(what)) from \(s.phase)")
        }

        /// Every slow thing answers, time passes, the card is closed: the phone is at rest.
        func settleDown() async {
            api.connectGate?.complete(()); api.connectGate = nil
            media.inner.sdpGate?.complete(()); media.inner.sdpGate = nil
            media.peers.forEach { $0.inner.sdpGate?.complete(()) }
            media.faults.removeAll()
            api.connectError = nil; api.answerError = nil; throwing.connectFault = nil
            r.mic = true; r.connected.value = true; r.foreground.value = true
            for _ in 0..<3 {
                await r.clock.advance(by: 150_000); await settle()
                calls.hangup(); await settle()
                calls.dismiss(); await settle()
            }
            await r.clock.advance(by: 150_000); await settle()
        }
    }

    private var sims: [Sim] = []

    override func tearDown() async throws {
        for s in sims { s.r.stop() }
        sims.removeAll()
        await drain()
    }

    private func simulate(seed: Int, steps: Int, stats: inout [String: Int]) async {
        let sim = Sim(seed: seed)
        sims.append(sim)
        await sim.settle()
        func fail(_ msg: String) {
            XCTFail("seed \(seed) failed: \(msg)\n--- steps ---\n\(sim.log.suffix(40).joined(separator: "\n"))")
        }
        for i in 0..<steps {
            if let problem = await sim.step(i) { fail(problem); return }
        }
        await sim.settleDown()
        if let problem = sim.check("at rest") { fail(problem); return }
        if sim.state.phase != .idle { fail("at rest: \(sim.state.phase)"); return }
        // Every placement came back (never threw).
        for d in sim.placed { _ = await d.value }
        // …and the phone still calls, on both channels.
        for ch in [CallWords.WHATSAPP, CallWords.MESSENGER] {
            let to = ch == CallWords.MESSENGER ? "7788990011" : "254712345678"
            let t = Task { await sim.calls.initiateCall(to: to, name: "Grace", conversationId: nil, channel: ch) }
            await sim.settle()
            let res = await t.value
            if !res.isSuccess { fail("a clean \(ch) call after the run: \(res.failureMessage ?? "?")"); return }
            if ch == CallWords.WHATSAPP { sim.emit(("type", "outbound_answer"), ("call_id", sim.api.connectId), ("sdp", "v=0 their-answer")) }
            else { sim.emit(("type", "call_answered"), ("call_id", sim.api.messengerConnectId)) }
            await sim.settle()
            sim.media.peers.last!.inner.onEvent(.connected); await sim.settle()
            if sim.state.phase != .inCall { fail("\(ch) connects: \(sim.state.phase)"); return }
            sim.calls.hangup(); await sim.settle(); await sim.r.clock.advance(by: 10_000); await sim.settle(); sim.calls.dismiss(); await sim.settle()
            if let problem = sim.check("after the clean \(ch) call") { fail(problem); return }
            if sim.r.audio.inCall { fail("audio held after the clean \(ch) call"); return }
        }
        stats["runs", default: 0] += 1
        stats["peers", default: 0] += sim.media.peers.count
        stats["placements", default: 0] += sim.placed.count
        stats["reachedInCall", default: 0] += sim.log.contains { $0.contains("→ inCall") } ? 1 : 0
        stats["nativeFaults", default: 0] += sim.log.filter { $0.contains("native fault") }.count
        sim.r.stop()
    }

    private static var runs: Int { Int(ProcessInfo.processInfo.environment["NEEMA_SIM_RUNS"] ?? "") ?? 30 }

    func testRandomAgentDays() async {
        var stats: [String: Int] = [:]
        let n = Self.runs
        for seed in 1...n { await simulate(seed: seed, steps: 60, stats: &stats) }
        print("CALL SIMULATION: \(stats.sorted { $0.key < $1.key })")
        XCTAssertEqual(stats["runs"], n)
        XCTAssertTrue((stats["reachedInCall"] ?? 0) > n / 10, "the simulation reaches live calls, not just failures: \(stats)")
    }

    func testLongShifts() async {
        var stats: [String: Int] = [:]
        let n = max(1, Self.runs / 10)
        for seed in 10_001...(10_000 + n) { await simulate(seed: seed, steps: 300, stats: &stats) }
        print("CALL SIMULATION (long): \(stats.sorted { $0.key < $1.key })")
        XCTAssertEqual(stats["runs"], n)
    }
}
