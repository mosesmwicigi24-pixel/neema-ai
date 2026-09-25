package ke.co.bethanyhouse.neema.feature.calls

import android.content.Context
import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** idle | ringing | connecting | in_call | ended (lib/callContext.tsx). */
enum class CallPhase { Idle, Ringing, Connecting, InCall, Ended }

data class CallUiState(
    val phase: CallPhase = CallPhase.Idle,
    val callId: String? = null,
    /** Customer wa_id (digits, no +). */
    val from: String? = null,
    val name: String? = null,
    val muted: Boolean = false,
    val speaker: Boolean = false,
    val seconds: Int = 0,
    val error: String? = null,
    val note: String? = null,
    /** True while we placed the call (ringing THEM). */
    val outbound: Boolean = false,
)

/**
 * The WhatsApp softphone: WebRTC peer connection, incoming-call ringing,
 * answer / decline / callback, outbound calls, mute, and call recording.
 * Port of lib/callContext.tsx. Process-wide (lives in AppContainer) so a call
 * survives navigating between screens.
 *
 * PUBLIC CONTRACT — other features call only these members.
 */
class CallManager(
    private val context: Context,
    private val api: NeemaApi,
    private val socket: LiveSocket,
    private val scope: CoroutineScope,
) {
    private val _state = MutableStateFlow(CallUiState())
    val state: StateFlow<CallUiState> = _state.asStateFlow()

    /** Begin listening for incoming_call / outbound_answer / call_ended and the poll fallback. */
    fun start() {}

    /** A notification action (answer/decline/show) routed through MainActivity. */
    fun handleIntent(intent: android.content.Intent) {}

    fun answer() {}
    fun hangup() {}
    fun callback() {}
    fun toggleMute() {}
    fun toggleSpeaker() {}

    /** Business-initiated call. Result.failure carries a user-facing message. */
    suspend fun initiateCall(to: String, name: String? = null): Result<Unit> =
        Result.failure(UnsupportedOperationException("Calling is not available yet"))
}
