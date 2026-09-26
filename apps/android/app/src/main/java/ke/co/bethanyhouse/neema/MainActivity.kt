package ke.co.bethanyhouse.neema

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.runtime.DisposableEffect
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.windowsizeclass.ExperimentalMaterial3WindowSizeClassApi
import androidx.compose.material3.windowsizeclass.calculateWindowSizeClass
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ke.co.bethanyhouse.neema.app.DashboardShell
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.LoginScreen
import ke.co.bethanyhouse.neema.app.SessionExpiredDialog
import ke.co.bethanyhouse.neema.app.DeepLink
import ke.co.bethanyhouse.neema.core.notify.Notifier
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaTheme

class MainActivity : ComponentActivity() {
    private val dash: DashboardViewModel by viewModels()

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    @OptIn(ExperimentalMaterial3WindowSizeClassApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // A recreated activity (process restore) must not replay the launch
        // intent, nor must a relaunch from Recents (which re-delivers it).
        val fromHistory = intent.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY != 0
        if (savedInstanceState == null && !fromHistory) handleIntent(intent)

        setContent {
            val dark by dash.dark.collectAsStateWithLifecycle()
            val session by dash.session.collectAsStateWithLifecycle()
            val expired by dash.sessionExpired.collectAsStateWithLifecycle()
            val size = calculateWindowSizeClass(this)
            // System bar icons follow what is drawn under them, not the phone's
            // own theme: light over the night login, the navy frame of a
            // tablet's docked sidebar, and the app's dark mode; dark over the
            // white phone header / bottom bar by day.
            val wide = size.widthSizeClass != WindowWidthSizeClass.Compact
            val lightStatusIcons = session == null || dark || wide
            val lightNavIcons = session == null || dark
            DisposableEffect(lightStatusIcons, lightNavIcons) {
                enableEdgeToEdge(
                    statusBarStyle = barStyle(lightStatusIcons),
                    navigationBarStyle = barStyle(lightNavIcons),
                )
                onDispose {}
            }
            // Ask for notifications once, after the first sign-in (a login
            // screen asking out of nowhere reads as spam). Denied is final:
            // alerts still reach the bell and the toast in the app, and
            // Profile links to the system settings — no nagging.
            LaunchedEffect(session != null) { if (session != null) maybeAskForNotifications() }
            NeemaTheme(dark = dark) {
                Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                    val s = session
                    if (s == null) {
                        LoginScreen(onSignedIn = {})
                    } else {
                        // Screen ViewModels live in a store owned by this signed-in agent:
                        // signing out (or in as someone else) discards it, so one agent's
                        // conversations, orders or drafts can never show for the next.
                        // Keyed by the agent too: saved UI state (a view's filters and
                        // drafts, open overlays) is never restored into someone else's shell.
                        androidx.compose.runtime.key(s.agentId) {
                            SignedInScope(dash, s.agentId) { DashboardShell(dash, size.widthSizeClass) }
                        }
                        if (expired) SessionExpiredDialog(
                            email = s.email,
                            onSuccess = { dash.onReauthenticated() },
                            onSignOut = { dash.logout() },
                        )
                    }
                }
            }
        }
    }

    /** Transparent bars (every screen draws its own colour under them) with light or dark icons. */
    private fun barStyle(lightIcons: Boolean): SystemBarStyle =
        if (lightIcons) SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
        else SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)

    private fun maybeAskForNotifications() {
        if (Build.VERSION.SDK_INT < 33 || Notifier.canPost(this)) return
        val prefs = dash.container.prefs.raw
        if (prefs.getBoolean(ASKED_NOTIFICATIONS, false)) return
        prefs.edit().putBoolean(ASKED_NOTIFICATIONS, true).apply()
        askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    /**
     * Deep links and notification taps. Mirrors the web's query parameters:
     * `?open=<wa_id>[&ref=<order>]` opens a chat, `?view=calls&caller=<wa_id>`
     * focuses the call console, `?view=<name>` switches view.
     */
    private fun handleIntent(intent: Intent?) {
        intent ?: return
        // A tap on an alert (Notifier.post): its conversation or view.
        val conv = intent.getStringExtra(Notifier.EXTRA_OPEN_CONV)
        val view = intent.getStringExtra(Notifier.EXTRA_VIEW)
        val notification = intent.getStringExtra(Notifier.EXTRA_NOTIFICATION)
        if (conv != null || view != null || notification != null) dash.openFromNotification(conv, view, notification)
        if (intent.getStringExtra(Notifier.EXTRA_CALL_ACTION) != null) {
            NeemaApplication.instance.container.calls.handleIntent(intent)
        }
        // Consumed once, like the web stripping the query string: a config
        // change must not replay it.
        listOf(
            Notifier.EXTRA_OPEN_CONV, Notifier.EXTRA_VIEW, Notifier.EXTRA_NOTIFICATION,
            Notifier.EXTRA_CALL_ACTION, Notifier.EXTRA_CALL_ID,
        ).forEach(intent::removeExtra)
        val uri: Uri = intent.data ?: return
        // Signed out, the dashboard keeps it and replays it after sign-in.
        dash.applyDeepLink(DeepLink.of { runCatching { uri.getQueryParameter(it) }.getOrNull() })
        intent.data = null
    }

    private companion object {
        const val ASKED_NOTIFICATIONS = "asked_post_notifications"
    }
}

/**
 * A ViewModel store scoped to one signed-in agent, held by the dashboard's
 * ViewModel (so it survives the activity being recreated) and cleared when
 * the agent signs out or another signs in.
 */
@androidx.compose.runtime.Composable
private fun SignedInScope(dash: DashboardViewModel, agentId: String, content: @androidx.compose.runtime.Composable () -> Unit) {
    val owner = androidx.compose.runtime.remember(dash, agentId) {
        val store = dash.viewModelStoreFor(agentId)
        object : androidx.lifecycle.ViewModelStoreOwner {
            override val viewModelStore = store
        }
    }
    androidx.compose.runtime.CompositionLocalProvider(
        androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner provides owner,
        content = content,
    )
}
