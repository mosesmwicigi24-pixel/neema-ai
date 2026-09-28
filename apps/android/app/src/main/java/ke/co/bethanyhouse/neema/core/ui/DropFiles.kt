package ke.co.bethanyhouse.neema.core.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.net.Uri
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.draganddrop.dragAndDropTarget
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.draganddrop.DragAndDropEvent
import androidx.compose.ui.draganddrop.DragAndDropTarget
import androidx.compose.ui.draganddrop.mimeTypes
import androidx.compose.ui.draganddrop.toAndroidDragEvent
import androidx.compose.ui.platform.LocalContext

/**
 * Files dragged in from another app (Gallery or My Files beside Neema in split
 * screen, a DeX window, a desktop): [onFiles] gets their URIs, readable for the
 * life of the activity (the drop's permissions are requested here — without
 * them another app's content URI can't be opened). [hovering] is true while a
 * droppable drag is over the area, for the "Drop to attach" highlight.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun Modifier.dropFiles(enabled: Boolean, hovering: MutableState<Boolean>, onFiles: (List<Uri>) -> Unit): Modifier {
    if (!enabled) return this
    val activity = LocalContext.current.findActivity()
    val latest = rememberUpdatedState(onFiles)
    val target = remember(activity) {
        object : DragAndDropTarget {
            override fun onEntered(event: DragAndDropEvent) { hovering.value = true }
            override fun onExited(event: DragAndDropEvent) { hovering.value = false }
            override fun onEnded(event: DragAndDropEvent) { hovering.value = false }
            override fun onDrop(event: DragAndDropEvent): Boolean {
                hovering.value = false
                val drag = event.toAndroidDragEvent()
                runCatching { activity?.requestDragAndDropPermissions(drag) }
                val clip = drag.clipData ?: return false
                val uris = (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri }
                if (uris.isEmpty()) return false
                latest.value(uris)
                return true
            }
        }
    }
    return dragAndDropTarget(shouldStartDragAndDrop = { e -> acceptsDrop(e.mimeTypes()) }, target = target)
}

/** A drag Neema can attach: images, video, audio, PDFs and office documents — not plain text. */
fun acceptsDrop(mimeTypes: Collection<String>): Boolean = mimeTypes.any { m ->
    val t = m.lowercase()
    t.startsWith("image/") || t.startsWith("video/") || t.startsWith("audio/") ||
        t == "application/pdf" || t.startsWith("application/vnd.") || t == "application/msword" ||
        t == "application/octet-stream"
}

@Composable
fun rememberDropHover(): MutableState<Boolean> = remember { mutableStateOf(false) }

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
