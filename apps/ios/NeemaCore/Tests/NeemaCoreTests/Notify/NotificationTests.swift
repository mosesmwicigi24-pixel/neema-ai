import Foundation
import XCTest
@testable import NeemaCore

/// Records what would reach the system's notification service.
final class RecordingTray: AlertSink {
    var allowed = true
    var posted: [SystemAlert] = []
    var cancelled: [Int] = []
    var summaryState: (count: Int, lines: [String])?
    var summaryCancels = 0
    /// Ids the agent swiped away.
    var swiped: Set<Int> = []
    func canPost() -> Bool { allowed }
    func post(_ alert: SystemAlert) { posted.append(alert) }
    func cancel(_ id: Int) { cancelled.append(id) }
    func active() -> Set<Int>? { Set(posted.map { $0.id }).subtracting(cancelled).subtracting(swiped) }
    func summary(count: Int, lines: [String]) { summaryState = (count, lines) }
    func cancelSummary() { summaryState = nil; summaryCancels += 1 }
}

final class RecordingPlayer: AlertPlayer {
    var plays: [(sound: Bool, vibrate: Bool)] = []
    func play(sound: Bool, vibrate: Bool) { plays.append((sound, vibrate)) }
}

/// The bell (components/ui/Notifications.tsx + useAgentNotifications). Android `core/NotificationCenterTest.kt`.
@MainActor
final class NotificationCenterTests: XCTestCase {
    private let factory = FakeSocketFactory()
    private let clock = VirtualClock()
    private let store = MemoryPrefs()
    private var centers: [AgentNotifications] = []
    private var sockets: [LiveSocket] = []

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for c in centers { c.stop() }
        for s in sockets { s.signOut() }
        AppClock.reset()
    }

    private func center() -> AgentNotifications {
        let socket = LiveSocket(factory: factory, baseUrl: "https://neema.test", token: { "t" }, sleep: clock.sleeper)
        let nc = AgentNotifications(events: socket.events, appPrefs: AppPrefs(store: MemoryPrefs()), store: store, sink: RecordingTray())
        nc.start(foreground: Watched(true))
        socket.connect("a1"); factory.last.open()
        centers.append(nc); sockets.append(socket)
        return nc
    }

    private func push(_ json: String) async { factory.last.frame(json); await drain() }

    func testFramesBecomeUnreadEntriesNewestFirst() async {
        let nc = center()
        let seen = Ref<[AppNotification]>([])
        let sub = nc.incoming.observe { n in seen.mutate { $0.append(n) } }
        await push(#"{"event":"notification","type":"new_conversation","title":"New chat from Mary","body":"Hi","wa_id":"254722000111"}"#)
        await push(#"{"event":"notification","type":"intercept","title":"🙋 Grace picked up","body":"b","conversationId":"c1"}"#)
        let items = nc.items.value
        XCTAssertEqual(items.map { $0.title }, ["🙋 Grace picked up", "New chat from Mary"])
        XCTAssertEqual(nc.unread, 2)
        XCTAssertEqual(seen.value.count, 2)
        XCTAssertTrue(items.allSatisfy { !$0.read && $0.at > 0 && !$0.id.isEmpty })
        XCTAssertEqual(Set(items.map { $0.id }).count, 2)
        sub.cancel()
    }

    func testTheTargetConversationIsReadFromEveryFieldTheBackendUses() async {
        let nc = center()
        await push(#"{"event":"notification","type":"intercept","title":"a","body":"","conversationId":"conv-1","wa_id":"w"}"#)
        await push(#"{"event":"notification","type":"draft_ready","title":"b","body":"","conv_id":"conv-2","wa_id":"w"}"#)
        await push(#"{"event":"notification","type":"new_conversation","title":"c","body":"","wa_id":"254700000000"}"#)
        await push(#"{"event":"notification","type":"standup","title":"d","body":""}"#)
        XCTAssertEqual(nc.items.value.map { $0.convKey }, [nil, "254700000000", "conv-2", "conv-1"])
    }

    func testMissingFieldsGetSafeDefaults() async {
        let nc = center()
        await push(#"{"event":"notification"}"#)
        XCTAssertEqual(nc.items.value.count, 1)
        let n = nc.items.value[0]
        XCTAssertEqual(n.type, "system"); XCTAssertEqual(n.title, "Neema"); XCTAssertEqual(n.body, ""); XCTAssertNil(n.convKey)
    }

    func testAFrameTimestampIsKeptOtherwiseArrivalTime() async {
        let nc = center()
        let before = AppClock.now()
        await push(#"{"event":"notification","type":"system","title":"late","body":"","ts":"2026-01-02T03:04:05Z"}"#)
        await push(#"{"event":"notification","type":"system","title":"now","body":"","ts":"garbage"}"#)
        XCTAssertEqual(nc.items.value.count, 2)
        let now = nc.items.value[0], late = nc.items.value[1]
        XCTAssertEqual(late.at, Int64(ISO8601DateFormatter().date(from: "2026-01-02T03:04:05Z")!.timeIntervalSince1970 * 1000))
        XCTAssertTrue(now.at >= before)
    }

    func testOnlyNotificationFramesCount() async {
        let nc = center()
        await push(#"{"type":"new_message","conversationId":"c1"}"#)
        await push(#"{"type":"intercept_changed","conversationId":"c1","mode":"human"}"#)
        await push(#"{"type":"incoming_call","call_id":"x"}"#)
        XCTAssertTrue(nc.items.value.isEmpty)
    }

    func testKeepsTheLatestSixty() async {
        let nc = center()
        for i in 0..<65 { factory.last.frame(#"{"event":"notification","type":"system","title":"n\#(i)","body":""}"#) }
        await drain()
        XCTAssertEqual(nc.items.value.count, 60)
        XCTAssertEqual(nc.items.value.first?.title, "n64")
        XCTAssertEqual(nc.items.value.last?.title, "n5")
    }

    func testReadDismissAndClear() async {
        let nc = center()
        for i in 0..<3 { await push(#"{"event":"notification","type":"system","title":"n\#(i)","body":""}"#) }
        let a = nc.items.value[0], b = nc.items.value[1], c = nc.items.value[2]
        nc.markRead(b.id)
        XCTAssertEqual(nc.items.value.map { $0.read }, [false, true, false])
        nc.dismiss(a.id)
        XCTAssertEqual(nc.items.value.map { $0.id }, [b.id, c.id])
        nc.markAllRead()
        XCTAssertEqual(nc.unread, 0)
        nc.clear()
        XCTAssertTrue(nc.items.value.isEmpty)
    }

    func testTheListSurvivesARestart() async {
        let nc = center()
        await push(#"{"event":"notification","type":"order_update","title":"Order paid","body":"BH-1042"}"#)
        nc.markAllRead()
        await drain()
        let again = center()
        XCTAssertEqual(again.items.value.map { $0.title }, ["Order paid"])
        XCTAssertEqual(again.items.value.first?.read, true)
    }

    func testEveryBackendTypeHasALook() {
        let kinds = [
            "intercept": "intercept", "human_transfer": "intercept", "media_escalation": "intercept", "take_back": "intercept", "availability_check": "intercept",
            "new_message": "new_message", "new_conversation": "new_message", "draft_ready": "new_message",
            "order": "order", "order_update": "order", "hub_event": "order",
            "transfer": "transfer",
            "system": "system", "daily_summary": "system", "planned_action": "system", "standup": "system", "selfcheck": "system", "something_new": "system",
        ]
        for (type, kind) in kinds { XCTAssertEqual(AgentNotifications.kindOf(type), kind, type) }
        XCTAssertFalse(kinds.values.contains { !["intercept", "new_message", "order", "transfer", "system"].contains($0) })
    }
}

/// The phone notifications raised for the 13 notification frames the backend
/// sends: channel, priority, text, tap target, the agent's switches, the
/// denied-permission path, and how a burst stacks in the tray. Android `core/NotificationAlertsTest.kt`.
@MainActor
final class NotificationAlertsTests: XCTestCase {
    private let factory = FakeSocketFactory()
    private let clock = VirtualClock()
    private let appPrefs = MemoryPrefs()
    private let foreground = Watched<Bool>(false)
    private let tray = RecordingTray()
    private var centers: [AgentNotifications] = []
    private var sockets: [LiveSocket] = []

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for c in centers { c.stop() }
        for s in sockets { s.signOut() }
        AppClock.reset()
    }

    private func center() -> AgentNotifications {
        let socket = LiveSocket(factory: factory, baseUrl: "https://neema.test", token: { "t" }, sleep: clock.sleeper)
        let nc = AgentNotifications(events: socket.events, appPrefs: AppPrefs(store: appPrefs), store: MemoryPrefs(), sink: tray)
        nc.start(foreground: foreground)
        socket.connect("a1"); factory.last.open()
        centers.append(nc); sockets.append(socket)
        return nc
    }

    private func push(_ type: String, title: String? = nil, body: String = "b", extra: String = "") async {
        factory.last.frame(#"{"event":"notification","type":"\#(type)","title":"\#(title ?? "t-\(type)")","body":"\#(body)"\#(extra)}"#)
        await drain()
    }

    func testAll13BackendTypesGetTheRightChannelPriorityAndTapTarget() async {
        _ = center()
        struct Case { let type: String; let extra: String; let channel: String; let priority: AlertPriority; let conv: String?; let view: String? }
        let cases = [
            Case(type: "new_conversation", extra: #","wa_id":"254700000001""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "254700000001", view: nil),
            Case(type: "new_message", extra: #","conversationId":"c-sms""#, channel: Notifier.CH_MESSAGES, priority: .normal, conv: "c-sms", view: nil),
            Case(type: "human_transfer", extra: #","waId":"254700000002","conversationId":"c-media","mediaType":"image""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "c-media", view: nil),
            Case(type: "media_escalation", extra: #","wa_id":"254700000003","conv_id":"c-doc""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "c-doc", view: nil),
            Case(type: "intercept", extra: #","conversationId":"c-int""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "c-int", view: nil),
            Case(type: "system", extra: #","conversationId":"c-rel""#, channel: Notifier.CH_UPDATES, priority: .low, conv: "c-rel", view: nil),
            Case(type: "draft_ready", extra: #","conv_id":"c-draft","wa_id":"254700000004""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "c-draft", view: nil),
            Case(type: "availability_check", extra: #","conv_id":"c-avail""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "c-avail", view: nil),
            Case(type: "take_back", extra: #","conv_id":"c-take","wa_id":"254700000005""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "c-take", view: nil),
            Case(type: "planned_action", extra: #","conv_id":"c-plan","wa_id":"254700000006""#, channel: Notifier.CH_ALERTS, priority: .high, conv: "c-plan", view: nil),
            Case(type: "standup", extra: "", channel: Notifier.CH_UPDATES, priority: .low, conv: nil, view: nil),
            Case(type: "hub_event", extra: "", channel: Notifier.CH_ALERTS, priority: .high, conv: nil, view: "orders"),
            Case(type: "selfcheck", extra: "", channel: Notifier.CH_UPDATES, priority: .low, conv: nil, view: nil),
        ]
        XCTAssertEqual(cases.count, 13)
        for c in cases { await push(c.type, title: "Title \(c.type)", body: "Body \(c.type)", extra: c.extra) }
        XCTAssertEqual(tray.posted.count, 13)
        for (c, a) in zip(cases, tray.posted) {
            XCTAssertEqual(a.channel, c.channel, c.type)
            XCTAssertEqual(a.priority, c.priority, c.type)
            XCTAssertEqual(a.convKey, c.conv, c.type)
            XCTAssertEqual(a.view, c.view, c.type)
            XCTAssertEqual(a.title, "Title \(c.type)")
            XCTAssertEqual(a.body, "Body \(c.type)")
            XCTAssertNotNil(a.notificationId, "tapping marks the bell entry read")
        }
    }

    func testAHubEventWithAThreadOpensTheThread() async {
        _ = center()
        await push("hub_event", extra: #","conv_id":"c9","wa_id":"254711""#)
        XCTAssertEqual(tray.posted.count, 1)
        XCTAssertEqual(tray.posted[0].convKey, "c9")
        XCTAssertNil(tray.posted[0].view)
    }

    func testTheWebsLegacyTypesStillMap() async {
        _ = center()
        appPrefs.set(true, for: "notif_order_updates")
        await push("order_update"); await push("transfer", extra: #","conv_id":"c1""#); await push("daily_summary")
        XCTAssertEqual(tray.posted.map { $0.channel }, [Notifier.CH_ALERTS, Notifier.CH_ALERTS, Notifier.CH_UPDATES])
        XCTAssertEqual(tray.posted[0].view, "orders")
    }

    func testNoSystemNotificationWhileTheAppIsInFront() async {
        let nc = center()
        foreground.value = true
        await push("intercept", extra: #","conversationId":"c1""#)
        XCTAssertTrue(tray.posted.isEmpty)
        XCTAssertEqual(nc.items.value.count, 1, "the bell still has it")
        foreground.value = false
        await push("intercept", title: "later", extra: #","conversationId":"c1""#)
        XCTAssertEqual(tray.posted.count, 1)
    }

    func testTheProfileSwitchesSilenceThePhoneButNotTheBell() async {
        let nc = center()
        appPrefs.set(false, for: "notif_new_conv"); appPrefs.set(false, for: "notif_human_transfer"); appPrefs.set(false, for: "notif_daily_summary")
        for t in ["new_conversation", "new_message", "human_transfer", "transfer", "media_escalation", "standup", "daily_summary", "order_update"] { await push(t) }
        XCTAssertTrue(tray.posted.isEmpty, "all switched off (order updates are off by default)")
        XCTAssertEqual(nc.items.value.count, 8)
        await push("intercept")
        XCTAssertEqual(tray.posted.count, 1, "escalations have no switch")
    }

    func testOrderUpdatesAreOptIn() async {
        _ = center()
        await push("order_update")
        XCTAssertTrue(tray.posted.isEmpty)
        appPrefs.set(true, for: "notif_order_updates")
        await push("order_update", title: "Order paid")
        XCTAssertEqual(tray.posted.map { $0.title }, ["Order paid"])
    }

    func testDeniedNotificationPermissionDegradesToTheBellAndToast() async {
        let nc = center()
        let seen = Ref<[AppNotification]>([])
        let sub = nc.incoming.observe { n in seen.mutate { $0.append(n) } }
        tray.allowed = false
        await push("intercept", extra: #","conversationId":"c1""#)
        XCTAssertTrue(tray.posted.isEmpty)
        XCTAssertNil(tray.summaryState)
        XCTAssertEqual(nc.items.value.count, 1)
        XCTAssertEqual(seen.value.count, 1, "the in-app toast still fires")
        sub.cancel()
    }

    func testAnExactRepeatWithinSecondsIsDropped() async {
        let nc = center()
        for _ in 0..<3 { await push("intercept", title: "🤖 AI Escalation", body: "wants a human", extra: #","conversationId":"c1""#) }
        XCTAssertEqual(nc.items.value.count, 1)
        XCTAssertEqual(tray.posted.count, 1)
        await push("intercept", title: "🤖 AI Escalation", body: "wants a human", extra: #","conversationId":"c2""#)
        XCTAssertEqual(nc.items.value.count, 2, "another thread is not a repeat")
    }

    func testAThreadsNewerAlertReplacesItsOlderOne() async {
        _ = center()
        await push("intercept", title: "🤖 AI Escalation", extra: #","conversationId":"c1""#)
        await push("intercept", title: "🙋 Grace picked up", extra: #","conversationId":"c1""#)
        XCTAssertEqual(tray.posted[0].id, tray.posted[1].id)
        XCTAssertNil(tray.summaryState, "one thread, one row: no summary")
    }

    func testABurstStacksUnderOneSummary() async {
        _ = center()
        await push("new_conversation", title: "New chat from Mary", body: "Hi", extra: #","wa_id":"2547001""#)
        XCTAssertNil(tray.summaryState)
        await push("new_conversation", title: "New chat from John", body: "Price?", extra: #","wa_id":"2547002""#)
        await push("standup", title: "☀️ Neema's morning standup", body: "")
        XCTAssertEqual(tray.summaryState?.count, 3)
        XCTAssertEqual(tray.summaryState?.lines, ["☀️ Neema's morning standup", "New chat from John — Price?", "New chat from Mary — Hi"])
        XCTAssertEqual(Set(tray.posted.map { $0.id }).count, 3, "distinct rows")
        XCTAssertTrue(tray.posted.allSatisfy { $0.id >= 10_000 && $0.id != Notifier.SUMMARY_ID })
    }

    func testSwipedAwayRowsLeaveTheSummaryCount() async {
        _ = center()
        await push("new_conversation", extra: #","wa_id":"1""#)
        await push("new_conversation", extra: #","wa_id":"2""#)
        tray.swiped.formUnion(tray.posted.map { $0.id })
        await push("new_conversation", extra: #","wa_id":"3""#)
        await push("new_conversation", extra: #","wa_id":"4""#)
        XCTAssertEqual(tray.summaryState?.count, 2)
    }

    func testReadingInTheBellTakesItOutOfTheTray() async {
        let nc = center()
        await push("new_conversation", extra: #","wa_id":"1""#)
        await push("new_conversation", extra: #","wa_id":"2""#)
        let second = nc.items.value[0], first = nc.items.value[1]
        nc.markRead(first.id)
        XCTAssertEqual(tray.cancelled, [tray.posted[0].id])
        nc.dismiss(second.id)
        XCTAssertEqual(tray.cancelled.count, 2)
        XCTAssertNil(tray.summaryState, "nothing left: the summary goes too")
    }

    func testMarkAllReadAndClearEmptyTheTray() async {
        let nc = center()
        for i in 0..<3 { await push("new_conversation", extra: #","wa_id":"\#(i)""#) }
        nc.markAllRead()
        XCTAssertEqual(tray.cancelled.count, 3)
        XCTAssertNil(tray.summaryState)
        await push("intercept", extra: #","conversationId":"x""#)
        nc.clear()
        XCTAssertEqual(tray.cancelled.count, 4)
        XCTAssertTrue(tray.summaryCancels > 0)
    }

    func testTheTargetIsTheSameInTheBellAndTheTray() {
        func n(_ type: String, _ conv: String?) -> AppNotification { AppNotification(id: "i", type: type, title: "t", body: "b", convKey: conv, at: 1) }
        XCTAssertEqual(AgentNotifications.viewFor(n("order_update", nil)), "orders")
        XCTAssertEqual(AgentNotifications.viewFor(n("hub_event", nil)), "orders")
        XCTAssertNil(AgentNotifications.viewFor(n("hub_event", "c1")))
        XCTAssertNil(AgentNotifications.viewFor(n("standup", nil)))
        XCTAssertNotEqual(AgentNotifications.systemId(n("intercept", "c1")), AgentNotifications.systemId(n("intercept", "c2")))
        XCTAssertEqual(AgentNotifications.systemId(n("intercept", "c1")), AgentNotifications.systemId(AppNotification(id: "other", type: "system", title: "x", body: "y", convKey: "c1", at: 2)))
        XCTAssertFalse([1001, 1002, 2001].contains(AgentNotifications.systemId(n("standup", nil))))
    }
}

/// Every customer message beeps and buzzes: open or closed, what mute and the
/// Profile switches silence, what a burst sounds like, what reaches the tray
/// and what never beeps (our own replies, the AI's, team updates). Android `core/MessageAlertsTest.kt`.
@MainActor
final class MessageAlertsTests: XCTestCase {
    private let factory = FakeSocketFactory()
    private let clock = VirtualClock()
    private let raw = MemoryPrefs()
    private let foreground = Watched<Bool>(false)
    private let tray = RecordingTray()
    private let player = RecordingPlayer()
    private var now: Int64 = 1_000_000
    private var prefs: AppPrefs!
    private var keep: [AnyObject] = []
    private var plays: [(sound: Bool, vibrate: Bool)] { player.plays }

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for k in keep { (k as? AgentNotifications)?.stop(); (k as? MessageAlerts)?.stop(); (k as? LiveSocket)?.signOut() }
        ContactNames.shared.clear()
        AppClock.reset()
    }

    @discardableResult
    private func start() -> MessageAlerts {
        prefs = AppPrefs(store: raw)
        let socket = LiveSocket(factory: factory, baseUrl: "https://neema.test", token: { "t" }, sleep: clock.sleeper)
        let nc = AgentNotifications(events: socket.events, appPrefs: prefs, store: MemoryPrefs(), sink: tray)
        nc.start(foreground: foreground)
        let ma = MessageAlerts(events: socket.events, notifications: nc, prefs: prefs, sink: tray, player: player, gate: AlertGate(), now: { [unowned self] in self.now })
        ma.start(foreground: foreground)
        socket.connect("a1"); factory.last.open()
        keep.append(socket); keep.append(nc); keep.append(ma)
        return ma
    }

    private func customer(_ text: String = "Do you have albs in size M?", conv: String = "c1", extra: String = "") async {
        factory.last.frame(#"{"type":"new_message","conversationId":"\#(conv)","sender":"user","text":"\#(text)"\#(extra)}"#)
        await drain()
    }
    private func frame(_ json: String) async { factory.last.frame(json); await drain() }
    private func playsEqual(_ expected: [(Bool, Bool)], _ msg: String = "", line: UInt = #line) {
        XCTAssertEqual(plays.map { "\($0.sound)/\($0.vibrate)" }, expected.map { "\($0.0)/\($0.1)" }, msg, line: line)
    }

    func testInTheBackgroundAMessageBeepsBuzzesAndShowsInTheTray() async {
        ContactNames.shared.learn([Conversation(id: "c1", waId: "254700111222", name: "Fr. Peter Kamau")])
        start()
        await customer(extra: #","waId":"254700111222""#)
        playsEqual([(true, true)])
        XCTAssertEqual(tray.posted.count, 1)
        let row = tray.posted[0]
        XCTAssertEqual(row.channel, Notifier.CH_MESSAGES)
        XCTAssertEqual(row.title, "Fr. Peter Kamau")
        XCTAssertEqual(row.body, "Do you have albs in size M?")
        XCTAssertEqual(row.convKey, "c1", "tap opens the chat")
    }

    func testInTheForegroundItBeepsWithoutATrayRow() async {
        foreground.value = true
        start()
        await customer()
        playsEqual([(true, true)])
        XCTAssertTrue(tray.posted.isEmpty)
    }

    func testOnlyTheCustomersOwnMessagesBeep() async {
        start()
        await frame(#"{"type":"new_message","conversationId":"c1","sender":"ai","text":"Yes, we do"}"#)
        await frame(#"{"type":"new_message","conversationId":"c1","sender":"human_agent","text":"Sending now"}"#)
        await frame(#"{"type":"message","conversationId":"c1","direction":"outbound","text":"Order confirmed"}"#)
        await frame(#"{"type":"intercept_changed","conversationId":"c1","mode":"human"}"#)
        XCTAssertTrue(plays.isEmpty); XCTAssertTrue(tray.posted.isEmpty)
        // The older inbound shape (web chat, TikTok) does.
        now += 5_000
        await frame(#"{"type":"message","conversationId":"c2","direction":"inbound","text":"hi","channel":"web_chat"}"#)
        XCTAssertEqual(plays.count, 1)
        XCTAssertEqual(tray.posted.map { $0.title }, ["Website chat customer · Website chat"])
    }

    func testMuteSilencesUntilItEnds() async {
        start()
        prefs.muteFor(3_600_000, now: now)
        await customer()
        XCTAssertTrue(plays.isEmpty, "muted: no sound, no buzz")
        XCTAssertEqual(tray.posted.count, 1, "still in the tray")
        now += 3_600_001
        await customer("Are you there?")
        playsEqual([(true, true)])
        // Until turned back on: stays silent however long it has been; unmute restores.
        prefs.muteFor(nil, now: now)
        now += 30 * 24 * 3_600_000
        await customer("Hello?")
        XCTAssertEqual(plays.count, 1)
        prefs.unmute()
        now += 5_000
        await customer("Hello??")
        XCTAssertEqual(plays.count, 2)
    }

    func testTheSwitchesChooseSoundAndBuzz() async {
        start()
        var a = prefs.alerts.value; a.messageSound = false; prefs.setAlerts(a)
        await customer()
        XCTAssertEqual("\(plays.last!.sound)/\(plays.last!.vibrate)", "false/true")
        now += 5_000
        a = prefs.alerts.value; a.messageVibrate = false; prefs.setAlerts(a)
        await customer("again")
        XCTAssertEqual(plays.count, 1)
    }

    func testABurstBeepsOnce() async {
        start()
        for i in 0..<5 { now += 200; await customer("", extra: #","mediaType":"image","mediaUrl":"u\#(i)""#) }
        XCTAssertEqual(plays.count, 1)
        XCTAssertEqual(tray.posted.last?.body, "📷 Photo")
        XCTAssertEqual(Set(tray.posted.map { $0.id }).count, 1, "one row per customer")
        // Two seconds on, the next message beeps again.
        now += 2_500
        await customer("Which is cheaper?")
        XCTAssertEqual(plays.count, 2)
    }

    func testANewChatAndItsFirstMessageBeepOnceInOneRow() async {
        start()
        await frame(#"{"event":"notification","type":"new_conversation","title":"New chat from Mary","body":"Hi","wa_id":"254722000111"}"#)
        await customer("Hi", conv: "c-new", extra: #","waId":"254722000111""#)
        XCTAssertEqual(plays.count, 1)
        XCTAssertEqual(Set(tray.posted.map { $0.id }).count, 1)
    }

    func testTheNewConversationsSwitchSilencesMessages() async {
        raw.set(false, for: "notif_new_conv")
        start()
        await customer()
        XCTAssertTrue(plays.isEmpty); XCTAssertTrue(tray.posted.isEmpty)
    }

    func testAlertsBeepTeamUpdatesDoNot() async {
        foreground.value = true
        start()
        await frame(#"{"event":"notification","type":"standup","title":"Morning standup","body":"3 follow-ups"}"#)
        await frame(#"{"event":"notification","type":"system","title":"Released to Neema","body":"x"}"#)
        XCTAssertTrue(plays.isEmpty)
        await frame(#"{"event":"notification","type":"human_transfer","title":"Transferred to you","body":"Mary","conversationId":"c7"}"#)
        XCTAssertEqual(plays.count, 1)
    }

    func testOpeningTheAppClearsMessageRows() async {
        start()
        await customer(conv: "c1"); now += 3_000; await customer(conv: "c2")
        foreground.value = true
        await drain()
        XCTAssertEqual(Set(tray.posted.map { $0.id }), Set(tray.cancelled))
    }

    func testMessengerWithoutANameSaysWhichApp() async {
        start()
        await customer("price?", conv: "m1", extra: #","channel":"messenger""#)
        XCTAssertEqual(tray.posted.map { $0.title }, ["Messenger customer · Messenger"])
    }

    func testInboundFramesAreRecognised() {
        XCTAssertEqual(inboundPingOf(JSONValue.parse(#"{"type":"new_message","conversationId":"c","sender":"user","mediaType":"audio"}"#)!)?.preview, "🎤 Voice message")
        XCTAssertEqual(inboundPingOf(JSONValue.parse(#"{"type":"new_message","conversationId":"c","sender":"user","text":"hi","channel":"sms"}"#)!)?.app, "SMS")
        XCTAssertNil(inboundPingOf(JSONValue.parse(#"{"event":"notification","type":"new_message","conversationId":"c"}"#)!), "the SMS bridge's agent ping is not a message")
        XCTAssertNil(inboundPingOf(JSONValue.parse(#"{"type":"new_message","sender":"user","text":"hi"}"#)!), "no thread, nothing to open")
    }

    func testThePhonesRingerSwitchWins() {
        func plan(_ s: Bool, _ v: Bool, _ m: RingerMode, _ dnd: Bool) -> String { let p = ringerPlan(sound: s, vibrate: v, ringerMode: m, dnd: dnd); return "\(p.sound)/\(p.vibrate)" }
        XCTAssertEqual(plan(true, true, .normal, false), "true/true")
        XCTAssertEqual(plan(true, true, .vibrate, false), "false/true")
        XCTAssertEqual(plan(true, true, .silent, false), "false/false")
        XCTAssertEqual(plan(true, true, .normal, true), "false/false")
        XCTAssertEqual(plan(false, false, .normal, false), "false/false")
    }

    func testMuteReadsInPlainWords() {
        let zone = TimeZone(identifier: "Africa/Nairobi")!
        var cal = Calendar(identifier: .gregorian); cal.timeZone = zone
        let now = Int64(cal.date(from: DateComponents(year: 2026, month: 9, day: 28, hour: 14, minute: 40))!.timeIntervalSince1970 * 1000)
        XCTAssertNil(muteStatus(until: 0, now: now, zone: zone))
        XCTAssertEqual(muteStatus(until: now + 3_600_000, now: now, zone: zone), "Muted until 3:40 PM")
        XCTAssertEqual(muteStatus(until: now + 32 * 3_600_000, now: now, zone: zone), "Muted until tomorrow, 10:40 PM")
        XCTAssertEqual(muteStatus(until: AlertSettings.FOREVER, now: now, zone: zone), "Muted until you turn it back on")
        XCTAssertNil(muteStatus(until: now - 1, now: now, zone: zone), "an ended mute")
    }

    func testSettingsPersist() async {
        start()
        prefs.setAlerts(AlertSettings(messageSound: false, messageVibrate: true, callRing: false, callVibrate: true, mutedUntil: 42))
        let again = AppPrefs(store: raw).alerts.value
        XCTAssertEqual(again, AlertSettings(messageSound: false, messageVibrate: true, callRing: false, callVibrate: true, mutedUntil: 42))
        XCTAssertEqual(AppPrefs(store: MemoryPrefs()).alerts.value, AlertSettings(), "defaults: everything on, not muted")
    }
}
