package ke.co.bethanyhouse.neema.app

import ke.co.bethanyhouse.neema.core.auth.Session
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/**
 * Who keeps the live socket (and the background service) up — the web's
 * WsProvider, which connects while a session exists and closes on sign-out.
 *
 * - signed out → the socket is closed and forgotten, the service stops; a
 *   sticky service restart or a late callback can't reopen it.
 * - signed in, app on screen → connected.
 * - signed in, "Stay connected in background" on → connected, and
 *   LiveService keeps the process alive in the background.
 * - signed in, live mode off, app in the background → closed; coming back
 *   reopens it, and the socket's `reconnected` signal makes screens catch up.
 *
 * Driven by the stored session, so a process that Android restarted
 * (START_STICKY, boot, update) reconnects without the app being opened.
 */
class LiveLifecycle(
    private val scope: CoroutineScope,
    private val session: StateFlow<Session?>,
    private val backgroundLive: StateFlow<Boolean>,
    private val foreground: StateFlow<Boolean>,
    private val socket: LiveSocket,
    private val startService: () -> Unit,
    private val stopService: () -> Unit,
) {
    fun start(): Job = scope.launch {
        // The service follows (who, live mode) only — not every trip to the
        // background, which would re-promote it from the background each time.
        launch {
            combine(session, backgroundLive) { s, bg -> !s?.agentId.isNullOrEmpty() && bg }
                .distinctUntilChanged()
                .collect { if (it) startService() else stopService() }
        }
        combine(session, backgroundLive, foreground) { s, bg, fg -> Triple(s?.agentId, bg, fg) }
            .distinctUntilChanged()
            .collect { (agentId, bg, fg) ->
                when {
                    agentId.isNullOrEmpty() -> socket.signOut()
                    bg || fg -> socket.connect(agentId)
                    else -> socket.disconnect()
                }
            }
    }
}
