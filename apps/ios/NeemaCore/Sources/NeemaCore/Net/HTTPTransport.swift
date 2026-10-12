import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// What a request sends. A file part is streamed from disk by the transport,
/// so a 150 MB video or an hour-long call recording never sits whole in
/// memory — and is re-read whole on the one retry after a token refresh.
public enum HTTPBody {
    case data(Data, contentType: String?)
    case file(URL, contentType: String?)
    case multipart(MultipartBody)

    public static func json(_ text: String) -> HTTPBody { .data(Data(text.utf8), contentType: "application/json") }
    public static func json(_ data: Data) -> HTTPBody { .data(data, contentType: "application/json") }
    public static func form(_ fields: [(String, String)]) -> HTTPBody {
        .data(Data(formEncode(fields).utf8), contentType: "application/x-www-form-urlencoded")
    }

    /// `application/x-www-form-urlencoded`: space as `+`, everything but `A-Za-z0-9-._*` percent-encoded.
    public static func formEncode(_ fields: [(String, String)]) -> String {
        fields.map { "\(formEncodeComponent($0.0))=\(formEncodeComponent($0.1))" }.joined(separator: "&")
    }

    static func formEncodeComponent(_ s: String) -> String {
        var out = ""
        for byte in s.utf8 {
            let c = Character(UnicodeScalar(byte))
            if byte == 0x20 { out += "+" }
            else if (0x30...0x39).contains(byte) || (0x41...0x5A).contains(byte) || (0x61...0x7A).contains(byte) || "-._*".contains(c) { out.append(c) }
            else { out += String(format: "%%%02X", byte) }
        }
        return out
    }
}

public struct HTTPRequest {
    public var method: String
    public var url: URL
    public var headers: [String: String]
    public var body: HTTPBody?
    /// The whole call's ceiling (connect, wait, stream the body).
    public var timeout: TimeInterval
    public var followRedirects: Bool

    public init(method: String, url: URL, headers: [String: String] = [:], body: HTTPBody? = nil,
                timeout: TimeInterval = 30, followRedirects: Bool = true) {
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.timeout = timeout
        self.followRedirects = followRedirects
    }

    public func header(_ name: String) -> String? {
        headers.first { $0.key.lowercased() == name.lowercased() }?.value
    }

    /// The path after `/api` (tests and gates match on it), without the query.
    public var path: String {
        var p = url.path
        if p.hasPrefix("/api") { p = String(p.dropFirst(4)) }
        return p.isEmpty ? "/" : p
    }
}

public struct HTTPResponse {
    public var status: Int
    /// Header names lower-cased; a repeated header keeps its last value.
    public var headers: [String: String]
    /// Every `Set-Cookie` header, one entry each (they are the only header that repeats and matters).
    public var setCookies: [String]
    public var body: Data

    public init(status: Int, headers: [String: String] = [:], setCookies: [String] = [], body: Data = Data()) {
        self.status = status
        self.headers = Dictionary(headers.map { ($0.key.lowercased(), $0.value) }, uniquingKeysWith: { $1 })
        self.setCookies = setCookies
        self.body = body
    }

    public init(status: Int, headers: [String: String] = [:], setCookies: [String] = [], text: String) {
        self.init(status: status, headers: headers, setCookies: setCookies, body: Data(text.utf8))
    }

    public func header(_ name: String) -> String? { headers[name.lowercased()] }
    public var text: String { String(decoding: body, as: UTF8.self) }
    public var isSuccessful: Bool { (200..<300).contains(status) }
}

/// No answer at all: the request never reached a server or the answer never arrived.
public enum TransportError: Error, Equatable {
    /// The ceiling passed (connect, read or the whole call).
    case timedOut
    /// Offline, refused, reset, dropped mid-body, a file that could not be read.
    case network(String)
    /// The task that waited was cancelled.
    case cancelled
}

/// One request on the wire. Production is `URLSessionTransport`; tests use a fake.
public protocol HTTPTransport: AnyObject {
    func send(_ request: HTTPRequest) async throws -> HTTPResponse
}

/// A multipart/form-data body. Field parts are bytes; file parts are read
/// from disk only when the body is written, so they are sent again intact
/// on a retry.
public struct MultipartBody {
    public enum Source {
        case data(Data)
        case file(URL)
    }

