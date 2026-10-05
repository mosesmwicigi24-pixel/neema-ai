package ke.co.bethanyhouse.neema.feature.calls

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

/**
 * The device's call audio failing under WebRTC (the microphone taken by
 * another app, a recorder that never started, the speaker refusing): WebRTC
 * reports it on its own threads, far from the call. [CallManager] puts it on
 * the call card — a call never goes silent without a word.
 */
object CallAudioTrouble {
    private val _events = MutableSharedFlow<Boolean>(extraBufferCapacity = 8)
    /** true: the microphone; false: the speaker / earpiece. */
    val events: SharedFlow<Boolean> = _events

    fun mic() { _events.tryEmit(true) }
    fun speaker() { _events.tryEmit(false) }
}
