package ke.co.bethanyhouse.neema.app

import android.content.Context
import ke.co.bethanyhouse.neema.BuildConfig
import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.auth.AuthRepository
import ke.co.bethanyhouse.neema.core.auth.SessionStore
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.notify.NotificationCenter
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.util.SnapshotCache
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/**
 * Knobs for tests: a fake backend (an OkHttp interceptor that answers without
 * the network), and a synchronous dispatcher so screens settle in one frame.
 */
data class ContainerConfig(
    val baseUrl: String = BuildConfig.NEEMA_BASE_URL,
    val interceptor: okhttp3.Interceptor? = null,
    val io: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.IO,
    /** Tests only: in-memory preferences by file name (layoutlib has no real ones). */
    val prefs: ((String) -> android.content.SharedPreferences)? = null,
)

/** Hand-rolled DI: one of each, created with the Application. */
class AppContainer(val context: Context, val config: ContainerConfig = ContainerConfig()) {
    /** Lives as long as the process; for work that must outlive a screen. */
    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val prefs = AppPrefs(context, config.prefs?.invoke("neema_prefs"))
    val sessionStore = SessionStore(context, config.prefs?.invoke("neema_session"))
    val auth = AuthRepository(sessionStore)
    val http = NeemaHttp(config.baseUrl, auth, config.interceptor, config.io)
    val api = NeemaApi(http)
    val socket = LiveSocket(http.wsClient, config.baseUrl, appScope)

    /** True while any activity of the app is visible (set by NeemaApplication). */
    val foreground = kotlinx.coroutines.flow.MutableStateFlow(false)
    val snapshots = SnapshotCache(context)
    val notifications = NotificationCenter(context, appScope, socket, prefs, config.prefs?.invoke("neema_notifications"))
    val calls = CallManager(
        context, api, socket, appScope,
        foreground = foreground,
        signedInFn = { sessionStore.session.value != null },
        prefs = prefs,
    )
}
