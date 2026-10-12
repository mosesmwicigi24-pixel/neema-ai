import XCTest
@testable import NeemaCore

/// The coroutine-flow twins: signals, watched values, the async lock, single-flight reads and coalesced refetches.
final class FlowsTests: XCTestCase {
    func testSignalFansOutAndStopsAfterCancel() {
        let s = Signal<Int>()
        var a: [Int] = [], b: [Int] = []
        let sa = s.observe { a.append($0) }
        let sb = s.observe { b.append($0) }
        s.emit(1)
        sa.cancel()
        s.emit(2)
        XCTAssertEqual([1], a)
        XCTAssertEqual([1, 2], b)
        sb.cancel()
        XCTAssertEqual(0, s.subscriberCount)
    }

    func testWatchedHandsTheCurrentValueFirstAndDedupes() {
        let w = Watched<Bool>(false)
        var seen: [Bool] = []
        let sub = w.observe { seen.append($0) }
        w.update(false)
        w.update(true)
        w.update(true)
        w.value = true
        sub.cancel()
        XCTAssertEqual([false, true, true], seen)
    }

    func testAsyncLockSerialises() async {
        let lock = AsyncLock()
        let state = Watched<[String]>([])
        await withTaskGroup(of: Void.self) { group in
            for i in 0..<5 {
                group.addTask {
                    await lock.withLock {
                        state.value = state.value + ["in\(i)"]
                        try? await Task.sleep(nanoseconds: 2_000_000)
                        state.value = state.value + ["out\(i)"]
                    }
                }
            }
        }
        let log = state.value
        XCTAssertEqual(10, log.count)
        for i in stride(from: 0, to: 10, by: 2) {
            XCTAssertTrue(log[i].hasPrefix("in") && log[i + 1].hasPrefix("out") && log[i].dropFirst(2) == log[i + 1].dropFirst(3), "\(log)")
        }
    }

    func testSingleFlightSharesTheNextReadNeverAStaleOne() async throws {
        let started = Watched<Int>(0)
        let gate = AsyncLock()
        await gate.acquire()
        let flight = SingleFlight<Int> {
            started.value += 1
            let n = started.value
            if n == 1 { await gate.withLock {} }
            return n
        }
        let first = Task { try await flight.run() }
        await eventually { started.value == 1 }
        XCTAssertTrue(flight.inFlight)
        let second = Task { try await flight.run() }
        let third = Task { try await flight.run() }
        await settle()
        XCTAssertEqual(1, started.value, "callers during a read wait for the NEXT one")
        gate.release()
        let got1 = try await first.value
        XCTAssertEqual(1, got1)
        let got2 = try await second.value
        XCTAssertEqual(2, got2)
        let got3 = try await third.value
        XCTAssertEqual(2, got3, "the queued read is shared")
        XCTAssertEqual(2, started.value)
        XCTAssertFalse(flight.inFlight)
    }

    func testSingleFlightCancelAbandonsBothReads() async {
        let gate = AsyncLock()
        await gate.acquire()
        let flight = SingleFlight<Int> {
            await gate.withLock {}
            try Task.checkCancellation()
            return 1
        }
        let a = Task { try await flight.run() }
        await settle()
        let b = Task { try await flight.run() }
        await settle()
        flight.cancel()
        gate.release()
        do { _ = try await a.value; XCTFail() } catch { XCTAssertTrue(error is CancellationError) }
        do { _ = try await b.value; XCTFail() } catch { XCTAssertTrue(error is CancellationError) }
    }

    func testCoalescerFoldsABurstIntoOneRun() async {
        let clock = VirtualClock()
        let runs = Watched<Int>(0)
        let c = Coalescer(windowMs: 800, sleep: clock.sleeper) { runs.value += 1 }
        for _ in 0..<10 { c.kick() }
        await clock.advance(by: 799)
        XCTAssertEqual(0, runs.value)
        await clock.advance(by: 2)
        await eventually { runs.value == 1 }
        XCTAssertEqual(1, runs.value)
        c.kick()
        await clock.advance(by: 801)
        await eventually { runs.value == 2 }
        XCTAssertEqual(2, runs.value)
    }

    func testCoalescerNeverOverlapsAndRunsOnceMoreAfterASlowRun() async {
        let clock = VirtualClock()
        let gate = AsyncLock()
        await gate.acquire()
        let runs = Watched<Int>(0)
        let c = Coalescer(windowMs: 100, sleep: clock.sleeper) {
            runs.value += 1
            if runs.value == 1 { await gate.withLock {} }
        }
        c.kick()
        await clock.advance(by: 101)
        await eventually { runs.value == 1 }
        for _ in 0..<5 { c.kick(); await clock.advance(by: 101) }
        XCTAssertEqual(1, runs.value, "a kick during a slow run waits for it")
        gate.release()
        await eventually { runs.value == 2 }
        await clock.advance(by: 1000)
        await settle()
        XCTAssertEqual(2, runs.value, "however many kicks landed, one run follows")
    }
}
