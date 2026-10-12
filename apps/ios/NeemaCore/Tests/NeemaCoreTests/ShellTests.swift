import XCTest
@testable import NeemaCore

/// The shell's rules: views and their web names, deep links, the way back, toasts, access and the nav.
final class ShellTests: XCTestCase {
    func testViewNamesMatchTheWeb() {
        XCTAssertEqual(.conversations, ViewId.fromWeb("inbox"))
        XCTAssertEqual(.conversations, ViewId.fromWeb("Conversations"))
        XCTAssertEqual(.overview, ViewId.fromWeb("analytics"))
        XCTAssertEqual(.agents, ViewId.fromWeb("team"))
        XCTAssertNil(ViewId.fromWeb("billing"))
        XCTAssertNil(ViewId.fromWeb(nil))
        XCTAssertEqual(["Inbox", "Calls", "Orders", "Reports", "Deals", "Leads", "Analytics", "Catalog", "Team", "Settings", "Profile"], ViewId.allCases.map { $0.label })
    }

    func testDeepLinksFromTheDashboardAndTheScheme() {
        let a = DeepLink(url: URL(string: "https://neema.bethanyhouse.co.ke/dashboard?open=254712345678&ref=BH-1042")!)!
        XCTAssertEqual(.openConversation(key: "254712345678|BH-1042"), a.action)
        let b = DeepLink(url: URL(string: "neema://x?view=calls&caller=254712345678")!)!
        XCTAssertEqual(.focusCalls(waId: "254712345678"), b.action)
        let c = DeepLink(url: URL(string: "neema://dashboard?view=team")!)!
        XCTAssertEqual(.navigate(.agents), c.action)
        XCTAssertNil(DeepLink(url: URL(string: "https://neema.bethanyhouse.co.ke/login?view=orders")!), "only the dashboard path")
        XCTAssertNil(DeepLink(url: URL(string: "https://evil.test/dashboard?view=orders")!), "only our host")
        let empty = DeepLink(url: URL(string: "neema://dashboard")!)!
        XCTAssertTrue(empty.isEmpty)
        XCTAssertNil(DeepLink(view: "billing").action, "unknown views are ignored")
        XCTAssertEqual(.openConversation(key: "k"), DeepLink(open: "k", ref: " ", view: "orders").action, "open wins over view")
        XCTAssertEqual(.navigate(.calls), DeepLink(view: "calls", caller: "").action)
    }

    func testTheWayBackKeepsEachViewOnceAndTenAtMost() {
        var nav = NavHistory()
        XCTAssertFalse(nav.canGoBack)
        nav.navigate(.orders); nav.navigate(.calls); nav.navigate(.orders)
        XCTAssertEqual(.orders, nav.view)
        XCTAssertEqual([.conversations, .calls], nav.history, "orders left the history when it became the view again")
        XCTAssertTrue(nav.back()); XCTAssertEqual(.calls, nav.view)
        XCTAssertTrue(nav.back()); XCTAssertEqual(.conversations, nav.view)
        XCTAssertFalse(nav.back(), "on the inbox with nothing left: leave the app")
        nav.navigate(.profile)
        nav = NavHistory(view: .profile, history: [])
        XCTAssertTrue(nav.back(), "any other view goes back to the inbox first")
        XCTAssertEqual(.conversations, nav.view)
        var long = NavHistory()
        for v in ViewId.allCases { long.navigate(v) }
        for v in ViewId.allCases.reversed() { long.navigate(v) }
        XCTAssertEqual(NavHistory.MAX, long.history.count)
        long.reset()
        XCTAssertEqual(NavHistory(), long)
    }

    func testAToastShowsForThreeAndAHalfSecondsOnlyWhileInFront() async {
        let clock = VirtualClock()
        let fg = Watched<Bool>(true)
        let p = ToastPresenter(foreground: fg, sleep: clock.sleeper, now: { clock.now })
        p.show("Saved")
        XCTAssertEqual("Saved", p.current.value?.message)
        await clock.advance(by: 3_499)
        XCTAssertNotNil(p.current.value)
        await clock.advance(by: 2)
        await eventually { p.current.value == nil }
        XCTAssertNil(p.current.value)

        // Raised while away: waits, then shows for the whole time.
        fg.update(false)
        p.show("Order marked as confirmed", .info)
        await clock.advance(by: 10_000)
        XCTAssertNotNil(p.current.value, "nothing counts while the app is away")
        fg.update(true)
        await clock.advance(by: 3_000)
        XCTAssertNotNil(p.current.value)
        // Going away after 3 s leaves 0.5 s, raised to the 1.5 s minimum on return.
        fg.update(false)
        await settle()
        await clock.advance(by: 60_000)
        XCTAssertNotNil(p.current.value)
        fg.update(true)
        await clock.advance(by: 1_499)
        XCTAssertNotNil(p.current.value)
        await clock.advance(by: 2)
        await eventually { p.current.value == nil }
        XCTAssertNil(p.current.value)
    }

