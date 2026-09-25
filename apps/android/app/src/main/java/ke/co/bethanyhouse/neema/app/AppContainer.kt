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

/** Hand-rolled DI: one of each, created with the Application. */
class AppContainer(val context: Context) {
    /** Lives as long as the process; for work that must outlive a screen. */
    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val prefs = AppPrefs(context)
    val sessionStore = SessionStore(context)
    val auth = AuthRepository(sessionStore)
    val http = NeemaHttp(BuildConfig.NEEMA_BASE_URL, auth)
    val api = NeemaApi(http)
    val socket = LiveSocket(http.wsClient, BuildConfig.NEEMA_BASE_URL, appScope)
    val snapshots = SnapshotCache(context)
    val notifications = NotificationCenter(context, appScope, socket)
    val calls = CallManager(context, api, socket, appScope)
}
