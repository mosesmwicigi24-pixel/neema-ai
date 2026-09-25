package ke.co.bethanyhouse.neema

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
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
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ke.co.bethanyhouse.neema.app.DashboardShell
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.LoginScreen
import ke.co.bethanyhouse.neema.app.SessionExpiredDialog
import ke.co.bethanyhouse.neema.app.ViewId
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
        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        // A recreated activity (process restore) must not replay the launch intent.
        if (savedInstanceState == null) handleIntent(intent)

        setContent {
            val dark by dash.dark.collectAsStateWithLifecycle()
            val session by dash.session.collectAsStateWithLifecycle()
            val expired by dash.sessionExpired.collectAsStateWithLifecycle()
            val size = calculateWindowSizeClass(this)
            NeemaTheme(dark = dark) {
                Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                    val s = session
                    if (s == null) {
                        LoginScreen(onSignedIn = {})
                    } else {
                        DashboardShell(dash, size.widthSizeClass)
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
        intent.getStringExtra(Notifier.EXTRA_OPEN_CONV)?.let { dash.openConversationFor(it) }
        intent.getStringExtra(Notifier.EXTRA_VIEW)?.let { ViewId.fromWeb(it)?.let(dash::navigate) }
        if (intent.getStringExtra(Notifier.EXTRA_CALL_ACTION) != null) {
            NeemaApplication.instance.container.calls.handleIntent(intent)
        }
        val uri: Uri = intent.data ?: return
        dash.applyDeepLink(
            open = uri.getQueryParameter("open"),
            ref = uri.getQueryParameter("ref"),
            view = uri.getQueryParameter("view"),
            caller = uri.getQueryParameter("caller"),
        )
        // Consumed once, like the web stripping the query string: a config
        // change or relaunch from recents must not replay it.
        intent.data = null
    }
}
