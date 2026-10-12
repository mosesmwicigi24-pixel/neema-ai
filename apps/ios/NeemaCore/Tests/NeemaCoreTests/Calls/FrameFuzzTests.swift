import Foundation
import XCTest
@testable import NeemaCore

/// Garbage in, no crash out (2026-09-27, "Neema closed because this app has a
/// bug"). Thousands of seeded random socket frames - every event type the
/// server publishes plus unknown ones, each field any JSON shape - go straight
/// into CallManager.onFrame (no safety net in between: a trap fails the run),
/// and the phone still rings a real call afterwards. The Calls log is fuzzed
/// the same way: random live updates never repeat a lazy-list key.
/// Android `calls/FrameFuzzTest.kt`.
@MainActor
final class FrameFuzzTests: XCTestCase {
    private var rigs: [CallRig] = []

    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
    }

    private func rig() async -> CallRig {
        let r = CallRig()
        rigs.append(r)
        await r.settle()
        return r
    }

    private let types = [
        "incoming_call", "call_answered", "call_ended", "call_update", "call_permission", "call_status",
        "calling_restricted", "call_settings", "media_update", "outbound_answer", "notification", "pong", "", "???",
    ]
    private let keys = [
        "call_id", "from", "external_id", "name", "conversation_id", "person_id", "channel", "sdp", "sdp_type",
        "status", "outcome", "duration", "agent_id", "agent_name", "version", "reasons", "at", "call", "wa_id",
        "response", "is_permanent", "expiration_timestamp", "psid", "type",
    ]
    private let ids = ["wacid.1", "wacid.2", "c_1", "pending"]

    /// A random JSON value of any shape (nested at most two deep, as Android's).
    private func value(_ rnd: inout CallSimulationTests.Rng, depth: Int = 0) -> JSONValue {
        switch rnd.int(depth > 1 ? 8 : 11) {
        case 0: return .null
        case 1: return .string("")
        case 2: return .string(rnd.pick(["wacid.1", "wacid.2", "c_1", "pending", "254712345678", "messenger", "whatsapp"]))
        case 3: return .number(Double(Int64(bitPattern: rnd.next())))
        case 4: return .number(Double(rnd.next() >> 11) / Double(1 << 53) * 1e12)
        case 5: return .bool(rnd.bool())
        case 6: return .string(rnd.pick(["NaN", "-1", "1e309", "ringing", "rejected", "offer", "answer", "v=0\r\n", "ü👩🏽‍💻",
                                        String(repeating: "x", count: 5000)]))
        case 7: return .string(rnd.pick(["2026-09-27T18:35:00Z", "2026-09-27 18:35:00", "not a date", "+0000", "9999999999"]))
        case 8:
            var a: [JSONValue] = []
            for _ in 0..<rnd.int(4) { a.append(value(&rnd, depth: depth + 1)) }
            return .array(a)
        case 9:
            var o: [String: JSONValue] = [:]
            for _ in 0..<rnd.int(4) { o[rnd.pick(keys)] = value(&rnd, depth: depth + 1) }
            return .object(o)
        default:
            return .object(["call_id": value(&rnd, depth: depth + 1), "status": value(&rnd, depth: depth + 1),
                            "started_at": value(&rnd, depth: depth + 1)])
        }
    }

    private func frame(_ rnd: inout CallSimulationTests.Rng) -> JSONValue {
        var m: [String: JSONValue] = [:]
        m["type"] = rnd.int(10) == 0 ? value(&rnd) : .string(rnd.pick(types))
        for _ in 0..<rnd.int(8) { m[rnd.pick(keys)] = value(&rnd) }
        if rnd.bool() { m["call_id"] = .string(rnd.pick(ids)) }
        return .object(m)
    }

    /// Lets the frame's own hops run (lighter than `drain()`: thousands of frames).
    private func hop() async { for _ in 0..<10 { await Task.yield() } }

    func testRandomFramesNeverThrowAndThePhoneStillRings() async {
        let r = await rig()
        var rnd = CallSimulationTests.Rng(20260927)
        for i in 0..<4000 {
            r.calls.onFrame(frame(&rnd))
            await hop()
            if i % 250 == 0 { await r.advance(15_000) }
        }
        // Whatever state the storm left, a fresh call still rings this phone.
        for id in ids {
            r.calls.onFrame(.object(["type": .string("call_ended"), "call_id": .string(id), "outcome": .string("missed")]))
        }
        await r.advance(120_000)
        r.calls.dismiss()
        await r.settle()
        r.calls.onFrame(.object(["type": .string("incoming_call"), "call_id": .string("wacid.fresh"),
                                 "from": .string("254700000001"), "name": .string("Grace Wanjiku")]))
        await r.settle()
        XCTAssertEqual("wacid.fresh", r.state.callId)
        XCTAssertEqual(CallPhase.ringing, r.state.phase)
    }

    /// The row keys are `rowKeys` (core); the day headers between them are the
    /// app's `logItems` (CallsScreenModel.swift), which numbers a repeated day.
    func testRandomLiveUpdatesNeverRepeatALogKey() {
        var rnd = CallSimulationTests.Rng(927)
        let days: [String?] = ["2026-09-27T12:00:00Z", "2026-09-26T08:00:00Z", "2026-09-12T10:00:00Z", "2026-08-01T00:00:00Z", nil, "garbage"]
        var log = (0..<60).map { Call(callId: "c\($0)", status: "completed", startedAt: days[$0 % 4]) }
            .sorted { ($0.startedAt ?? "") > ($1.startedAt ?? "") }
        for _ in 0..<3000 {
            let id = rnd.bool() ? "c\(rnd.int(80))" : "n\(rnd.int(500))"
            let row = Call(callId: id, status: "missed", startedAt: rnd.pick(days))
            if log.contains(where: { $0.callId == id }) { log = log.map { $0.callId == id ? row : $0 } }
            else { log = insertByTime(log, row) ?? log }
            let keys = rowKeys(log)
            XCTAssertEqual(keys.count, Set(keys).count, "a repeated lazy key crashes the Calls screen")
        }
    }
}