    func testANewerToastReplacesTheOldAndKeepsItsOwnTime() async {
        let clock = VirtualClock()
        let fg = Watched<Bool>(true)
        let p = ToastPresenter(foreground: fg, sleep: clock.sleeper, now: { clock.now })
        var all: [String] = []
        let sub = p.toasts.observe { all.append($0.message) }
        defer { sub.cancel() }
        p.show("one")
        await clock.advance(by: 3_000)
        p.show("two", .error)
        await clock.advance(by: 3_000)
        XCTAssertEqual("two", p.current.value?.message, "the first toast's timer must not clear the second")
        await clock.advance(by: 600)
        await eventually { p.current.value == nil }
        XCTAssertEqual(["one", "two"], all)
        p.show("three")
        p.dismiss(Toast(message: "x", type: .info, id: -1))
        XCTAssertEqual("three", p.current.value?.message, "dismissing another toast changes nothing")
        p.dismiss()
        XCTAssertNil(p.current.value)
    }

    private func agent(_ id: String, _ email: String, role: String, superuser: Bool = false, custom: [String]? = nil) -> Agent {
        var a = Agent(id: id, name: id, email: email, role: role)
        a.isSuperuser = superuser
        a.customPermissions = custom
        return a
    }

    private func session(_ id: String, _ email: String, role: String) -> Session {
        Session(accessToken: "t", refreshToken: nil, agentId: id, email: email, name: "", role: role, isSuperuser: false, mode: "direct")
    }

    func testAccessIsNothingUntilTheTeamRowLandsThenTheRowDecides() {
        let s = session("a1", "moses@bethanyhouse.co.ke", role: "agent")
        let none = ShellRules.access(agents: [], me: nil, session: s)
        XCTAssertTrue(none.permissions.isEmpty)
        XCTAssertFalse(none.isAdmin)
        let row = agent("a1", "MOSES@bethanyhouse.co.ke", role: "agent", custom: ["view_orders"])
        let byEmail = ShellRules.access(agents: [row], me: nil, session: session("other-id", "moses@bethanyhouse.co.ke", role: "agent"))
        XCTAssertEqual(["view_orders"], byEmail.permissions, "matched by email when the id differs")
        XCTAssertFalse(byEmail.isAdmin)
        XCTAssertTrue(ShellRules.access(agents: [row], me: nil, session: session("a1", "", role: "admin")).isAdmin, "the session's role is enough")
        XCTAssertTrue(ShellRules.access(agents: [agent("a1", "m@b", role: "agent", superuser: true)], me: nil, session: s).isAdmin)
        XCTAssertTrue(ShellRules.access(agents: [agent("a1", "m@b", role: "agent", custom: ["manage_agents"])], me: nil, session: s).isAdmin)
        XCTAssertTrue(ShellRules.access(agents: [agent("a1", "m@b", role: "admin")], me: nil, session: s).can("manage_settings"))
    }

    func testNavItemsAreGatedLikeTheWeb() {
        let everyone = ShellRules.navItems(can: { _ in false }, humanConvs: 2, pendingOrders: 5)
        XCTAssertEqual([.conversations, .calls, .orders, .profile], everyone.map { $0.view })
        XCTAssertEqual([2, 0, 5, 0], everyone.map { $0.badge })
        let admin = ShellRules.navItems(can: { _ in true }, humanConvs: 0, pendingOrders: 0)
        XCTAssertEqual(ViewId.allCases, admin.map { $0.view })
        let leadsOnly = ShellRules.navItems(can: { $0 == "view_leads" }, humanConvs: 0, pendingOrders: 0)
        XCTAssertEqual([.conversations, .calls, .orders, .deals, .leads, .profile], leadsOnly.map { $0.view })
    }
}
