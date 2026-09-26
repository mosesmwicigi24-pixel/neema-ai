package ke.co.bethanyhouse.neema.testing

import ke.co.bethanyhouse.neema.core.util.AppClock

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
private val jtiSeq = java.util.concurrent.atomic.AtomicLong()

fun fakeJwt(sub: String = Fixtures.ME_ID, expiresInSec: Long = 365L * 24 * 3600): String {
    fun b64(s: String) = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(s.toByteArray())
    val exp = AppClock.now() / 1000 + expiresInSec
    // A unique jti: two tokens minted in the same second must still differ, or
    // the auth layer reads a refresh that "returned the same token" as failed.
    val jti = jtiSeq.incrementAndGet()
    return "${b64("""{"alg":"HS256","typ":"JWT"}""")}.${b64("""{"sub":"$sub","exp":$exp,"type":"access","jti":"t$jti"}""")}.sig"
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
    /** Sign in as this persona (overrides [role]/[superuser] and serves its rows on [fake]). */
    persona: Persona? = null,
): AppContainer {
    if (persona != null) {
        Personas.install(fake, persona)
        return testContainer(context, fake, persona.role, persona.superuser, appDispatcher, wsFactory)
    }
    installTestImageLoader(context)
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

/**
 * Screenshot tests have no network: every image request fails at once, on the
 * calling thread, so each render shows the same fallback (initials, emoji,
 * placeholder) every run — Coil's async loads otherwise race the snapshot.
 */
fun installTestImageLoader(context: Context) {
    coil.Coil.setImageLoader(
        coil.ImageLoader.Builder(context)
            .dispatcher(Dispatchers.Unconfined)
            .interceptorDispatcher(Dispatchers.Unconfined)
            .fetcherDispatcher(Dispatchers.Unconfined)
            .decoderDispatcher(Dispatchers.Unconfined)
            .transformationDispatcher(Dispatchers.Unconfined)
            .networkObserverEnabled(false)
            .components {
                add(object : coil.intercept.Interceptor {
                    override suspend fun intercept(chain: coil.intercept.Interceptor.Chain): coil.request.ImageResult =
                        coil.request.ErrorResult(null, chain.request, java.io.IOException("no network in tests"))
                })
            }
            .build(),
    )
}

/** Theme + a ViewModel store, as MainActivity provides. */
@Composable
fun AppFrame(dark: Boolean = false, content: @Composable () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    androidx.compose.runtime.remember { installTestImageLoader(context); true }
    CompositionLocalProvider(
        LocalViewModelStoreOwner provides TestOwner(),
        androidx.activity.compose.LocalActivityResultRegistryOwner provides TestResults(),
    ) {
        NeemaTheme(dark = dark) {
            // The shell's Scaffold sets the content colour; do the same so text renders as on device.
            CompositionLocalProvider(androidx.compose.material3.LocalContentColor provides MaterialTheme.colorScheme.onBackground) {
                Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) { content() }
            }
        }
    }
}

/**
 * A signed-in [DashboardViewModel] on [fake]. Pass [persona] to sign in as one
 * of round 6's permission personas (see [Persona]): e.g.
 * `dashboard(ctx, fake, persona = Persona.Sales)`.
 */
fun dashboard(
    context: Context, fake: FakeNeema = FakeNeema.withFixtures(), role: String = "admin", superuser: Boolean = true,
    appDispatcher: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.Default, wsFactory: okhttp3.WebSocket.Factory? = null,
    persona: Persona? = null,
) =
    DashboardViewModel(testContainer(context, fake, role, superuser, appDispatcher, wsFactory, persona))
