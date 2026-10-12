import Foundation

/// A background refetch whose failure leaves the screen as it was (the dashboard's poller keeps trying).
public func quietly(_ block: () async throws -> Void) async {
    do { try await block() } catch { /* keep what is on screen */ }
}

/// Waits until `watched` holds `value` (the twin of `flow.first { it }`).
public func await_<T: Equatable>(_ watched: Watched<T>, equals value: T) async {
    if watched.value == value { return }
    for await v in watched.stream() where v == value { return }
}

/// The web view's lifecycle for a model that outlives its screen (Android
/// `core/util/ScreenLife.kt`).
///
/// - `shown` is true while the screen is on display (the screen sets it).
///   It starts true: the screen creates its model on its first frame, and the
///   model's own init does the first load.
/// - Each time the screen comes back into view — and, when
///   `catchUpOnForeground`, each time the app comes back to the foreground —
///   `catchUp` runs once.
/// - When `connected` (the live socket) comes back up after a drop while the
///   screen is on display, `catchUp` runs: the frames sent while it was down
///   are lost, so the screen reads the truth again.
/// - Every `pollMs` while the screen is on display AND the app is in front,
///   `poll` runs. Nothing polls while the screen is off-screen or the app is
///   in the background.
///
/// Every refetch is quiet: a failure keeps what is on screen. Catch-ups are
/// coalesced (`catchUpWindowMs`) so a return plus a reconnect is one fetch.
public final class ScreenLife: @unchecked Sendable {
    /// Long enough to fold a foreground return and the socket's reconnect into one fetch.
    public static let CATCH_UP_WINDOW_MS: Int64 = Coalescer.CATCH_UP_WINDOW_MS
    /// The web's `setTimeout(refetch, 800)` after a notification lands.
    public static let EVENT_WINDOW_MS: Int64 = Coalescer.EVENT_WINDOW_MS

    public let shown = Watched<Bool>(true)
    private let foreground: Watched<Bool>
    private let catchUps: Coalescer
    private let pollMs: Int64?
    private let catchUpOnForeground: Bool
    private let sleep: Sleeper
    private let poll: @Sendable () async throws -> Void
    private let lock = NSLock()
    private var subs: [Subscription] = []
    private var pollTask: Task<Void, Never>?
    private var wasShown: Bool
    private var wasFront: Bool
    private var last: (Bool, Bool)?
    private var wasUp: Bool

    /// On display: the screen is composed and the app is in front.
    public var active: Bool { shown.value && foreground.value }

    public init(foreground: Watched<Bool>, connected: Watched<Bool>? = nil, pollMs: Int64? = nil, catchUpOnForeground: Bool = true,
                catchUpWindowMs: Int64 = ScreenLife.CATCH_UP_WINDOW_MS, sleep: @escaping Sleeper = realSleep,
                poll: @escaping @Sendable () async throws -> Void = {}, catchUp: @escaping @Sendable () async throws -> Void) {
        self.foreground = foreground
        self.pollMs = pollMs
        self.catchUpOnForeground = catchUpOnForeground
        self.sleep = sleep
        self.poll = poll
        catchUps = Coalescer(windowMs: catchUpWindowMs, sleep: sleep, block: catchUp)
        wasShown = true
        wasFront = foreground.value
        wasUp = connected?.value ?? false
        subs.append(shown.observe { [weak self] _ in self?.evaluate() })
        subs.append(foreground.observe { [weak self] _ in self?.evaluate() })
        if let c = connected {
            subs.append(c.observe { [weak self] up in
                guard let self = self else { return }
                let kick: Bool = self.lock.sync {
                    let k = up && !self.wasUp && self.active
                    self.wasUp = up
                    return k
                }
                if kick { self.catchUps.kick() }
            })
        }
    }

    /// Ask for a catch-up now (coalesced with any already waiting).
    public func catchUpNow() { catchUps.kick() }

    private func evaluate() {
        let s = shown.value, f = foreground.value
        let (kick, startPoll): (Bool, Bool) = lock.sync {
            if let l = last, l == (s, f) { return (false, false) }
            last = (s, f)
            let reShown = s && !wasShown
            let cameBack = catchUpOnForeground && s && f && !wasFront
            wasShown = s; wasFront = f
            // collectLatest: a change restarts the block, so the poll loop stops.
            pollTask?.cancel(); pollTask = nil
            if !(s && f) { return (false, false) }
            return (reShown || cameBack, pollMs != nil)
        }
        if kick { catchUps.kick() }
        if startPoll, let every = pollMs {
            let sleep = self.sleep, poll = self.poll
            let t = Task { [weak self] in
                while !Task.isCancelled {
                    do { try await sleep(every) } catch { return }
                    if Task.isCancelled || self == nil { return }
                    await quietly { try await poll() }
                }
            }
            lock.sync { pollTask = t }
        }
    }

    /// Stops polling and listening (the model is going away).
    public func close() {
        lock.sync {
            subs.forEach { $0.cancel() }
            subs = []
            pollTask?.cancel(); pollTask = nil
        }
        catchUps.cancel()
    }

    deinit { close() }
}
