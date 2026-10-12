import Foundation
import XCTest
@testable import NeemaCore

/// The build's pinned instant (Android pins the same for its screenshot goldens).
let PINNED = ISO8601DateFormatter().date(from: "2026-09-25T09:00:00Z")!

private var jtiSeq = 0
private let jtiLock = NSLock()

func fakeJwt(_ sub: String = "a1", expiresInSec: Int64 = 365 * 24 * 3600) -> String {
    func b64(_ s: String) -> String {
        var out = Data(s.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
        while out.hasSuffix("=") { out.removeLast() }
        return out
    }
    let exp = AppClock.now() / 1000 + expiresInSec
    // A unique jti: two tokens minted in the same second must still differ.
    let jti: Int = jtiLock.sync { jtiSeq += 1; return jtiSeq }
    return "\(b64(#"{"alg":"HS256","typ":"JWT"}"#)).\(b64("{\"sub\":\"\(sub)\",\"exp\":\(exp),\"type\":\"access\",\"jti\":\"t\(jti)\"}")).sig"
}

struct PlainError: Error, LocalizedError {
    let message: String?
    init(_ message: String? = nil) { self.message = message }
    var errorDescription: String? { message }
}

/// Polls `cond` until it holds (or `timeout` passes); the fake socket and
/// clock hand work to the cooperative pool, so assertions wait for it to land.
@discardableResult
func eventually(timeout: TimeInterval = 3, _ cond: @escaping () -> Bool) async -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if cond() { return true }
        await Task.yield()
        try? await Task.sleep(nanoseconds: 2_000_000)
    }
    return cond()
}

/// Lets queued tasks run for a moment, for "nothing should happen" checks.
func settle(ms: UInt64 = 30) async {
    for _ in 0..<10 { await Task.yield() }
    try? await Task.sleep(nanoseconds: ms * 1_000_000)
}

/// A virtual clock for the socket's and auth layer's timers: `sleep` parks a
/// task until `advance` moves time past its wake-up — the Swift twin of
/// kotlinx's `runTest` scheduler.
final class VirtualClock: @unchecked Sendable {
    private let lock = NSLock()
    private(set) var now: Int64 = 0
    private var seq = 0
    private var timers: [(at: Int64, seq: Int, cont: CheckedContinuation<Void, Error>)] = []
    private var cancelledEarly: Set<Int> = []
    /// Every wait asked for, in ms, in order.
    private(set) var waits: [Int64] = []

    var sleeper: Sleeper { { ms in try await self.sleep(ms) } }

    func sleep(_ ms: Int64) async throws {
        if Task.isCancelled { throw CancellationError() }
        let id: Int = lock.sync { seq += 1; waits.append(ms); return seq }
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                lock.sync {
                    if cancelledEarly.remove(id) != nil { c.resume(throwing: CancellationError()); return }
                    timers.append((now + ms, id, c))
                }
            }
        } onCancel: {
            let c: CheckedContinuation<Void, Error>? = lock.sync {
                if let i = timers.firstIndex(where: { $0.seq == id }) { return timers.remove(at: i).cont }
                cancelledEarly.insert(id)
                return nil
            }
            c?.resume(throwing: CancellationError())
        }
    }

    /// Moves time forward, firing every timer due on the way (in order) and letting each run.
    func advance(by ms: Int64) async {
        // Tasks spawned a moment ago must reach their `sleep` before time moves.
        await settle(ms: 20)
        let target = now + ms
        while true {
            let next: (at: Int64, seq: Int, cont: CheckedContinuation<Void, Error>)? = lock.sync {
                guard let i = timers.indices.min(by: { (timers[$0].at, timers[$0].seq) < (timers[$1].at, timers[$1].seq) }), timers[i].at <= target else { return nil }
                let t = timers.remove(at: i)
                now = t.at
                return t
            }
            guard let t = next else { break }
            t.cont.resume()
            await settle(ms: 15)
        }
        lock.sync { now = target }
        await settle(ms: 15)
    }

    var pending: Int { lock.sync { timers.count } }
}

extension XCTestCase {
    /// Runs `body` and hands back the `ApiError` it threw.
    func expectApi(_ body: () async throws -> Any, file: StaticString = #filePath, line: UInt = #line) async -> ApiError? {
        do { _ = try await body() } catch let e as ApiError { return e } catch { XCTFail("expected ApiError, got \(error)", file: file, line: line); return nil }
        XCTFail("expected ApiError", file: file, line: line)
        return nil
    }

    func expectAuth(_ body: () async throws -> Any, file: StaticString = #filePath, line: UInt = #line) async -> AuthError? {
        do { _ = try await body() } catch let e as AuthError { return e } catch { XCTFail("expected AuthError, got \(error)", file: file, line: line); return nil }
        XCTFail("expected AuthError", file: file, line: line)
        return nil
    }
}
