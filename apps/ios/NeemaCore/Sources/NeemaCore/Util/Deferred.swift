import Foundation

/// A value completed once, awaited by any number of tasks — kotlinx's
/// `CompletableDeferred`. Waiting is cancellable (a `CancellationError`).
public final class Deferred<T: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var result: T?
    private var waiters: [(id: UUID, cont: CheckedContinuation<T, Error>)] = []
    private var cancelledEarly: Set<UUID> = []

    public init() {}

    public var isDone: Bool { lock.sync { result != nil } }

    /// Resolves every waiter; a second completion is ignored (the first value stands).
    @discardableResult
    public func complete(_ value: T) -> Bool {
        let ws: [(id: UUID, cont: CheckedContinuation<T, Error>)]? = lock.sync {
            if result != nil { return nil }
            result = value
            let w = waiters
            waiters = []
            return w
        }
        guard let ws = ws else { return false }
        for w in ws { w.cont.resume(returning: value) }
        return true
    }

    /// The value, once there is one.
    public func value() async throws -> T {
        if let r = (lock.sync { result }) { return r }
        let id = UUID()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<T, Error>) in
                lock.sync {
                    if cancelledEarly.remove(id) != nil { c.resume(throwing: CancellationError()); return }
                    if let r = result { c.resume(returning: r); return }
                    waiters.append((id, c))
                }
            }
        } onCancel: {
            let c: CheckedContinuation<T, Error>? = lock.sync {
                if let i = waiters.firstIndex(where: { $0.id == id }) { return waiters.remove(at: i).cont }
                cancelledEarly.insert(id)
                return nil
            }
            c?.resume(throwing: CancellationError())
        }
    }
}

/// kotlinx's `withTimeoutOrNull`: `op`'s value, or nil when `ms` passed first
/// (`op` is then cancelled). An error `op` throws is rethrown.
public func withTimeoutOrNil<T: Sendable>(_ ms: Int64, sleep: @escaping Sleeper,
                                          _ op: @escaping @Sendable () async throws -> T) async throws -> T? {
    try await withThrowingTaskGroup(of: T?.self) { group in
        group.addTask { try await op() }
        group.addTask {
            do { try await sleep(ms) } catch { throw error }
            return nil
        }
        let first = try await group.next() ?? nil
        group.cancelAll()
        return first
    }
}
