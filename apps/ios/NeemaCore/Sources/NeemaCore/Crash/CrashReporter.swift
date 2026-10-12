import Foundation

/// Delivers saved crash reports to `POST /admin/client-crashes` once someone
/// is signed in (at start, on sign-in, and after a non-fatal). A report that
/// can't be sent stays on the phone for the next try; the server keeps them
/// for the owner (Settings → App crash reports) and logs each one. Android
/// `CrashReporter`.
public final class CrashReporter: @unchecked Sendable {
    private let http: NeemaHTTP
    private let signedIn: Watched<Bool>
    private let pending: () -> [(file: URL, report: CrashReport)]
    private let delivered: (URL) -> Void
    private let lock = AsyncLock()
    private var sub: Subscription?

    public init(http: NeemaHTTP, signedIn: Watched<Bool>,
                pending: @escaping () -> [(file: URL, report: CrashReport)], delivered: @escaping (URL) -> Void) {
        self.http = http; self.signedIn = signedIn; self.pending = pending; self.delivered = delivered
    }

    public convenience init(http: NeemaHTTP, signedIn: Watched<Bool>, vault: CrashVault) {
        self.init(http: http, signedIn: signedIn, pending: { vault.pending() }, delivered: { vault.delivered($0) })
    }

    /// Every sign-in (and the one already in force) sends what is waiting.
    public func start() {
        sub = signedIn.observe { [weak self] on in if on { self?.flushSoon() } }
    }

    public func stop() { sub?.cancel(); sub = nil }

    /// Send what is waiting (a no-op when signed out or nothing waits).
    public func flushSoon() { Task { _ = await self.flush() } }

    /// Sends the pending reports oldest first, stopping at the first that fails; how many went.
    @discardableResult
    public func flush() async -> Int {
        await lock.acquire()
        defer { lock.release() }
        if !signedIn.value { return 0 }
        var sent = 0
        for (file, report) in pending() {
            if Task.isCancelled { break }
            do {
                let _: JSONValue = try await http.post("/admin/client-crashes", report)
                delivered(file)
                sent += 1
            } catch {
                break   // offline or refused: try again next time, in order
            }
        }
        return sent
    }
}
