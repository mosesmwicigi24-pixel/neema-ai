package ke.co.bethanyhouse.neema.testing

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import ke.co.bethanyhouse.neema.app.AppContainer
import ke.co.bethanyhouse.neema.app.ContainerConfig
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.auth.Session
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaTheme
import kotlinx.coroutines.Dispatchers

/** A JWT the auth layer accepts as valid for a year (signature is never checked client-side). */
fun fakeJwt(sub: String = Fixtures.ME_ID, expiresInSec: Long = 365L * 24 * 3600): String {
    fun b64(s: String) = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(s.toByteArray())
    val exp = System.currentTimeMillis() / 1000 + expiresInSec
    return "${b64("""{"alg":"HS256","typ":"JWT"}""")}.${b64("""{"sub":"$sub","exp":$exp,"type":"access"}""")}.sig"
}

/**
 * A signed-in app wired to [fake]: synchronous I/O so every screen has its
 * data by the first frame, the app "in the foreground", an admin session.
 */
fun testContainer(
    context: Context,
    fake: FakeNeema = FakeNeema.withFixtures(),
    role: String = "admin",
    superuser: Boolean = true,
    /** Where the socket / notification centre run; Unconfined makes them synchronous. */
    appDispatcher: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.Default,
    /** A fake socket (see [FakeSocketFactory]) so tests can push live frames. */
    wsFactory: okhttp3.WebSocket.Factory? = null,
): AppContainer {
    val stores = HashMap<String, MemoryPrefs>()
    val c = AppContainer(
        context,
        ContainerConfig(
            baseUrl = "https://neema.test", interceptor = fake, io = Dispatchers.Unconfined,
            prefs = { name -> stores.getOrPut(name) { MemoryPrefs() } },
            authBackoffMs = 0, appDispatcher = appDispatcher, wsFactory = wsFactory,
        ),
    )
    // Each test starts cold: no stale-while-revalidate snapshot from an earlier test.
    c.snapshots.clear()
    c.sessionStore.save(
        Session(
            accessToken = fakeJwt(), refreshToken = "refresh", agentId = Fixtures.ME_ID,
            email = "moses@bethanyhouse.co.ke", name = "Moses Mwicigi", role = role,
            isSuperuser = superuser, mode = "direct",
        ),
    )
    c.foreground.value = true
    return c
}

private class TestOwner : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }

/** Launchers (permissions, pickers) register fine and simply never deliver a result. */
private class TestResults : androidx.activity.result.ActivityResultRegistryOwner {
    override val activityResultRegistry = object : androidx.activity.result.ActivityResultRegistry() {
        override fun <I, O> onLaunch(
            requestCode: Int,
            contract: androidx.activity.result.contract.ActivityResultContract<I, O>,
            input: I,
            options: androidx.core.app.ActivityOptionsCompat?,
        ) = Unit
    }
}

/** Theme + a ViewModel store, as MainActivity provides. */
@Composable
fun AppFrame(dark: Boolean = false, content: @Composable () -> Unit) {
    CompositionLocalProvider(
        LocalViewModelStoreOwner provides TestOwner(),
        androidx.activity.compose.LocalActivityResultRegistryOwner provides TestResults(),
    ) {
        NeemaTheme(dark = dark) {
            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) { content() }
        }
    }
}

fun dashboard(
    context: Context, fake: FakeNeema = FakeNeema.withFixtures(), role: String = "admin", superuser: Boolean = true,
    appDispatcher: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.Default, wsFactory: okhttp3.WebSocket.Factory? = null,
) =
    DashboardViewModel(testContainer(context, fake, role, superuser, appDispatcher, wsFactory))
