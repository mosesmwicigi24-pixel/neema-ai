import Foundation
import Network
import NeemaCore

/// One of each service, for the whole process — the twin of Android's
/// `AppContainer`. Screens reach everything through `AppModel`.
final class AppContainer {
    let baseUrl: String
    let sessionStore: SessionStore
    let auth: AuthRepository
    let http: NeemaHTTP
    let api: NeemaApi
    let socket: LiveSocket
    /// True while the app is on screen — polls pause in the background.
    let foreground = Watched<Bool>(false)
    /// The device has a network (the shell's offline banner).
    let online = Watched<Bool>(true)
    let prefs = AppPrefs(store: UserDefaults.standard)
    /// Crash reports that survive the crash (Application Support/crash); the handlers are installed first thing.
    let crashVault: CrashVault

    private let monitor = NWPathMonitor()
    private var subs: [Subscription] = []

    init(baseUrl: String = NeemaConfig.baseUrl, store: SecureStore = KeychainStore(), transport: HTTPTransport = URLSessionTransport(),
         socketFactory: WebSocketFactory = URLSessionWebSocketFactory(), watchNetwork: Bool = true) {
        self.baseUrl = baseUrl
        crashVault = CrashVault(dir: CrashHandlers.vaultDirectory())
        CrashHandlers.install(crashVault)
        // Images (AsyncImage through URLSession.shared) keep a 64 MB memory / 256 MB disk cache,
        // Coil's defaults on Android; the system's default is a tenth of that.
        if URLCache.shared.memoryCapacity < 64 << 20 {
            URLCache.shared = URLCache(memoryCapacity: 64 << 20, diskCapacity: 256 << 20)
        }
        sessionStore = SessionStore(store: store)
        auth = AuthRepository(store: sessionStore, base: baseUrl, transport: transport)
        http = NeemaHTTP(baseUrl: baseUrl, tokens: auth, transport: transport)
        api = NeemaApi(http: http)
        let sessions = sessionStore
        socket = LiveSocket(factory: socketFactory, baseUrl: baseUrl, token: { sessions.current?.accessToken })

        if watchNetwork {
            monitor.pathUpdateHandler = { [weak self] path in
                let up = path.status == .satisfied
                self?.online.update(up)
                if up { self?.socket.nudge() }
            }
            monitor.start(queue: DispatchQueue(label: "ke.co.bethanyhouse.neema.network"))
        }
        // The live-connection policy (Android's LiveLifecycle): connected while
        // signed in and in front. iOS suspends sockets in the background; the
        // Android foreground service has no twin here — pushes will carry
        // alerts there once the backend sends them.
        subs.append(sessionStore.session.observe { [weak self] _ in self?.applyLivePolicy() })
        subs.append(foreground.observe { [weak self] _ in self?.applyLivePolicy() })
    }

    func applyLivePolicy() {
        guard let s = sessionStore.current else {
            socket.signOut()
            return
        }
        if foreground.value { socket.connect(s.agentId) } else { socket.disconnect() }
    }
}
