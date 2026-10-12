import XCTest
import SwiftUI
import UIKit
import NeemaCore
@testable import Neema

/// Renders every view of the signed-in app — and the sign-in screen — against
/// the canned backend, on a phone (light and dark) and an iPad (light), then
/// the named states Android's screenshot suites pin (the drawer, the account
/// menu, the bell, toasts, offline, the session-expired card, an open thread,
/// a ringing call and its wrap-up), and writes the PNGs to `$NEEMA_SCREENSHOTS`
/// (the CI job uploads that folder as the `ios-screenshots` artifact) besides
/// attaching them to the test result. Each shot is the view hosted in a window
/// of that size and drawn as it is on screen. It is the only look at the
/// SwiftUI layer this programme gets without a device: a screen that fails to
/// lay out fails here.
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
        let app = AppModel(container: container, ringer: QuietRinger())

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
        await renderStates(app, container, transport, failures: &failures)
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

    /// Renders the app as it is on screen: the view hosted in a window of the shot's size (lazy
    /// stacks and scroll views lay out only there; `ImageRenderer` left every scrolling region
    /// blank), then the layer tree drawn at 2x.
    @discardableResult
    private func render(_ app: AppModel, shot: Shot, name: String) -> UIImage? {
        let colors = shot.dark ? NeemaColors.dark : NeemaColors.light
        let content = RootView()
            .environmentObject(app)
            .environment(\.neema, colors)
            .preferredColorScheme(shot.dark ? .dark : .light)
            .frame(width: shot.size.width, height: shot.size.height)
            .background(colors.surface)
        let host = UIHostingController(rootView: content)
        host.overrideUserInterfaceStyle = shot.dark ? .dark : .light
        let window: UIWindow
        if let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first {
            window = UIWindow(windowScene: scene)
        } else {
            window = UIWindow(frame: CGRect(origin: .zero, size: shot.size))
        }
        window.frame = CGRect(origin: .zero, size: shot.size)
        window.rootViewController = host
        window.isHidden = false
        host.view.frame = window.bounds
        host.view.setNeedsLayout()
        host.view.layoutIfNeeded()
        // Two turns of the run loop: SwiftUI commits its first layout and the lazy stacks fill the viewport.
        RunLoop.main.run(until: Date().addingTimeInterval(0.25))
        host.view.layoutIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        let format = UIGraphicsImageRendererFormat()
        format.scale = 2
        let image = UIGraphicsImageRenderer(size: shot.size, format: format).image { ctx in
            window.layer.render(in: ctx.cgContext)
        }
        window.isHidden = true
        window.rootViewController = nil
        guard let png = image.pngData() else { return nil }
        let file = "\(shot.tag)-\(name).png"
        let attachment = XCTAttachment(image: image)
        attachment.name = file
        attachment.lifetime = .keepAlways
        add(attachment)
        if let dir = outDir { try? png.write(to: dir.appendingPathComponent(file)) }
        return image
    }

    // ── Named states (Android's screenshot suites), on the phone and the iPad ──

    /// A silent ringer for the gallery: CallKit's system call UI must not open over the test host.
    final class QuietRinger: CallRinger {
        func startRinging() {}
        func stopRinging() {}
        func postIncoming(callId: String, who: String, from: String?, app: String) {}
        func cancelIncoming() {}
    }

    private func renderStates(_ app: AppModel, _ container: AppContainer, _ transport: CannedTransport, failures: inout [String]) async {
        let phone = Self.shots[0], phoneDark = Self.shots[1], ipad = Self.shots[2]
        var missed: [String] = []
        func shot(_ s: Shot, _ name: String) {
            app.setDark(s.dark)
            if render(app, shot: s, name: name) == nil { missed.append("\(s.tag)-\(name)") }
        }
        defer { failures.append(contentsOf: missed) }
        func pause(_ ms: UInt64 = 350) async { try? await Task.sleep(nanoseconds: ms * 1_000_000) }

        app.navigate(.conversations)
        await quiet(transport)
        // ShellScreenshotTest.phoneDrawer / phoneDrawerDark, and the account menu in it.
        app.drawerOpen = true
        await pause()
        shot(phone, "drawer"); shot(phoneDark, "drawer")
        app.accountMenuOpen = true
        await pause()
        shot(phone, "account-menu")
        app.accountMenuOpen = false
        app.drawerOpen = false
        // bellSheet / bellSheetDark (the fixtures' notifications land in the bell as frames; none here: the empty sheet).
        app.bellOpen = true
        await pause()
        shot(phone, "bell"); shot(phoneDark, "bell")
        app.bellOpen = false
        // phoneToastSuccess / Error / Warning.
        app.toast("Order marked as confirmed", .success); await pause(); shot(phone, "toast-success")
        app.toast("Couldn't update the order. Please try again.", .error); await pause(); shot(phone, "toast-error")
        app.toast("Saved, but the hub has not confirmed it yet", .warning); await pause(); shot(phone, "toast-warning")
        await pause(3_800)
        // phoneOffline / tabletOffline: the device has no network.
        container.online.update(false)
        await pause()
        shot(phone, "offline"); shot(phoneDark, "offline"); shot(ipad, "offline")
        container.online.update(true)
        // sessionExpired / sessionExpiredDark.
        app.sessionExpired = true
        await pause()
        shot(phone, "session-expired"); shot(phoneDark, "session-expired"); shot(ipad, "session-expired")
        app.sessionExpired = false
        // The first thread open: full-screen on the phone (immersive), beside the list on the iPad.
        app.openConversationFor("c1")
        await quiet(transport)
        shot(phone, "thread"); shot(phoneDark, "thread"); shot(ipad, "thread")
        app.navigate(.conversations)
        // The calls console with a call ringing (CallsScreenshotTest.cardRinging) and after the caller gave up (the wrap-up).
        app.navigate(.calls)
        await quiet(transport)
        container.socket.events.emit(.object(["type": .string("incoming_call"), "call_id": .string("wacid.gallery"), "from": .string("254712345678"), "name": .string("Fr. Peter Kamau")]))
        await pause(600)
        shot(phone, "call-ringing"); shot(phoneDark, "call-ringing"); shot(ipad, "call-ringing")
        container.socket.events.emit(.object(["type": .string("call_ended"), "call_id": .string("wacid.gallery"), "status": .string("missed")]))
        await pause(600)
        shot(phone, "call-ended"); shot(phoneDark, "call-ended")
        await pause(2_500)
        app.setDark(false)
    }
}
