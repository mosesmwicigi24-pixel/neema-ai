package ke.co.bethanyhouse.neema.core.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

/**
 * A detail sheet that fits the window: the phone's bottom sheet on a phone,
 * a panel sliding in from the end edge on a tablet window (600dp and wider —
 * a Tab S9 Ultra in any orientation, split screen, a pop-up) so a product or
 * a lead opens beside the list instead of a phone sheet rising across 14.6".
 * Back, a tap outside and the close control all dismiss it.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdaptiveSheet(
    onDismiss: () -> Unit,
    title: String,
    containerColor: Color,
    width: Dp = 440.dp,
    dragHandle: @Composable (() -> Unit)? = null,
    scrim: Color = Color.Black.copy(alpha = 0.4f),
    content: @Composable ColumnScope.() -> Unit,
) {
    val w = contentWidthDp()
    if (w < 600) {
        ModalBottomSheet(
            onDismissRequest = onDismiss,
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = containerColor,
            dragHandle = dragHandle ?: { androidx.compose.material3.BottomSheetDefaults.DragHandle() },
            scrimColor = scrim,
            content = content,
        )
        return
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        val shown = remember { MutableTransitionState(false).apply { targetState = true } }
        Box(
            Modifier.fillMaxSize().background(scrim)
                .clickable(remember { MutableInteractionSource() }, indication = null, onClickLabel = "Close $title", onClick = onDismiss),
        ) {
            AnimatedVisibility(shown, enter = slideInHorizontally(tween(220)) { it }, modifier = Modifier.align(Alignment.CenterEnd)) {
                Surface(
                    Modifier.width(minOf(width, (w * 0.9f).dp)).fillMaxHeight()
                        // Taps inside the panel stay inside it.
                        .clickable(remember { MutableInteractionSource() }, indication = null, enabled = true) {}
                        .semantics { paneTitle = title },
                    color = containerColor, shadowElevation = 16.dp,
                ) {
                    Column(Modifier.windowInsetsPadding(WindowInsets.statusBars.union(WindowInsets.navigationBars))) { content() }
                }
            }
        }
    }
}
