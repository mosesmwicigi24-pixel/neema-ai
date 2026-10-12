import XCTest
import UIKit
import NeemaCore
@testable import Neema

/// Smoke tests for the app layer; the rules themselves are tested in NeemaCore.
@MainActor
final class NeemaAppTests: XCTestCase {
    private final class NoNetwork: HTTPTransport {
        func send(_ request: HTTPRequest) async throws -> HTTPResponse { throw TransportError.network("offline") }
    }

    private final class NoSockets: WebSocketFactory {
        final class Dead: WebSocketConnection {
            let url: URL
            init(_ u: URL) { url = u }
            func send(text: String) {}
            func close(code: Int, reason: String?) {}
            func cancel() {}
        }
        var opened: [URL] = []
        func newWebSocket(url: URL, events: WebSocketEvents) -> WebSocketConnection { opened.append(url); return Dead(url) }
    }

    private func container(session: Session? = nil) -> (AppContainer, NoSockets) {
        let store = MemoryStore()
        let sockets = NoSockets()
        let c = AppContainer(baseUrl: "https://neema.test", store: store, transport: NoNetwork(), socketFactory: sockets, watchNetwork: false)
        if let s = session { c.sessionStore.save(s) }
        return (c, sockets)
    }

    private var session: Session {
        Session(accessToken: "t", refreshToken: nil, agentId: "a1", email: "m@b.co", name: "Moses", role: "admin", isSuperuser: true, mode: "direct")
    }

    func testSignedOutShowsNoViewAndKeepsADeepLinkForLater() {
        let (c, _) = container()
        let app = AppModel(container: c)
        XCTAssertNil(app.session)
        app.open(URL(string: "neema://x?view=orders")!)
        XCTAssertEqual(.conversations, app.view, "nothing to navigate while signed out")
        c.sessionStore.save(session)
        let exp = expectation(description: "replayed after sign-in")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { exp.fulfill() }
        wait(for: [exp], timeout: 2)
        XCTAssertEqual(.orders, app.view)
    }

    func testTheSocketFollowsTheSessionAndTheForeground() {
        let (c, sockets) = container(session: session)
        let app = AppModel(container: c)
        XCTAssertTrue(sockets.opened.isEmpty, "not in front yet")
        app.setForeground(true)
        XCTAssertEqual(1, sockets.opened.count)
        XCTAssertTrue(sockets.opened[0].absoluteString.hasPrefix("wss://neema.test/ws/a1?token="))
        app.logout()
        XCTAssertNil(app.session)
        XCTAssertEqual(.conversations, app.view)
    }

    func testNavItemsFollowAccess() {
        let (c, _) = container(session: session)
        let app = AppModel(container: c)
        XCTAssertEqual([.conversations, .calls, .orders, .profile], app.navItems.map { $0.view }, "nothing is gated open until the team row lands")
        XCTAssertTrue(app.isAdmin, "the session's role is enough for isAdmin")
    }

    func testThemeTokensAndFontsResolve() {
        XCTAssertFalse(NeemaColors.light.isDark)
        XCTAssertTrue(NeemaColors.dark.isDark)
        XCTAssertNotNil(UIFont(name: "Manrope-Regular", size: 14), "the bundled fonts are registered")
        XCTAssertNotNil(UIFont(name: "DMMono-Regular", size: 14))
    }
}
