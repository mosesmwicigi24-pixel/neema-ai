import Foundation

/// Call recordings waiting to reach the server. The web uploads once at hang-up
/// and loses the recording if that fails; on a phone network the upload often
/// does fail (the call ended BECAUSE the network dropped), so here each
/// recording is kept on disk until the server has it, and retried whenever the
/// phone is back online (socket reconnect, app back on screen, the next call).
///
/// Bounded: a recording the server refuses for good (403 recording disabled,
/// 413 too large, 400 empty) is dropped at once; anything older than
/// `MAX_AGE_MS` is dropped; at most `MAX_FILES` are kept (the oldest go first).
/// One drain at a time, so a recording is never uploaded twice concurrently.
///
/// A recording is stored as `<savedAtMillis>__<base64url(callId)>.m4a`.
/// Android `feature/calls/RecordingOutbox.kt`.
public final class RecordingOutbox: @unchecked Sendable {
    public static let MAX_FILES = 10
    public static let MAX_AGE_MS: Int64 = 3 * 24 * 60 * 60 * 1000

    private let dir: URL
    private let now: () -> Int64
    private let lock = AsyncLock()
    private let fm = FileManager.default

    public init(dir: URL, now: @escaping () -> Int64) { self.dir = dir; self.now = now }

    /// Moves `file` into the outbox for `callId`; returns false (and deletes it) if it can't be kept.
    @discardableResult
    public func put(_ callId: String, file: URL) -> Bool {
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let dest = dir.appendingPathComponent("\(now())__\(Self.encode(callId)).m4a")
        var kept = false
        if (try? fm.moveItem(at: file, to: dest)) != nil { kept = true }
        else if (try? fm.copyItem(at: file, to: dest)) != nil { kept = true }
        if fm.fileExists(atPath: file.path) { try? fm.removeItem(at: file) }
        if !kept { try? fm.removeItem(at: dest) }
        prune()
        return kept
    }

    /// Waiting recordings, oldest first: (callId, file).
    public func pending() -> [(callId: String, file: URL)] {
        let files = (try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return files.compactMap { f -> (at: Int64, id: String, file: URL)? in
            guard let (at, id) = Self.parse(f) else { return nil }
            return (at, id, f)
        }
        .sorted { $0.at < $1.at }
        .map { ($0.id, $0.file) }
    }

    /// Uploads every waiting recording, oldest first. Stops at the first
    /// transient failure (offline, timeout, 5xx, 429, session expired) and
    /// keeps the rest for the next try. Returns how many reached the server.
    @discardableResult
    public func drain(_ upload: (String, URL) async throws -> Void) async throws -> Int {
        try await lock.withLock {
            prune()
            var sent = 0
            for (id, f) in pending() {
                if !fm.fileExists(atPath: f.path) { continue }
                do {
                    try await upload(id, f)
                    sent += 1
                    try? fm.removeItem(at: f)
                } catch is CancellationError {
                    throw CancellationError()
                } catch {
                    if Self.isTransient(error) { return sent }
                    try? fm.removeItem(at: f)   // refused for good: retrying would only fail again
                }
            }
            return sent
        }
    }

    /// Drops expired recordings and the oldest beyond `MAX_FILES`.
    public func prune() {
        guard let files = try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) else { return }
        var all: [(at: Int64, file: URL)] = []
        for f in files {
            if let (at, _) = Self.parse(f) { all.append((at, f)) }
            else if f.pathExtension == "m4a" { try? fm.removeItem(at: f) }
        }
        all.sort { $0.at > $1.at }
        let t = now()
        for (i, e) in all.enumerated() where i >= Self.MAX_FILES || t - e.at > Self.MAX_AGE_MS { try? fm.removeItem(at: e.file) }
    }

    private static func parse(_ f: URL) -> (Int64, String)? {
        guard f.pathExtension == "m4a" else { return nil }
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: f.path, isDirectory: &isDir), !isDir.boolValue else { return nil }
        let stem = f.deletingPathExtension().lastPathComponent
        guard let sep = stem.range(of: "__") else { return nil }
        guard let at = Int64(stem[stem.startIndex..<sep.lowerBound]) else { return nil }
        var b64 = String(stem[sep.upperBound...]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.count % 4 != 0 { b64 += "=" }
        guard let data = Data(base64Encoded: b64), let id = String(data: data, encoding: .utf8), !id.isEmpty else { return nil }
        return (at, id)
    }

    private static func encode(_ callId: String) -> String {
        var s = Data(callId.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
        while s.hasSuffix("=") { s.removeLast() }
        return s
    }

    /// Worth another try later: never reached the server, or the server was briefly unable.
    public static func isTransient(_ e: Error) -> Bool {
        guard let a = e as? ApiError else { return false }
        return a.status == 0 || a.status == 401 || a.status == 408 || a.status == 429 || a.status >= 500
    }
}
