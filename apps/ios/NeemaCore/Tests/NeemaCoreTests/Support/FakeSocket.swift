import Foundation
@testable import NeemaCore

/// A WebSocket factory for tests: every `newWebSocket` is recorded as a
/// `FakeWs`; the test drives the server side through it (open, frames,
/// failure) and inspects what the app sent.
final class FakeSocketFactory: WebSocketFactory, @unchecked Sendable {
    private let lock = NSLock()
    private(set) var sockets: [FakeWs] = []
    var last: FakeWs { lock.sync { sockets.last! } }
    var count: Int { lock.sync { sockets.count } }

    func newWebSocket(url: URL, events: WebSocketEvents) -> WebSocketConnection {
        let ws = FakeWs(url: url, events: events)
        lock.sync { sockets.append(ws) }
        return ws
    }

    subscript(i: Int) -> FakeWs { lock.sync { sockets[i] } }
}

final class FakeWs: WebSocketConnection, @unchecked Sendable {
    let url: URL
    weak var events: WebSocketEvents?
    private let lock = NSLock()
    private(set) var sent: [String] = []
    private(set) var closedWith: Int?
    private(set) var cancelled = false

    init(url: URL, events: WebSocketEvents) { self.url = url; self.events = events }

    var urlText: String { url.absoluteString }

    /// The server accepted the upgrade.
    func open() { events?.webSocketOpened(self) }
    /// The server sent a text frame.
    func frame(_ text: String) { events?.webSocket(self, text: text) }
    /// The connection dropped.
    func fail() { events?.webSocketFailed(self, error: TransportError.network("reset")) }
    /// The server closed cleanly.
    func serverClose(code: Int = 1001) { events?.webSocketClosed(self, code: code, reason: "") }

    func send(text: String) { lock.sync { sent.append(text) } }
    func close(code: Int, reason: String?) { lock.sync { closedWith = code } }
    func cancel() { lock.sync { cancelled = true } }
    var sentCount: Int { lock.sync { sent.count } }
    var sentFrames: [String] { lock.sync { sent } }
}
