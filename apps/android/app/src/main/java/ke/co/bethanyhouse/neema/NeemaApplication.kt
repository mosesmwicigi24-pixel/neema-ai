package ke.co.bethanyhouse.neema

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import ke.co.bethanyhouse.neema.app.AppContainer
import ke.co.bethanyhouse.neema.core.notify.LiveService
import ke.co.bethanyhouse.neema.core.notify.Notifier
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

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
        container.appScope.launch {
            combine(container.sessionStore.session, container.prefs.backgroundLive, foreground) { s, bg, fg ->
                Triple(s?.agentId, bg, fg)
            }.distinctUntilChanged().collect { (agentId, bg, fg) ->
                if (agentId.isNullOrEmpty()) {
                    container.socket.disconnect()
                    LiveService.stop(this@NeemaApplication)
                    return@collect
                }
                container.socket.connect(agentId)
                if (bg) LiveService.start(this@NeemaApplication)
                else {
                    LiveService.stop(this@NeemaApplication)
                    if (!fg) container.socket.disconnect()
                }
            }
        }
        container.notifications.start(foreground)
        container.calls.start()
    }

    companion object {
        lateinit var instance: NeemaApplication
            private set
    }
}
