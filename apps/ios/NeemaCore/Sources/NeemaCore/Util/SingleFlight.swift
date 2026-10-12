import Foundation

/// One read of a resource on the wire at a time. A caller that arrives while a
/// read is in flight does not start a second one: it shares the NEXT read,
/// which starts the moment the current one ends — so its answer never predates
/// the caller's own reason to ask (a save that just landed, a socket frame).
/// However many callers pile up (a poll tick, a reconnect, a return to the
/// app, a pull-to-refresh and three saves), at most one read runs and one waits.
public final class SingleFlight<T: Sendable>: @unchecked Sendable {
    private final class Flight: @unchecked Sendable {
        var task: Task<T, Error>!
        var done = false
    }

    private let lock = NSLock()
    private var running: Flight?
    private var queued: Flight?
    private let block: @Sendable () async throws -> T

    public init(_ block: @escaping @Sendable () async throws -> T) { self.block = block }

    /// True while a read is on the wire.
    public var inFlight: Bool {
        lock.lock(); defer { lock.unlock() }
        return running.map { !$0.done } ?? false
    }

    /// Abandon the read on the wire and the one waiting behind it (sign-out,
    /// a switch of agent): their requests are cancelled and their callers
    /// see a `CancellationError`. The next `run` starts afresh.
    public func cancel() {
        lock.lock()
        let q = queued, r = running
        queued = nil; running = nil
        lock.unlock()
        q?.task.cancel(); r?.task.cancel()
    }

    public func run() async throws -> T {
        let task: Task<T, Error> = lock.sync {
            if let q = queued, !q.done { return q.task }
            let prev = running.flatMap { $0.done ? nil : $0 }
            let flight = Flight()
            let block = self.block
            flight.task = Task { [weak self] in
                defer { self?.lock.sync { flight.done = true } }
                // A queued read starts only once the one ahead of it is over (success or not).
                if let p = prev { _ = try? await p.task.value }
                if let self = self {
                    self.lock.sync {
                        if self.queued === flight { self.queued = nil }
                        self.running = flight
                    }
                }
                try Task.checkCancellation()
                return try await block()
            }
            if prev == nil { running = flight } else { queued = flight }
            return flight.task
        }
        return try await task.value
    }
}

/// One refetch for a burst of reasons: `kick` schedules `block` after
/// `windowMs` unless one is already waiting, so ten frames (or a return to the
/// foreground plus the socket reconnecting a moment later) cost one round
/// trip. The web's `setTimeout(refetch, 800)` per event, without the storm.
/// Runs never overlap: a kick during a slow run waits for it, so fetches
/// can't stack; however many kicks land during a slow run, at most ONE run
/// follows it. A failure keeps what is on screen.
public final class Coalescer: @unchecked Sendable {
    /// Long enough to fold a foreground return and the socket's reconnect into one fetch.
    public static let CATCH_UP_WINDOW_MS: Int64 = 500
    /// The web's `setTimeout(refetch, 800)` after a notification lands.
    public static let EVENT_WINDOW_MS: Int64 = 800

    private let lock = NSLock()
    private var pending: Task<Void, Never>?
    private var pendingId: UUID?
    private let running = AsyncLock()
    private let windowMs: Int64
    private let sleep: Sleeper
    private let block: @Sendable () async throws -> Void

    public init(windowMs: Int64, sleep: @escaping Sleeper = realSleep, block: @escaping @Sendable () async throws -> Void) {
        self.windowMs = windowMs
        self.sleep = sleep
        self.block = block
    }

    /// Safe from any thread at any rate.
    public func kick() {
        lock.lock(); defer { lock.unlock() }
        if pendingId != nil { return }
        let id = UUID()
        pendingId = id
        let sleep = self.sleep, window = self.windowMs, block = self.block
        pending = Task { [weak self] in
            do { try await sleep(window) } catch { self?.clear(id); return }
            if Task.isCancelled { self?.clear(id); return }
            guard let self = self else { return }
            await self.running.withLock {
                // Only now is it running: a kick from here on schedules the next.
                self.clear(id)
                try? await block()
            }
        }
    }

    private func clear(_ id: UUID) {
        lock.lock()
        if pendingId == id { pendingId = nil; pending = nil }
        lock.unlock()
    }

    public func cancel() {
        lock.lock()
        let p = pending
        pendingId = nil; pending = nil
        lock.unlock()
        p?.cancel()
    }
}