    public struct Part {
        public var name: String
        public var filename: String?
        public var contentType: String?
        public var source: Source
    }

    public let boundary: String
    public private(set) var parts: [Part] = []

    public init(boundary: String = "neema-" + UUID().uuidString.lowercased()) { self.boundary = boundary }

    public mutating func addField(_ name: String, _ value: String) {
        parts.append(Part(name: name, filename: nil, contentType: nil, source: .data(Data(value.utf8))))
    }

    public mutating func addFile(_ name: String, filename: String, contentType: String, data: Data) {
        parts.append(Part(name: name, filename: filename, contentType: contentType, source: .data(data)))
    }

    public mutating func addFile(_ name: String, filename: String, contentType: String, file: URL) {
        parts.append(Part(name: name, filename: filename, contentType: contentType, source: .file(file)))
    }

    public var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    public var hasFileParts: Bool { parts.contains { if case .file = $0.source { return true } else { return false } } }

    /// The whole body in memory. A file that can't be read is a network-style failure, never a crash.
    public func encoded() throws -> Data {
        var out = Data()
        try write(into: { out.append($0) })
        return out
    }

    /// Writes the body to a temporary file (file parts streamed in chunks), for an upload task.
    public func writeTemporaryFile() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("neema-upload-\(UUID().uuidString)")
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else { throw TransportError.network("can't write the upload") }
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try write(into: { chunk in handle.write(chunk) })
        return url
    }

    private func write(into sink: (Data) throws -> Void) throws {
        for p in parts {
            var head = "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(p.name)\""
            if let f = p.filename { head += "; filename=\"\(f.replacingOccurrences(of: "\"", with: "%22"))\"" }
            head += "\r\n"
            if let ct = p.contentType { head += "Content-Type: \(ct)\r\n" }
            head += "\r\n"
            try sink(Data(head.utf8))
            switch p.source {
            case .data(let d):
                try sink(d)
            case .file(let url):
                guard let stream = InputStream(url: url) else { throw TransportError.network("Can't read the file") }
                stream.open()
                defer { stream.close() }
                if stream.streamStatus == .error { throw TransportError.network("Can't read the file") }
                var buffer = [UInt8](repeating: 0, count: 256 * 1024)
                while true {
                    let n = stream.read(&buffer, maxLength: buffer.count)
                    if n < 0 { throw TransportError.network("Can't read the file") }
                    if n == 0 { break }
                    try sink(Data(buffer[0..<n]))
                }
            }
            try sink(Data("\r\n".utf8))
        }
        try sink(Data("--\(boundary)--\r\n".utf8))
    }
}

/// The real transport: `URLSession`, no cookie jar of its own (the auth layer
/// keeps NextAuth's cookies itself), redirects only when asked, and the
/// request's `timeout` as a hard ceiling on the whole call.
public final class URLSessionTransport: HTTPTransport, @unchecked Sendable {
    /// Which tasks must not follow a redirect (the NextAuth callback answers 302).
    final class Redirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
        private let lock = NSLock()
        private var stay: Set<Int> = []

        func hold(_ task: URLSessionTask) { lock.sync { _ = stay.insert(task.taskIdentifier) } }

