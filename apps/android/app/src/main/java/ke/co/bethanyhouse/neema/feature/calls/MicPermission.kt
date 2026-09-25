package ke.co.bethanyhouse.neema.feature.calls

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat

fun hasMicPermission(ctx: Context): Boolean =
    ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

/**
 * Runs an action that needs the microphone, asking for RECORD_AUDIO first
 * when it hasn't been granted — the browser's getUserMedia prompt. The action
 * receives whether the mic is available; CallManager itself reports
 * "Microphone blocked — allow it and try again" when it is not.
 *
 * Usage (any feature that places a call):
 * ```
 * val withMic = rememberMicPermission()
 * withMic { granted -> scope.launch { calls.initiateCall(to, name) } }
 * ```
 */
@Composable
fun rememberMicPermission(): ((granted: Boolean) -> Unit) -> Unit {
    val ctx = LocalContext.current
    var pending by remember { mutableStateOf<((Boolean) -> Unit)?>(null) }
    val current by rememberUpdatedState(pending)
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        current?.invoke(granted)
        pending = null
    }
    return remember(launcher) {
        { action ->
            if (hasMicPermission(ctx)) action(true)
            else { pending = action; launcher.launch(Manifest.permission.RECORD_AUDIO) }
        }
    }
}
