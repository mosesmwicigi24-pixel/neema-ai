import Foundation
import XCTest
@testable import NeemaCore

/// Lifecycle and state (Android `InboxLifecycleTest`): what a phone does to
/// the app — the system reclaiming it in the background (a fresh host and
/// model on the same disk — the inbox's `InboxMemory`), a 401 in the middle
/// of a send, a deep link or a notification tap landing while the agent is
/// mid-task, sign-out on a shared phone, and back.
@MainActor
final class InboxLifecycleTests: XCTestCase {
    var fake: FakeNeema!
    var server: InboxNetFixtures.Server!
    let clock = VirtualClock()
    let snapshots = SnapshotCache.temporary()

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
        server = InboxNetFixtures.Server(fake)
    }

    override func tearDown() async throws { AppClock.reset(); snapshots.clear(); try await super.tearDown() }

    struct App { let host: TestHost; let vm: InboxViewModel }

    func start(_ host: TestHost? = nil) async -> App {
        let h = host ?? TestHost(fake: fake, clock: clock, snapshots: snapshots)
        let vm = InboxViewModel(host: h, sleep: clock.sleeper)
        await drain()
        return App(host: h, vm: vm)
    }

    /// The system kills the process: nothing is torn down politely, the
    /// in-memory state is gone, and a fresh app starts on the same disk. The
    /// old model's work is stopped by closing it around a COPY of the memory
    /// file, so only what reached disk before counts.
    func processDeath(_ a: App, before: () -> Void = {}) async -> App {
        let saved: InboxMemory? = snapshots.read(Fixtures.ME_ID, Inbox.MEMORY_KEY)
        a.vm.close()
        snapshots.write(Fixtures.ME_ID, Inbox.MEMORY_KEY, saved ?? InboxMemory())
        before()
        return await start()
    }

    func idle(_ ms: Int64) async { await clock.advance(by: ms) }
    func memory() -> InboxMemory? { snapshots.read(Fixtures.ME_ID, Inbox.MEMORY_KEY) }
    func replies(_ conv: String = "c1") -> Int { fake.calls.filter { $0.method == "POST" && $0.path == "/admin/conversations/\(conv)/reply" }.count }
    func mine(_ vm: InboxViewModel, _ id: String = "c1") -> [ThreadMsg] { (vm.thread.value.messages[id] ?? []).filter { $0.id.hasPrefix("optimistic-") } }

    // ═══════════════ The composer draft ═══════════════

    /// Each customer keeps their own draft (the web's single replyText would carry it to the next person).
    func testDraftIsPerCustomerAndComesBackWhenSwitchingBack() async {
        let a = await start()
        a.vm.select("c1"); a.vm.setReplyText("For Fr. Peter")
        a.vm.select("c2"); XCTAssertEqual(a.vm.composer.value.replyText, "")
        a.vm.setReplyText("For Rev. Mary")
        a.vm.select("c1"); XCTAssertEqual(a.vm.composer.value.replyText, "For Fr. Peter")
        // The same person's other channel shares the draft (c5 is Fr. Peter on Facebook).
        a.vm.select("c5"); XCTAssertEqual(a.vm.composer.value.replyText, "For Fr. Peter")
        a.vm.select("c2"); XCTAssertEqual(a.vm.composer.value.replyText, "For Rev. Mary")
        await drain()
    }

    func testProcessDeathRestoresTheOpenThreadTheFiltersTheSearchAndEveryDraft() async {
        let a = await start()
        a.vm.setTab("human"); await drain()
        a.vm.select("c1"); await drain()
        a.vm.setReplyText("Half a reply for Fr. Peter")
        a.vm.beginReplyTo(a.vm.thread.value.messages["c1"]!.last { $0.inbound }!)
        a.vm.select("c6"); await drain()
        a.vm.setReplyText("Measurements — ")
        a.vm.showNote(true); a.vm.setNoteText("Call back after 5")
        await idle(InboxViewModel.MEMORY_DEBOUNCE_MS + 50)
        // It reached disk after a pause in typing (no teardown needed).
        let m = memory()!
        XCTAssertEqual(m.activeId, "c6"); XCTAssertTrue(m.threadOpen); XCTAssertEqual(m.tab, "human")
        XCTAssertEqual(m.composers["p:p1"]?.replyText, "Half a reply for Fr. Peter")

        let n = fake.calls.count
        let b = await processDeath(a)
        // The first list request is already the restored filter's: no flash of "All".
        XCTAssertTrue(fake.calls.dropFirst(n).first { $0.method == "GET" && $0.path == "/admin/conversations" }!.query!.contains("tab=human"))
        XCTAssertEqual(b.vm.inbox.value.filters.tab, "human")
        XCTAssertEqual(b.vm.thread.value.activeId, "c6")
        XCTAssertTrue(b.vm.thread.value.threadOpen)
        XCTAssertEqual(b.vm.composer.value.replyText, "Measurements — ")
        XCTAssertTrue(b.vm.dialogs.value.note); XCTAssertEqual(b.vm.dialogs.value.noteText, "Call back after 5")
        b.vm.select("c1"); await drain()
        XCTAssertEqual(b.vm.composer.value.replyText, "Half a reply for Fr. Peter")
        XCTAssertNotNil(b.vm.composer.value.quoted, "the quoted message comes back too")
        // The note stays with its own thread.
        XCTAssertFalse(b.vm.dialogs.value.note)
        b.vm.select("c6"); await drain()
        XCTAssertEqual(b.vm.dialogs.value.noteText, "Call back after 5")
    }

    func testProcessDeathInTheBackgroundSavesAtOnceNoDebounceNeeded() async {
        let a = await start()
        a.vm.select("c2"); await drain()
        a.vm.setReplyText("Typed a moment before switching apps")
        a.host.foreground.value = false   // the system may now kill it at any moment
        XCTAssertEqual(memory()?.composers["c2"]?.replyText, "Typed a moment before switching apps")
        let b = await processDeath(a)
        XCTAssertEqual(b.vm.thread.value.activeId, "c2")
        XCTAssertEqual(b.vm.composer.value.replyText, "Typed a moment before switching apps")
    }

    func testProcessDeathSearchAsTypedComesBackAndRuns() async {
        let a = await start()
        a.vm.setSearch("Kamau")          // killed before the 300 ms pause ran the query
        a.host.foreground.value = false
        let b = await processDeath(a)
        XCTAssertEqual(b.vm.list.value.search, "Kamau")
        XCTAssertEqual(b.vm.inbox.value.filters.q, "Kamau")
        XCTAssertTrue(fake.calls.contains { $0.method == "GET" && $0.path == "/admin/conversations" && ($0.query ?? "").contains("q=Kamau") })
    }

    func testRestoreWithNothingSavedIsAFreshInboxNoCrash() async {
        let a = await start()
        let b = await processDeath(a)
        XCTAssertEqual(b.vm.thread.value.activeId, "")
        XCTAssertEqual(b.vm.inbox.value.filters.tab, "all")
        XCTAssertFalse(b.vm.rows.isEmpty)
    }

    /// A thread no longer on page one (or gone from the snapshot) is fetched by id and reopened.
    func testProcessDeathOpenThreadNotOnPageOneIsFetchedAndReopened() async {
        let a = await start()
        a.vm.select("c4"); await drain(); a.vm.setReplyText("Albs in M — ")
        a.host.foreground.value = false
        let fake = self.fake!
        let b = await processDeath(a) {
            fake.on("GET", "/admin/conversations", body: "{\"items\":[\(InboxFixtures.conversations.filter { !$0.contains("\"id\":\"c4\"") }.joined(separator: ","))],\"next_cursor\":null}")
        }
        XCTAssertEqual(b.vm.thread.value.activeId, "c4")
        XCTAssertEqual(b.vm.composer.value.replyText, "Albs in M — ")
        XCTAssertTrue(fake.called("GET", "/admin/conversations/c4"))
    }

    // ═══════════════ A send in flight when the app dies ═══════════════

    /// No answer came before the kill; the server had it: the bubble settles — never a second POST.
    func testProcessDeathMidSendTheServerHadItSettlesNeverSentTwice() async {
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ in try InboxNetFixtures.timeout() }
        let a = await start()
        a.vm.select("c1"); await drain()
        a.vm.setReplyText("On its way"); a.vm.sendReply(); await drain()
        await idle(InboxViewModel.MEMORY_DEBOUNCE_MS + 50)
        XCTAssertEqual(memory()?.outbox.count, 1)
        let server = self.server!
        let b = await processDeath(a) { server.add(InboxNetFixtures.row("srv-1", "On its way")) }
        await drain()
        XCTAssertTrue(mine(b.vm).isEmpty)
        XCTAssertEqual(b.vm.thread.value.messages["c1"]!.filter { $0.body == "On its way" }.count, 1)
        XCTAssertEqual(replies(), 1)
    }

    /// The server never got it: after the checks it turns "Not sent" with Retry — nothing is lost, nothing duplicated.
    func testProcessDeathMidSendTheServerNeverGotItTurnsNotSentRetrySendsOnce() async {
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ in try InboxNetFixtures.timeout() }
        let a = await start()
        a.vm.select("c1"); await drain()
        a.vm.setReplyText("Lost in the air"); a.vm.sendReply(); await drain()
        await idle(InboxViewModel.MEMORY_DEBOUNCE_MS + 50)
        let b = await processDeath(a)
        let first = mine(b.vm)
        XCTAssertEqual(first.count, 1); XCTAssertEqual(first.first?.body, "Lost in the air"); XCTAssertEqual(first.first?.sendState, "sending")
        await idle(10_000)
        let failed = mine(b.vm).first!
        XCTAssertEqual(failed.sendState, "failed")
        XCTAssertEqual(replies(), 1)
        let server = self.server!
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ in server.add(InboxNetFixtures.row("srv-2", "Lost in the air")); return (200, #"{"ok":true}"#) }
        b.vm.retrySend(failed.id); await drain()
        XCTAssertEqual(replies(), 2)
        // Both attempts carry the same client_msg_id — even across the kill — so
        // had the first actually landed, the server would answer the second with
        // it instead of messaging the customer again.
        let ids = fake.calls.filter { $0.method == "POST" && $0.path == "/admin/conversations/c1/reply" }.map { json($0.body!)["client_msg_id"]?.content ?? "null" }
        XCTAssertEqual(Set(ids).count, 1)
        XCTAssertNotEqual(ids.first, "null")
        XCTAssertTrue(mine(b.vm).isEmpty)
        XCTAssertEqual(b.vm.thread.value.messages["c1"]!.filter { $0.body == "Lost in the air" }.count, 1)
    }

    /// A "Not sent" bubble (with its Edit / Retry) survives the kill; Edit puts the words back in the box.
    func testProcessDeathNotSentBubbleSurvivesAndEditRestoresTheWords() async {
        let a = await start()
        a.vm.select("c1"); await drain()
        // The agent is already typing the next thought when the refusal lands: it can't go back in the box.
        let vmRef = Ref<InboxViewModel?>(a.vm)
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ in
            onMainSync { vmRef.value?.setReplyText("Next thought") }
            return (422, #"{"detail":"Outside the messaging window"}"#)
        }
        a.vm.setReplyText("Third"); a.vm.sendReply(); await drain()
        XCTAssertEqual(mine(a.vm).first?.sendState, "failed")
        await idle(InboxViewModel.MEMORY_DEBOUNCE_MS + 50)
        let b = await processDeath(a)
        let bubble = mine(b.vm).first!
        XCTAssertEqual(bubble.sendState, "failed")
        XCTAssertEqual(bubble.body, "Third")
        XCTAssertEqual(b.vm.composer.value.replyText, "Next thought")
        b.vm.editFailed(bubble.id)
        XCTAssertTrue(mine(b.vm).isEmpty)
        XCTAssertTrue(b.vm.composer.value.replyText.contains("Third"))
    }

    // ═══════════════ 401 in the middle of a send ═══════════════

    func testNote401WaitsForSignInThenSavesOnce() async {
        let n = Ref(0)
        let server = self.server!
        fake.on("POST", "/admin/conversations/c1/note") { _, _ in
            defer { n.mutate { $0 += 1 } }
            if n.value == 0 { return (401, #"{"detail":"Token expired"}"#) }
            let row = InboxNetFixtures.row("srv-n", "Internal: VIP", note: true)
            server.add(row)
            return (200, row)
        }
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let a = await start()
        a.vm.select("c1"); await drain()
        a.vm.showNote(true); a.vm.setNoteText("Internal: VIP"); a.vm.saveNote(); await drain()
        XCTAssertTrue(a.host.sessionExpired.value)
        XCTAssertEqual(mine(a.vm).first?.sendError, InboxViewModel.AUTH_HELD)
        fake.on("POST", "/(agent-auth|auth)/refresh", body: Fixtures.tokenResponse())
        a.host.onReauthenticated(); await drain()
        XCTAssertEqual(n.value, 2)
        XCTAssertTrue(mine(a.vm).isEmpty)
        XCTAssertTrue(a.host.toasts.contains { $0.message == "Note saved" }, "\(a.host.toasts)")
    }

    /// Files an expired session refused stay in the tray with their captions and go on sign-in — even if the agent moved on.
    func testMedia401StaysInTheTrayAndUploadsOnceAfterSignIn() async {
        let n = Ref(0)
        let server = self.server!
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ in
            defer { n.mutate { $0 += 1 } }
            if n.value == 0 { return (401, #"{"detail":"Token expired"}"#) }
            let row = InboxNetFixtures.row("srv-v", "Fitting video", mediaType: "video")
            server.add(row)
            return (200, row)
        }
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let a = await start()
        a.vm.select("c1"); await drain()
        a.vm.pickMedia([PickedMedia(id: "v1", file: nil, name: "clip.mp4", mime: "video/mp4", size: 1_000, bytes: Data([1, 2, 3]), caption: "Fitting video")])
        a.vm.sendMedia(); await drain()
        XCTAssertTrue(a.host.sessionExpired.value)
        let left = a.vm.composer.value.media.first!
        XCTAssertEqual(left.caption, "Fitting video"); XCTAssertTrue(left.error!.contains("sign in again"))
        a.vm.select("c2"); await drain()               // moved on while the dialog was up
        fake.on("POST", "/(agent-auth|auth)/refresh", body: Fixtures.tokenResponse())
        a.host.onReauthenticated(); await drain()
        XCTAssertEqual(n.value, 2)
        a.vm.select("c1"); await drain()
        XCTAssertTrue(a.vm.composer.value.media.isEmpty)
    }

    /// Held for sign-in when the app dies: it comes back as "Not sent" with Retry — never sent on its own hours later.
    func testProcessDeathWithAHeldSendOffersRetryDoesNotSendByItself() async {
        fake.on("POST", "/admin/conversations/c1/reply", code: 401, body: #"{"detail":"Token expired"}"#)
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let a = await start()
        a.vm.select("c1"); await drain(); a.vm.setReplyText("Held"); a.vm.sendReply(); await drain()
        a.host.foreground.value = false
        let fake = self.fake!, server = self.server!
        let b = await processDeath(a) {
            fake.on("POST", "/(agent-auth|auth)/refresh", body: Fixtures.tokenResponse())
            fake.on("POST", "/admin/conversations/c1/reply") { _, _ in server.add(InboxNetFixtures.row("srv-h", "Held")); return (200, #"{"ok":true}"#) }
        }
        let bubble = mine(b.vm).first!
        XCTAssertEqual(bubble.sendState, "failed")
        XCTAssertTrue(bubble.sendError!.contains("Tap Retry"))
        await idle(30_000)
        XCTAssertEqual(replies(), 1)
        b.vm.retrySend(bubble.id); await drain()
        XCTAssertEqual(replies(), 2)
        XCTAssertTrue(mine(b.vm).isEmpty)
    }

    // ═══════════════ Deep links in every state ═══════════════

    /// A notification tap switches threads under an open note: the note waits with its own thread; a transfer never retargets.
    func testDeepLinkWhileANoteIsOpenTheNoteWaitsWithItsThread() async {
        let a = await start()
        a.vm.select("c1"); await drain()
        a.vm.showNote(true); a.vm.setNoteText("Half a note about Fr. Peter")
        a.host.openConversationFor("254722000111"); await drain()   // Rev. Mary (c2)
        XCTAssertEqual(a.vm.thread.value.activeId, "c2")
        XCTAssertFalse(a.vm.dialogs.value.note); XCTAssertEqual(a.vm.dialogs.value.noteText, "")
        a.vm.select("c1"); await drain()
        XCTAssertTrue(a.vm.dialogs.value.note); XCTAssertEqual(a.vm.dialogs.value.noteText, "Half a note about Fr. Peter")
    }

    func testDeepLinkWhileTransferOrClearIsOpenClosesThem() async {
        let a = await start()
        a.vm.select("c1"); await drain()
        a.vm.showTransfer(true)
        a.host.openConversationFor("254722000111"); await drain()
        XCTAssertFalse(a.vm.dialogs.value.transfer)
        a.vm.showClear(true)
        a.host.openConversationFor("254712345678"); await drain()
        XCTAssertEqual(a.vm.thread.value.activeId, "c1")
        XCTAssertFalse(a.vm.dialogs.value.clearConfirm)
    }

    /// Cold start from a notification: the link wins over the thread the app was killed on; drafts still come back.
    func testColdStartDeepLinkBeatsTheRestoredThread() async {
        let a = await start()
        a.vm.select("c1"); await drain(); a.vm.setReplyText("Keep me")
        a.host.foreground.value = false
        let saved: InboxMemory = snapshots.read(Fixtures.ME_ID, Inbox.MEMORY_KEY)!
        a.vm.close()
        snapshots.write(Fixtures.ME_ID, Inbox.MEMORY_KEY, saved)
        let host = TestHost(fake: fake, clock: clock, snapshots: snapshots)
        host.openConvKey.value = "254722000111"
        let b = await start(host)
        XCTAssertEqual(b.vm.thread.value.activeId, "c2")
        b.vm.select("c1"); await drain()
        XCTAssertEqual(b.vm.composer.value.replyText, "Keep me")
    }

    // ═══════════════ Sign-out on a shared phone ═══════════════

    func testSignOutWipesTheAgentsWorkTheNextSignInSeesNothing() async {
        let a = await start()
        a.vm.select("c1"); await drain(); a.vm.setReplyText("Private words")
        a.host.foreground.value = false
        XCTAssertEqual(memory()?.composers["p:p1"]?.replyText, "Private words")
        let session = a.host.session.value!
        a.host.logout()
        a.vm.close()    // the agent store is dropped on sign-out
        XCTAssertTrue(memory()!.isEmpty)
        a.host.sessionStore.save(session)
        let b = await start(TestHost(fake: fake, clock: clock, snapshots: snapshots))
        XCTAssertEqual(b.vm.thread.value.activeId, "")
        b.vm.select("c1"); await drain()
        XCTAssertEqual(b.vm.composer.value.replyText, "")
    }

    // ═══════════════ Files picked but not sent ═══════════════

    /// The system took back the read grant: the file can't come back — it is named, never silently dropped.
    func testProcessDeathPickedFileNoLongerReadableIsNamedForReattaching() async {
        let a = await start()
        a.vm.select("c2"); await drain()
        a.vm.setReplyText("See attached")
        a.host.foreground.value = false
        var m = memory()!
        var c = m.composers["c2"] ?? SavedComposer()
        c.media = [SavedMedia(uri: "file:///private/var/mobile/Containers/Data/gone/cassock.jpg", name: "cassock.jpg", mime: "image/jpeg", size: 120_000, caption: "The purple one")]
        m.composers["c2"] = c
        snapshots.write(Fixtures.ME_ID, Inbox.MEMORY_KEY, m)
        let b = await processDeath(a)
        await drain()
        XCTAssertEqual(b.vm.thread.value.activeId, "c2")
        XCTAssertEqual(b.vm.composer.value.replyText, "See attached")
        XCTAssertTrue(b.vm.composer.value.media.isEmpty)
        XCTAssertEqual(b.vm.composer.value.lostMedia, ["cassock.jpg"])
        b.vm.dismissLostMedia()
        XCTAssertTrue(b.vm.composer.value.lostMedia.isEmpty)
    }

    // ═══════════════ Back, and saveable UI state ═══════════════

    func testBackClosesTheTopmostThingFirst() {
        XCTAssertEqual(inboxBackStep(phoneThread: true, selectMode: true, searching: true, filtersOpen: true), .closeThread)
        XCTAssertEqual(inboxBackStep(phoneThread: false, selectMode: true, searching: true, filtersOpen: true), .exitSelect)
        XCTAssertEqual(inboxBackStep(phoneThread: false, selectMode: false, searching: true, filtersOpen: true), .clearSearch)
        XCTAssertEqual(inboxBackStep(phoneThread: false, selectMode: false, searching: false, filtersOpen: true), .closeFilters)
        XCTAssertNil(inboxBackStep(phoneThread: false, selectMode: false, searching: false, filtersOpen: false))
    }

    /// Back from the thread keeps the draft (the web has no prompt here; the text is simply kept).
    func testBackFromTheThreadKeepsTheDraft() async {
        let a = await start()
        a.vm.select("c1"); await drain(); a.vm.setReplyText("Not finished")
        a.vm.closeThread()
        XCTAssertFalse(a.vm.thread.value.threadOpen)
        a.vm.select("c1"); await drain()
        XCTAssertEqual(a.vm.composer.value.replyText, "Not finished")
    }

    /// The media viewer survives a scene snapshot: every kind round-trips through its saved form.
    func testViewerRoundTripsEveryKind() throws {
        func rt(_ v: Viewer?) throws -> Viewer? { try v.map { try NeemaJSON.decode(Viewer.self, from: try NeemaJSON.encode($0)) } }
        XCTAssertEqual(try rt(.image(url: "https://neema.test/a.jpg")), .image(url: "https://neema.test/a.jpg"))
        XCTAssertEqual(try rt(.video(url: "https://neema.test/v.mp4", messageId: "m1")), .video(url: "https://neema.test/v.mp4", messageId: "m1"))
        XCTAssertEqual(try rt(.video(url: "https://neema.test/v.mp4", messageId: nil)), .video(url: "https://neema.test/v.mp4", messageId: nil))
        let album = Viewer.album(items: [AlbumItem(src: "a", caption: "one"), AlbumItem(src: "b", caption: nil), AlbumItem(src: "c", caption: "three")], start: 1)
        XCTAssertEqual(try rt(album), album)
        XCTAssertNil(try rt(nil))
    }
}
