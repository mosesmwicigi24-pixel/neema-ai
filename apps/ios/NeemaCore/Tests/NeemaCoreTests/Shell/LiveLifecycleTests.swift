import XCTest
@testable import NeemaCore

/// Android `app/LiveLifecycleTest`: the socket across sign-in, sign-out, the
/// app going to the background, and the process being killed and restarted.
/// iOS has no foreground service and no "live mode": the socket is up while
/// signed in AND in front (`AppContainer.applyLivePolicy`, mirrored here
/// verbatim over NeemaCore's `SessionStore` and `LiveSocket`); the service
/// and boot-receiver tests are Android-only.
final class LiveLifecycleTests: XCTestCase {
    private var factory: FakeSocketFactory!
    private var clock: VirtualClock!
    /// The persisted session (the Keychain), shared by every "process".
    private var sessionStore: MemoryStore!
    private var fg: Watched<Bool>!
    private var processes: [Process] = []

    override func setUp() {
        factory = FakeSocketFactory()
        clock = VirtualClock()
        sessionStore = MemoryStore()
        fg = Watched<Bool>(true)
    }

    override func tearDown() {
        for p in processes { p.close() }
        processes = []
    }

    private func session(_ agent: String = "a1") -> Session {
        Session(accessToken: "tok", refreshToken: "ref", agentId: agent, email: "m@b.co.ke", name: "Moses", role: "admin", isSuperuser: true, mode: "direct")
    }

    /// A "process": a session store over the persisted store, a socket, the live policy.
    private final class Process {
        let store: SessionStore
        let socket: LiveSocket
        private let foreground: Watched<Bool>
        private var subs: [Subscription] = []

        init(persisted: MemoryStore, factory: FakeSocketFactory, foreground: Watched<Bool>, sleep: @escaping Sleeper) {
            store = SessionStore(store: persisted)
            socket = LiveSocket(factory: factory, baseUrl: "https://neema.test", token: { nil }, sleep: sleep)
            self.foreground = foreground
            subs.append(store.session.observe { [weak self] _ in self?.applyLivePolicy() })
            subs.append(foreground.observe { [weak self] _ in self?.applyLivePolicy() })
        }

        /// `AppContainer.applyLivePolicy`: connected while signed in and in front.
        func applyLivePolicy() {
            guard let s = store.current else {
                socket.signOut()
                return
            }
            if foreground.value { socket.connect(s.agentId) } else { socket.disconnect() }
        }

        func close() {
            subs.forEach { $0.cancel() }
            subs = []
            socket.signOut()
        }
    }

    private func process(factory f: FakeSocketFactory? = nil) -> Process {
        let p = Process(persisted: sessionStore, factory: f ?? factory, foreground: fg, sleep: clock.sleeper)
        processes.append(p)
        return p
    }

    func testSignedOutThereIsNoSocket() {
        let p = process()
        XCTAssertEqual(0, factory.count)
        XCTAssertFalse(p.socket.connected.value)
    }

    func testSigningInConnectsAsThatAgent() {
        let p = process()
        p.store.save(session("a1"))
        XCTAssertTrue(factory.last.urlText.hasSuffix("/ws/a1"), factory.last.urlText)
    }

    func testSigningOutClosesForGoodEvenIfTheSocketDropsAfterwards() async {
        let p = process()
        p.store.save(session()); factory.last.open()
        p.store.clear()
        XCTAssertEqual(1000, factory.last.closedWith)
        factory.last.fail() // a late failure callback from the closed socket
        p.socket.nudge()    // the app comes to the front / the network returns
        await clock.advance(by: 120_000)
        XCTAssertEqual(1, factory.count, "nothing reconnects after sign-out")
    }

    func testInTheBackgroundTheSocketClosesAndReopensOnReturn() async {
        // Android without live mode: closed in the background, alerts still arrive while open.
        let p = process()
        p.store.save(session()); factory.last.open()
        XCTAssertTrue(p.socket.connected.value, "connected while the app is open")

        fg.value = false
        XCTAssertFalse(p.socket.connected.value, "closed in the background")
        XCTAssertEqual(1000, factory.last.closedWith)
        await clock.advance(by: 60_000)
        XCTAssertEqual(1, factory.count)

        fg.value = true
        XCTAssertEqual(2, factory.count, "reopened on return")
        XCTAssertTrue(factory.last.urlText.hasSuffix("/ws/a1"))
    }

    func testARestartedProcessReconnectsFromTheStoredSession() {
        let p = process()
        p.store.save(session("a7"))
        p.close()
        // iOS kills the process; the agent opens the app again.
        let restarted = FakeSocketFactory()
        fg.value = false
        let again = process(factory: restarted)
        XCTAssertEqual(0, restarted.count, "nothing in the background: iOS suspends sockets there")
        fg.value = true
        XCTAssertEqual(1, restarted.count)
        XCTAssertTrue(restarted.last.urlText.hasSuffix("/ws/a7"), "the stored session says who")
        XCTAssertEqual("a7", again.store.current?.agentId)
    }

    func testARestartedProcessAfterSignOutStaysDisconnected() {
        let p = process()
        p.store.save(session()); p.store.clear()
        p.close()
        let restarted = FakeSocketFactory()
        let again = process(factory: restarted)
        XCTAssertEqual(0, restarted.count)
        XCTAssertNil(again.store.current)
        XCTAssertFalse(again.socket.connected.value)
    }

    func testSwitchingAgentsReconnectsAsTheNewOne() {
        let p = process()
        p.store.save(session("a1")); factory.last.open()
        p.store.save(session("a2"))
        XCTAssertTrue(factory.last.urlText.hasSuffix("/ws/a2"), factory.last.urlText)
        XCTAssertEqual(1000, factory[0].closedWith)
    }
}
