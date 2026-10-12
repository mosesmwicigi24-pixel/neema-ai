import XCTest
import SwiftUI
import UIKit
import NeemaCore
@testable import Neema

/// Renders every view of the signed-in app — and the sign-in screen — against
/// the canned backend, on a phone (light and dark) and an iPad (light), and
/// writes the PNGs to `$NEEMA_SCREENSHOTS` (the CI job uploads that folder as
/// the `ios-screenshots` artifact) besides attaching them to the test result.
/// It is the only look at the SwiftUI layer this programme gets without a
/// device: a screen that fails to lay out fails here.
@MainActor
final class ScreenGalleryTests: XCTestCase {
    private final class NoSockets: WebSocketFactory {
        final class Dead: WebSocketConnection {
            let url: URL
            init(_ u: URL) { url = u }
            func send(text: String) {}
            func close(code: Int, reason: String?) {}
            func cancel() {}
        }
        func newWebSocket(url: URL, events: WebSocketEvents) -> WebSocketConnection { Dead(url) }
    }

    private struct Shot {
        let tag: String
        let size: CGSize
        let dark: Bool
    }

    private static let shots = [
        Shot(tag: "phone-light", size: CGSize(width: 390, height: 844), dark: false),
        Shot(tag: "phone-dark", size: CGSize(width: 390, height: 844), dark: true),
        Shot(tag: "ipad-light", size: CGSize(width: 1180, height: 820), dark: false),
    ]

    private static let views: [ViewId] = [.conversations, .orders, .catalog, .deals, .leads, .overview, .reports, .agents, .profile, .calls, .settings]

    private var outDir: URL? {
        guard let dir = ProcessInfo.processInfo.environment["NEEMA_SCREENSHOTS"], !dir.isEmpty else { return nil }
        let url = URL(fileURLWithPath: dir)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    /// A signed JWT-shaped token that expires in a year: the HTTP client reads its `exp`, nothing checks its signature here.
    private func token(for agentId: String) -> String {
        func b64(_ s: String) -> String {
            var out = Data(s.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            while out.hasSuffix("=") { out.removeLast() }
            return out
        }
        let exp = Int64(Date().timeIntervalSince1970) + 365 * 24 * 3600
        return b64(#"{"alg":"HS256","typ":"JWT"}"#) + "." + b64(#"{"sub":"\#(agentId)","exp":\#(exp)}"#) + ".gallery"
    }

    func testRendersEveryScreen() async throws {
        let transport = try CannedTransport.bundled(for: ScreenGalleryTests.self)
        // The fixtures' dates are relative to the core's pinned clock: "5m ago" reads the same here.
        if transport.pinnedMillis > 0 { AppClock.pin(to: Date(timeIntervalSince1970: Double(transport.pinnedMillis) / 1000)) }
        defer { AppClock.reset() }
        let container = AppContainer(baseUrl: "https://neema.test", store: MemoryStore(), transport: transport, socketFactory: NoSockets(), watchNetwork: false)
        let app = AppModel(container: container)

        // Signed out first: the login screen, by night as it always is.
        var failures: [String] = []
        for shot in Self.shots where shot.tag != "phone-dark" {
            if render(app, shot: shot, name: "login") == nil { failures.append("\(shot.tag)-login") }
        }

        let a = transport.agent
        container.sessionStore.save(Session(accessToken: token(for: a.id), refreshToken: "gallery", agentId: a.id, email: a.email,
                                            name: a.name, role: a.role, isSuperuser: a.isSuperuser, mode: "direct"))
        app.setForeground(true)
        await quiet(transport)

        for shot in Self.shots {
            app.setDark(shot.dark)
            for view in Self.views {
                app.navigate(view)
                await quiet(transport)
                if render(app, shot: shot, name: view.rawValue) == nil { failures.append("\(shot.tag)-\(view.rawValue)") }
            }
        }
        if !transport.unmatched.isEmpty {
            print("gallery: no fixture for \(Set(transport.unmatched).sorted().joined(separator: ", "))")
        }
        XCTAssertTrue(failures.isEmpty, "screens that did not render: \(failures.joined(separator: ", "))")
        app.logout()
    }

    /// Waits until the app has asked the backend for nothing for 400 ms (at most 6 s), then a beat for the models to publish.
    private func quiet(_ transport: CannedTransport) async {
        let start = Date()
        while Date().timeIntervalSince(start) < 6 {
            try? await Task.sleep(nanoseconds: 100_000_000)
            if Date().timeIntervalSince(transport.lastRequest) > 0.4 { break }
        }
        try? await Task.sleep(nanoseconds: 250_000_000)
    }

    @discardableResult
    private func render(_ app: AppModel, shot: Shot, name: String) -> UIImage? {
        let colors = shot.dark ? NeemaColors.dark : NeemaColors.light
        let content = RootView()
            .environmentObject(app)
            .environment(\.neema, colors)
            .preferredColorScheme(shot.dark ? .dark : .light)
            .frame(width: shot.size.width, height: shot.size.height)
            .background(colors.surface)
        let renderer = ImageRenderer(content: content)
        renderer.proposedSize = ProposedViewSize(shot.size)
        renderer.scale = 2
        guard let image = renderer.uiImage, let png = image.pngData() else { return nil }
        let file = "\(shot.tag)-\(name).png"
        let attachment = XCTAttachment(image: image)
        attachment.name = file
        attachment.lifetime = .keepAlways
        add(attachment)
        if let dir = outDir { try? png.write(to: dir.appendingPathComponent(file)) }
        return image
    }
}
