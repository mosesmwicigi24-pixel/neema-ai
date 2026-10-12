import Foundation

/// Words another view asked for in a thread's composer (never sent by themselves).
public struct ComposerPrefill: Equatable, Sendable {
    public let convId: String
    public let text: String
    public init(convId: String, text: String) { self.convId = convId; self.text = text }
}

/// How placing a call from the thread went.
public enum CallOutcome: Sendable, Equatable {
    case placed
    /// The call screen already showed the outcome: nothing to say here.
    case shown
    case failed(String)
}

/// What the inbox needs from the shell (Android's `DashboardViewModel` as the
/// inbox sees it). The app model conforms; tests use a small fake.
public protocol InboxHost: AnyObject {
    var session: Watched<Session?> { get }
    var foreground: Watched<Bool> { get }
    /// The SessionExpired dialog is up (a refresh failed for good).
    var sessionExpired: Watched<Bool> { get }
    var socketConnected: Watched<Bool> { get }
    var socketEvents: Signal<JSONValue> { get }
    /// The shell asks the inbox to refetch (a notification landed).
    var inboxRefresh: Signal<Void> { get }
    /// The badges the shell shows (the inbox keeps them fresh).
    var inboxSummary: Watched<InboxSummary?> { get }
    /// A conversation another view wants opened (`wa_id|ref`, a PSID or an id); the inbox consumes it.
    var openConvKey: Watched<String?> { get }
    var composerPrefill: Watched<ComposerPrefill?> { get }
    var api: NeemaApi { get }
    var snapshots: SnapshotCache { get }
    func toast(_ message: String, _ type: ToastType)
    func placeCall(waId: String, name: String?, convId: String?) async -> CallOutcome
}

/// What the inbox needs from the file system and the image codec for picked
/// files (`ContentResolver` + `BitmapFactory` on Android). The app supplies
/// the real one; the core ships a Foundation-only default.
public protocol MediaAccess: AnyObject, Sendable {
    /// The display name and byte size of a picked file.
    func meta(of url: URL) -> (name: String, size: Int64)
    /// The system's idea of the file's type, if it has one.
    func mimeType(of url: URL) -> String?
    /// Max 2048 px on the long side, JPEG, stepping quality down until it fits 5 MB; nil when it can't be done.
    func compressImage(at url: URL) async -> Data?
    /// The app can still read the file (a picker's grant may have lapsed).
    func readable(_ url: URL) -> Bool
}

/// Files on disk, no image codec: a photo over the cap is refused instead of shrunk.
public final class FileMediaAccess: MediaAccess, @unchecked Sendable {
    public init() {}
    public func meta(of url: URL) -> (name: String, size: Int64) {
        let name = url.lastPathComponent.isEmpty ? "file" : url.lastPathComponent
        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value ?? 0
        return (name, size)
    }
    public func mimeType(of url: URL) -> String? { nil }
    public func compressImage(at url: URL) async -> Data? { nil }
    public func readable(_ url: URL) -> Bool { FileManager.default.isReadableFile(atPath: url.path) }
}