        func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
            let hold = lock.sync { stay.contains(task.taskIdentifier) }
            completionHandler(hold ? nil : request)
        }

        func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
            lock.sync { _ = stay.remove(task.taskIdentifier) }
        }
    }

    private let session: URLSession
    private let redirects = Redirects()

    public init(configuration: URLSessionConfiguration = .default) {
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.httpCookieAcceptPolicy = .never
        session = URLSession(configuration: configuration, delegate: redirects, delegateQueue: nil)
    }

    public func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        var built = URLRequest(url: request.url)
        built.httpMethod = request.method
        built.timeoutInterval = request.timeout
        for (k, v) in request.headers { built.setValue(v, forHTTPHeaderField: k) }
        var fileToUpload: URL? = nil
        var tempFile: URL? = nil
        switch request.body {
        case .none:
            break
        case .data(let d, let ct):
            built.httpBody = d
            if let ct = ct { built.setValue(ct, forHTTPHeaderField: "Content-Type") }
        case .file(let url, let ct):
            fileToUpload = url
            if let ct = ct { built.setValue(ct, forHTTPHeaderField: "Content-Type") }
        case .multipart(let m):
            built.setValue(m.contentType, forHTTPHeaderField: "Content-Type")
            if m.hasFileParts {
                let t = try m.writeTemporaryFile()
                tempFile = t
                fileToUpload = t
            } else {
                built.httpBody = try m.encoded()
            }
        }
        defer { if let t = tempFile { try? FileManager.default.removeItem(at: t) } }
        let req = built
        let upload = fileToUpload
        let follow = request.followRedirects
        return try await withCeiling(request.timeout) {
            try await self.perform(req, uploadFile: upload, followRedirects: follow)
        }
    }

    private final class TaskBox: @unchecked Sendable {
        let lock = NSLock()
        var task: URLSessionTask?
        var cancelled = false
        func set(_ t: URLSessionTask) {
            let c: Bool = lock.sync { task = t; return cancelled }
            if c { t.cancel() }
        }
        func cancel() {
            let t: URLSessionTask? = lock.sync { cancelled = true; return task }
            t?.cancel()
        }
    }

    private func perform(_ req: URLRequest, uploadFile: URL?, followRedirects: Bool) async throws -> HTTPResponse {
        let box = TaskBox()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (cont: CheckedContinuation<HTTPResponse, Error>) in
                let handler: @Sendable (Data?, URLResponse?, Error?) -> Void = { data, resp, err in
                    if let err = err { cont.resume(throwing: Self.map(err)); return }
                    guard let http = resp as? HTTPURLResponse else {
                        cont.resume(throwing: TransportError.network("no HTTP answer"))
                        return
                    }
                    cont.resume(returning: Self.response(http, data ?? Data()))
                }
                let task: URLSessionTask
                if let f = uploadFile {
                    task = session.uploadTask(with: req, fromFile: f, completionHandler: handler)
                } else {
                    task = session.dataTask(with: req, completionHandler: handler)
                }
                if !followRedirects { redirects.hold(task) }
                box.set(task)
                task.resume()
            }
        } onCancel: {
            box.cancel()
        }
    }

    static func response(_ http: HTTPURLResponse, _ data: Data) -> HTTPResponse {
        var headers: [String: String] = [:]
        for (k, v) in http.allHeaderFields { headers[String(describing: k).lowercased()] = String(describing: v) }
        // Several Set-Cookie headers arrive joined by commas; Foundation's cookie
        // parser is the one thing that splits them right (dates hold commas too).
        var cookies: [String] = []
        if let url = http.url, let raw = http.allHeaderFields as? [String: String] {
            for c in HTTPCookie.cookies(withResponseHeaderFields: raw, for: url) {
                var line = "\(c.name)=\(c.value)"
                if let exp = c.expiresDate, exp <= Date() { line += "; Max-Age=0" }
                cookies.append(line)
            }
        }
        return HTTPResponse(status: http.statusCode, headers: headers, setCookies: cookies, body: data)
    }

    static func map(_ err: Error) -> Error {
        if let e = err as? URLError {
            switch e.code {
            case .timedOut: return TransportError.timedOut
            case .cancelled: return TransportError.cancelled
            default: return TransportError.network(e.localizedDescription)
            }
        }
        let ns = err as NSError
        if ns.domain == NSURLErrorDomain {
            if ns.code == NSURLErrorTimedOut { return TransportError.timedOut }
            if ns.code == NSURLErrorCancelled { return TransportError.cancelled }
        }
        return TransportError.network(ns.localizedDescription)
    }
}

/// Runs `op` with a hard ceiling: when `seconds` pass first, the operation is cancelled and the call times out.
public func withCeiling<T: Sendable>(_ seconds: TimeInterval, _ op: @escaping @Sendable () async throws -> T) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask { try await op() }
        group.addTask {
            try await Task.sleep(nanoseconds: UInt64(max(0, seconds) * 1_000_000_000))
            throw TransportError.timedOut
        }
        defer { group.cancelAll() }
        guard let first = try await group.next() else { throw TransportError.network("no answer") }
        return first
    }
}
