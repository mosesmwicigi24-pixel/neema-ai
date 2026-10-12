import Foundation

/// One crash report as the server keeps it (`POST /admin/client-crashes`;
/// Android `CrashReport`). `sdk` carries the iOS major version.
public struct CrashReport: Codable, Equatable, Sendable {
    public let id: String
    public let at: String
    public let kind: String
    public let thread: String?
    public let summary: String
    public let trace: String
    public let appVersion: String
    public let build: String
    public let device: String
    public let sdk: Int

    public init(id: String, at: String, kind: String, thread: String? = nil, summary: String = "", trace: String = "",
                appVersion: String = "", build: String = "", device: String = "", sdk: Int = 0) {
        self.id = id; self.at = at; self.kind = kind; self.thread = thread; self.summary = summary; self.trace = trace
        self.appVersion = appVersion; self.build = build; self.device = device; self.sdk = sdk
    }

    enum CodingKeys: String, CodingKey { case id, at, kind, thread, summary, trace, appVersion = "app_version", build, device, sdk }
}

/// Crash reports that survive the crash (Android `CrashVault`; owner,
/// 2026-09-27: "Neema closed because this app has a bug" and nobody could say
/// why). The app's handlers write a report to disk the moment something goes
/// wrong — an uncaught exception or a fatal signal (`crash`), an error caught
/// at the edge (`nonfatal`) — and the reports wait in the vault's directory
/// until `CrashReporter` delivers them. What is on disk: one JSON file per
/// report (the newest `MAX_FILES`), `last.txt` (the newest, delivered or
/// not — Settings shows it with Copy) and `last-fatal.txt` (the crash that
/// closed the app, until the person has seen the notice).
public final class CrashVault: @unchecked Sendable {
    public static let MAX_FILES = 10
    public static let MAX_TRACE = 48_000
    public static let MAX_TEXT = 60_000
    public static let LAST = "last.txt"
    public static let LAST_FATAL = "last-fatal.txt"

    /// What the app is, filled in once at launch (the report's build and device lines).
    nonisolated(unsafe) public static var appVersion = ""
    nonisolated(unsafe) public static var build = ""
    nonisolated(unsafe) public static var device = ""
    nonisolated(unsafe) public static var sdk = 0

    public let dir: URL
    private let now: () -> Date
    private let lock = NSLock()
    private var seq = 0

    public init(dir: URL, now: @escaping () -> Date = { Date() }) {
        self.dir = dir
        self.now = now
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    /// A report for `kind`, bounded (500 characters of summary, 48k of trace), with the app's lines.
    public static func report(kind: String, summary: String, trace: String, thread: String?, at: Date = Date()) -> CrashReport {
        let text = trace
        let line = summary.isEmpty ? (text.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: true).first.map(String.init) ?? "") : summary
        return CrashReport(id: UUID().uuidString, at: ISO8601DateFormatter().string(from: at), kind: kind, thread: thread,
                           summary: String(line.prefix(500)), trace: String(text.prefix(MAX_TRACE)),
                           appVersion: appVersion, build: build, device: String(device.prefix(120)), sdk: sdk)
    }

    /// Writes a report down. Safe to call from any thread; never throws (a crash handler calls it).
    @discardableResult
    public func record(kind: String, summary: String, trace: String, thread: String? = nil) -> CrashReport {
        let r = Self.report(kind: kind, summary: summary, trace: trace, thread: thread, at: now())
        save(r)
        return r
    }

    /// An error that was caught at the edge (a background task, a WebRTC callback) — the app keeps running.
    public func recordNonFatal(_ error: Error, where: String) {
        record(kind: "nonfatal", summary: "\(type(of: error)): \(String(describing: error))", trace: "\(error)\n\tat \(`where`)", thread: `where`)
    }

    /// Reports not yet delivered, oldest first (a file that can't be read is dropped).
    public func pending() -> [(file: URL, report: CrashReport)] {
        lock.lock(); defer { lock.unlock() }
        return jsonFiles().compactMap { f in
            if let data = try? Data(contentsOf: f), let r = try? NeemaJSON.decoder.decode(CrashReport.self, from: data) { return (f, r) }
            try? FileManager.default.removeItem(at: f)
            return nil
        }
    }

    /// The newest report on this phone (delivered or not) — Settings shows it with Copy.
    public func latest() -> CrashReport? { read(dir.appendingPathComponent(Self.LAST)) }

    public func delivered(_ file: URL) { lock.lock(); defer { lock.unlock() }; try? FileManager.default.removeItem(at: file) }

    /// The crash that closed the app last time, until the person has seen it (the next-launch notice).
    public func unseenFatal() -> CrashReport? { read(dir.appendingPathComponent(Self.LAST_FATAL)) }

    public func seen() { lock.lock(); defer { lock.unlock() }; try? FileManager.default.removeItem(at: dir.appendingPathComponent(Self.LAST_FATAL)) }

    /// A crash report as text to send on: what, where, which build and device, the trace.
    public static func asText(_ r: CrashReport) -> String {
        var out = "Neema crash report\n\(r.summary)\n"
        let line: [String?] = [r.at, r.kind, r.thread, r.device, r.sdk > 0 ? "iOS \(r.sdk)" : nil, "v\(r.appVersion) (\(r.build))"]
        out += line.compactMap { $0 }.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.joined(separator: " · ")
        out += "\n\n" + r.trace
        return String(out.prefix(MAX_TEXT))
    }

    private func read(_ url: URL) -> CrashReport? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? NeemaJSON.decoder.decode(CrashReport.self, from: data)
    }

    private func jsonFiles() -> [URL] {
        let all = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return all.filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    private func save(_ r: CrashReport) {
        lock.lock(); defer { lock.unlock() }
        guard let body = try? NeemaJSON.encoder.encode(r) else { return }
        seq += 1
        let millis = Int64(now().timeIntervalSince1970 * 1000)
        let name = String(format: "%013lld-%03d-%@.json", millis, seq % 1000, r.kind)
        try? body.write(to: dir.appendingPathComponent(name), options: .atomic)
        try? body.write(to: dir.appendingPathComponent(Self.LAST), options: .atomic)
        // The app closed on someone: the next launch shows this, with Share and Copy.
        if r.kind != "nonfatal" { try? body.write(to: dir.appendingPathComponent(Self.LAST_FATAL), options: .atomic) }
        let files = jsonFiles()
        if files.count > Self.MAX_FILES { for f in files.prefix(files.count - Self.MAX_FILES) { try? FileManager.default.removeItem(at: f) } }
    }
}

/// The hook `rtcGuard` and the app's edges record through; the app points it at its vault.
public extension CrashHooks {
    /// `CrashHooks.recordNonFatal` wired to `vault`, with `afterwards` run once the report is saved (the reporter's flush).
    static func install(_ vault: CrashVault, afterwards: @escaping () -> Void = {}) {
        recordNonFatal = { error, `where` in vault.recordNonFatal(error, where: `where`); afterwards() }
    }
}
