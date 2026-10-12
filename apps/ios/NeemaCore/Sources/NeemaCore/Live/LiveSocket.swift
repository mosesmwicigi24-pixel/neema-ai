import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// One WebSocket on the wire. Production wraps `URLSessionWebSocketTask`; tests use a fake.
public protocol WebSocketConnection: AnyObject {
    var url: URL { get }
    func send(text: String)
    /// A graceful close (code 1000 on purpose).
    func close(code: Int, reason: String?)
    /// Tear down at once, no handshake.
    func cancel()
}

/// What a connection reports back. Callbacks may arrive on any thread.
public protocol WebSocketEvents: AnyObject {
    func webSocketOpened(_ socket: WebSocketConnection)
    func webSocket(_ socket: WebSocketConnection, text: String)
    func webSocketClosed(_ socket: WebSocketConnection, code: Int, reason: String)
    func webSocketFailed(_ socket: WebSocketConnection, error: Error)
}

public protocol WebSocketFactory: AnyObject {
    func newWebSocket(url: URL, events: WebSocketEvents) -> WebSocketConnection
}

/// The dashboard's live feed: a plain FastAPI WebSocket at
/// `/ws/{agent_id}?token=<access token>` (routers/websocket.py) that relays
/// every `ws:channel:*` Redis broadcast to every connected client. Port of
/// `lib/websocket.tsx` and Android's `LiveSocket`: reconnect after any close
/// (2 s like the web, then backing off 4/8/16/30 s while the server stays
/// unreachable, so a phone on a dead network doesn't spin its radio), JSON
/// `{"type":"ping"}` every 25 s (the server answers `{"type":"pong"}`, dropped
/// here; anything that isn't JSON makes the server close the socket, so only
/// JSON is ever sent).
///
/// The socket is not filtered per agent or per conversation: every frame
/// reaches every client, and consumers collect `events` and filter on `type`
/// / `event` / `conversationId` themselves. The frame catalogue (conversation
/// frames on `ws:channel:{conversation_id}`, agent notifications on
/// `ws:channel:agents:all`, calls on `ws:channel:calls`) is documented in
/// docs/ios/PARITY_MATRIX.md and Android's LiveSocket.kt.
public final class LiveSocket: WebSocketEvents {
    public static let EVENT_BUFFER = 1024

    /// Frames are parsed on the socket's reader thread and handed over without
    /// blocking it. A stream buffer absorbs a burst at peak while a collector
    /// on the main thread catches up.
    public let events = Signal<JSONValue>(buffer: EVENT_BUFFER)
    /// Frames lost because a collector fell more than `EVENT_BUFFER` behind (should stay 0).
    public private(set) var droppedFrames: Int64 = 0
    public let connected = Watched<Bool>(false)
    /// Fires every time the socket opens AGAIN for the same agent — after a
    /// drop, a retry, or a deliberate close while backgrounded — i.e. whenever
    /// frames may have been missed. Screens refetch what they show on it. Not
    /// fired for the first open after sign-in / an agent switch.
    public let reconnected = Signal<Void>(buffer: 8)

    private let factory: WebSocketFactory
    private let baseUrl: String
    /// The first retry's wait — the web's flat 2 s.
    private let reconnectDelayMs: Int64
    /// Retries back off (doubling) up to this; an open socket resets it.
    private let maxReconnectDelayMs: Int64
    private let pingEveryMs: Int64
    /// The signed-in agent's current access token, read on every attempt so a
    /// reconnect after a token refresh uses the fresh one.
    private let token: () -> String?
    private let sleep: Sleeper

    private let lock = NSRecursiveLock()
    private var ws: WebSocketConnection?
    private var agentId: String?
    private var pingTask: Task<Void, Never>?
    private var reconnectTask: Task<Void, Never>?
    /// Has a socket opened for `agentId` since sign-in / the last agent switch?
    private var everOpened = false
    /// Consecutive failed attempts since the last open (drives the backoff).
    private var failures = 0
    private var closed = true

    public init(factory: WebSocketFactory, baseUrl: String, reconnectDelayMs: Int64 = 2_000, maxReconnectDelayMs: Int64 = 30_000,
                pingEveryMs: Int64 = 25_000, token: @escaping () -> String? = { nil }, sleep: @escaping Sleeper = realSleep) {
        self.factory = factory
        self.baseUrl = baseUrl
        self.reconnectDelayMs = reconnectDelayMs
        self.maxReconnectDelayMs = maxReconnectDelayMs
        self.pingEveryMs = pingEveryMs
        self.token = token
        self.sleep = sleep
    }

