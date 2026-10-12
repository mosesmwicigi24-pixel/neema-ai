import Foundation

/// Keeps a `Signal` / `Watched` subscription alive; cancelling (or dropping)
/// it unsubscribes, as Combine's `AnyCancellable` does.
public final class Subscription {
    private let lock = NSLock()
    private var onCancel: (() -> Void)?
    init(_ onCancel: @escaping () -> Void) { self.onCancel = onCancel }
    public func cancel() {
        lock.lock()
        let c = onCancel
        onCancel = nil
        lock.unlock()
        c?()
    }
    deinit { cancel() }
}

/// A hot, multicast event stream — the Swift twin of a `MutableSharedFlow`
/// with `extraBufferCapacity`: every subscriber hears every value emitted
/// while subscribed; nobody replays. Handlers run on the emitting thread.
public final class Signal<Value>: @unchecked Sendable {
    public typealias Handler = (Value) -> Void
    private let lock = NSLock()
    private var handlers: [UUID: Handler] = [:]
    public let buffer: Int

    /// `buffer`: how many values a lagging `stream()` collector may fall
    /// behind before new ones are dropped (kotlinx drops the NEW value when
    /// its buffer is full, so the oldest are kept).
    public init(buffer: Int = 64) { self.buffer = buffer }

    public func emit(_ value: Value) {
        lock.lock()
        let hs = Array(handlers.values)
        lock.unlock()
        for h in hs { h(value) }
    }

    /// Subscribe with a closure; keep the token to stay subscribed.
    public func observe(_ handler: @escaping Handler) -> Subscription {
        let id = UUID()
        lock.lock()
        handlers[id] = handler
        lock.unlock()
        return Subscription { [weak self] in self?.remove(id) }
    }

    public var subscriberCount: Int { lock.lock(); defer { lock.unlock() }; return handlers.count }

    private func remove(_ id: UUID) { lock.lock(); handlers[id] = nil; lock.unlock() }

    /// A buffered stream of future values. `onDrop` is told about each value
    /// a lagging collector lost (the equivalent of `tryEmit` returning false).
    public func stream(onDrop: (() -> Void)? = nil) -> AsyncStream<Value> {
        AsyncStream(bufferingPolicy: .bufferingOldest(buffer)) { continuation in
            let sub = self.observe { v in
                if case .dropped = continuation.yield(v) { onDrop?() }
            }
            continuation.onTermination = { _ in sub.cancel() }
        }
    }
}

extension Signal where Value == Void {
    public func emit() { emit(()) }
}

/// A value plus its changes — the Swift twin of a `StateFlow`.
public final class Watched<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var current: Value
    private let changes = Signal<Value>(buffer: 1)

    public init(_ value: Value) { current = value }

    public var value: Value {
        get { lock.lock(); defer { lock.unlock() }; return current }
        set {
            lock.lock()
            current = newValue
            lock.unlock()
            changes.emit(newValue)
        }
    }

    /// Hears the current value at once, then every change.
    public func observe(_ handler: @escaping (Value) -> Void) -> Subscription {
        let sub = changes.observe(handler)
        handler(value)
        return sub
    }

    /// The current value first, then every change (the newest kept when the collector lags).
    public func stream() -> AsyncStream<Value> {
        AsyncStream(bufferingPolicy: .bufferingNewest(1)) { continuation in
            continuation.yield(self.value)
            let sub = self.changes.observe { v in continuation.yield(v) }
            continuation.onTermination = { _ in sub.cancel() }
        }
    }
}

extension Watched where Value: Equatable {
    /// Sets the value only when it changed, as a `StateFlow` does.
    public func update(_ newValue: Value) {
        lock.lock()
        if current == newValue { lock.unlock(); return }
        current = newValue
        lock.unlock()
        changes.emit(newValue)
    }
}

/// A mutex for async code: callers queue in order; `withLock` holds it
/// across suspension points (kotlinx's `Mutex.withLock`).
public final class AsyncLock: @unchecked Sendable {
    private let lock = NSLock()
    private var locked = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    public init() {}

    public func acquire() async {
        let got: Bool = lock.sync {
            if locked { return false }
            locked = true
            return true
        }
        if got { return }
        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            lock.sync {
                if !locked {
                    locked = true
                    c.resume()
                } else {
                    waiters.append(c)
                }
            }
        }
    }

    public func release() {
        let next: CheckedContinuation<Void, Never>? = lock.sync {
            if waiters.isEmpty {
                locked = false
                return nil
            }
            return waiters.removeFirst()
        }
        next?.resume()
    }

    public func withLock<T>(_ body: () async throws -> T) async rethrows -> T {
        await acquire()
        defer { release() }
        return try await body()
    }
}

public extension NSLock {
    /// Runs `body` under the lock — the form that is allowed inside async code.
    func sync<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}

/// Sleeps `ms` milliseconds; tests inject a virtual clock instead.
public typealias Sleeper = @Sendable (Int64) async throws -> Void

public let realSleep: Sleeper = { ms in
    try await Task.sleep(nanoseconds: UInt64(max(0, ms)) * 1_000_000)
}
