package ke.co.bethanyhouse.neema

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import ke.co.bethanyhouse.neema.app.AppContainer
import ke.co.bethanyhouse.neema.core.notify.LiveService
import ke.co.bethanyhouse.neema.core.notify.Notifier
import android.net.ConnectivityManager
import android.net.Network
import ke.co.bethanyhouse.neema.app.LiveLifecycle
import kotlinx.coroutines.flow.StateFlow

class NeemaApplication : Application() {
    lateinit var container: AppContainer
        private set

    /** True while any activity of the app is visible. */
    val foreground: StateFlow<Boolean> get() = container.foreground

    override fun onCreate() {
        super.onCreate()
        instance = this
        container = AppContainer(this)
        Notifier.createChannels(this)

        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) { container.foreground.value = true; container.socket.nudge() }
            override fun onStop(owner: LifecycleOwner) { container.foreground.value = false }
        })

        // One socket per signed-in agent, for the life of the process; the
        // foreground service only keeps the process alive in the background.
        LiveLifecycle(
            container.appScope, container.sessionStore.session, container.prefs.backgroundLive, foreground,
            container.socket,
            startService = { LiveService.start(this) },
            stopService = { LiveService.stop(this) },
        ).start()
        watchNetwork()
        container.notifications.start(foreground)
        container.calls.start()
    }

    /**
     * The network came back: retry the socket now instead of waiting out a
     * backoff of up to 30 s (a no-op when connected or closed on purpose).
     */
    private fun watchNetwork() {
        runCatching {
            getSystemService(ConnectivityManager::class.java)?.registerDefaultNetworkCallback(
                object : ConnectivityManager.NetworkCallback() {
                    override fun onAvailable(network: Network) = container.socket.nudge()
                },
            )
        }
    }

    companion object {
        lateinit var instance: NeemaApplication
            private set
    }
}