    /// The frames, buffered per collector; a lagging collector's losses count in `droppedFrames`.
    public func eventStream() -> AsyncStream<JSONValue> {
        events.stream(onDrop: { [weak self] in
            guard let self = self else { return }
            self.lock.lock(); self.droppedFrames += 1; self.lock.unlock()
        })
    }

    public func url(_ agentId: String) -> String {
        var wsBase = baseUrl
        while wsBase.hasSuffix("/") { wsBase.removeLast() }
        if wsBase.hasPrefix("https://") { wsBase = "wss://" + wsBase.dropFirst(8) }
        else if wsBase.hasPrefix("http://") { wsBase = "ws://" + wsBase.dropFirst(7) }
        if let r = wsBase.range(of: #"/api/?$"#, options: .regularExpression) { wsBase.removeSubrange(r) }
        let t = token() ?? ""
        if t.isEmpty { return "\(wsBase)/ws/\(agentId)" }
        return "\(wsBase)/ws/\(agentId)?token=\(Self.urlEncode(t))"
    }

    /// `URLEncoder.encode(t, "UTF-8")`: letters, digits, `.-*_` kept; space as `+`; the rest percent-encoded.
    static func urlEncode(_ s: String) -> String { HTTPBody.formEncodeComponent(s) }

    /// The wait before retry number `attempt` (1-based): 2 s, 4 s, 8 s, 16 s, then 30 s.
    public func backoff(_ attempt: Int) -> Int64 {
        var d = reconnectDelayMs
        for _ in 0..<min(max(attempt - 1, 0), 20) { d = min(d * 2, maxReconnectDelayMs) }
        return min(d, maxReconnectDelayMs)
    }

    /// Idempotent: connecting as the same agent again is a no-op.
    public func connect(_ agentId: String) {
        lock.lock(); defer { lock.unlock() }
        if !closed && self.agentId == agentId { return }
        if self.agentId != agentId { everOpened = false }
        close()
        self.agentId = agentId
        closed = false
        failures = 0
        open()
    }

    /// Close on purpose; nothing reconnects until `connect` again. The agent
    /// is remembered, so reconnecting as them later counts as a *re*connect
    /// (frames were missed meanwhile) — `signOut` forgets them.
    public func disconnect() { lock.lock(); close(); lock.unlock() }

    /// Close and forget the agent: nothing reconnects, and nothing is "missed".
    public func signOut() {
        lock.lock(); defer { lock.unlock() }
        close()
        agentId = nil
        everOpened = false
    }

    private func close() {
        closed = true
        pingTask?.cancel(); pingTask = nil
        reconnectTask?.cancel(); reconnectTask = nil
        ws?.close(code: 1000, reason: nil)
        ws = nil
        connected.update(false)
    }

    /// Reconnect immediately if the socket is down but wanted (the app came
    /// back to the foreground, or the network returned, mid-backoff). A socket
    /// closed on purpose — signed out, or backgrounded without live mode —
    /// stays closed: the session/foreground watcher decides when to reopen.
    public func nudge() {
        lock.lock(); defer { lock.unlock() }
        if agentId == nil || closed || connected.value { return }
        failures = 0
        reconnectTask?.cancel(); reconnectTask = nil
        ws?.cancel(); ws = nil
        open()
    }

    private func open() {
        guard let id = agentId, let u = URL(string: url(id)) else { return }
        ws = factory.newWebSocket(url: u, events: self)
    }

    private func opened(_ socket: WebSocketConnection) {
        lock.lock(); defer { lock.unlock() }
        if socket !== ws || closed { socket.cancel(); return }
        connected.update(true)
        failures = 0
        pingTask?.cancel()
        let every = pingEveryMs
        let sleep = self.sleep
        pingTask = Task { [weak socket] in
            while !Task.isCancelled {
                do { try await sleep(every) } catch { return }
                if Task.isCancelled { return }
                socket?.send(text: #"{"type":"ping"}"#)
            }
        }
        if everOpened { reconnected.emit() }
        everOpened = true
    }

    private func dropped(_ socket: WebSocketConnection) {
        lock.lock(); defer { lock.unlock() }
        if socket !== ws { return }
        connected.update(false)
        pingTask?.cancel(); pingTask = nil
        if closed { return }
        failures += 1
        let wait = backoff(failures)
        reconnectTask?.cancel()
        let sleep = self.sleep
        reconnectTask = Task { [weak self] in
            do { try await sleep(wait) } catch { return }
            if Task.isCancelled { return }
            self?.reopen()
        }
    }

    private func reopen() {
        lock.lock(); defer { lock.unlock() }
        if !closed && !connected.value { open() }
    }

    // ── WebSocketEvents ─────────────────────────────────────────────────────

    public func webSocketOpened(_ socket: WebSocketConnection) { opened(socket) }

    public func webSocket(_ socket: WebSocketConnection, text: String) {
        // A replaced socket still draining must not double every frame.
        lock.lock(); let current = ws; lock.unlock()
        if socket !== current { return }
        guard let v = JSONValue.parse(text), case .object(let o) = v else { return }
        if o["type"]?.content == "pong" { return }
        events.emit(v)
    }

    public func webSocketClosed(_ socket: WebSocketConnection, code: Int, reason: String) { dropped(socket) }

    public func webSocketFailed(_ socket: WebSocketConnection, error: Error) { dropped(socket) }
}

/// Convenience reader for the loosely-typed socket frames.
public extension JSONValue {
    func str(_ key: String) -> String? { self[key]?.content }
}

#if !os(Linux)
/// Production sockets over `URLSessionWebSocketTask`.
public final class URLSessionWebSocketFactory: NSObject, WebSocketFactory, URLSessionWebSocketDelegate {
    private var session: URLSession!
    private let lock = NSLock()
    private var connections: [Int: Connection] = [:]

    public override init() {
        super.init()
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 60
        cfg.waitsForConnectivity = false
        session = URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
    }

    final class Connection: WebSocketConnection {
        let url: URL
        let task: URLSessionWebSocketTask
        weak var events: WebSocketEvents?
        private var finished = false
        private let lock = NSLock()

        init(url: URL, task: URLSessionWebSocketTask, events: WebSocketEvents) {
            self.url = url
            self.task = task
            self.events = events
        }

        func receiveLoop() {
            task.receive { [weak self] result in
                guard let self = self else { return }
                switch result {
                case .success(.string(let s)):
                    self.events?.webSocket(self, text: s)
                    self.receiveLoop()
                case .success(.data(let d)):
                    if let s = String(data: d, encoding: .utf8) { self.events?.webSocket(self, text: s) }
                    self.receiveLoop()
                case .success:
                    self.receiveLoop()
                case .failure(let e):
                    self.fail(e)
                }
            }
        }

        func fail(_ e: Error) {
            lock.lock()
            if finished { lock.unlock(); return }
            finished = true
            lock.unlock()
            events?.webSocketFailed(self, error: e)
        }

        func closedByServer(code: Int, reason: String) {
            lock.lock()
            if finished { lock.unlock(); return }
            finished = true
            lock.unlock()
            events?.webSocketClosed(self, code: code, reason: reason)
        }

        func send(text: String) { task.send(.string(text)) { _ in } }
        func close(code: Int, reason: String?) {
            task.cancel(with: URLSessionWebSocketTask.CloseCode(rawValue: code) ?? .normalClosure, reason: reason.map { Data($0.utf8) })
        }
        func cancel() { task.cancel() }
    }

    public func newWebSocket(url: URL, events: WebSocketEvents) -> WebSocketConnection {
        let task = session.webSocketTask(with: url)
        let conn = Connection(url: url, task: task, events: events)
        lock.lock(); connections[task.taskIdentifier] = conn; lock.unlock()
        task.resume()
        conn.receiveLoop()
        return conn
    }

    private func connection(_ task: URLSessionTask) -> Connection? {
        lock.lock(); defer { lock.unlock() }
        return connections[task.taskIdentifier]
    }

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        guard let c = connection(webSocketTask) else { return }
        c.events?.webSocketOpened(c)
    }

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        guard let c = connection(webSocketTask) else { return }
        c.closedByServer(code: closeCode.rawValue, reason: reason.flatMap { String(data: $0, encoding: .utf8) } ?? "")
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let c = connection(task) else { return }
        lock.lock(); connections[task.taskIdentifier] = nil; lock.unlock()
        if let e = error { c.fail(e) } else { c.closedByServer(code: 1000, reason: "") }
    }
}
#endif
