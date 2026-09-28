package ke.co.bethanyhouse.neema.core.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * A panel that slides over the content from the end edge — the large-screen
 * form of a phone's bottom sheet (a customer profile, the activity log): it
 * keeps the thread visible and in place beside it instead of covering the
 * whole tablet from the bottom. A tap on the scrim or back closes it.
 *
 * Call it inside a Box that fills the area it should cover.
 */
@Composable
fun BoxScope.SideSheet(
    open: Boolean,
    width: Dp,
    title: String,
    onDismiss: () -> Unit,
    content: @Composable () -> Unit,
) {
    BackHandler(enabled = open, onBack = onDismiss)
    AnimatedVisibility(open, enter = fadeIn(tween(160)), exit = fadeOut(tween(160)), modifier = Modifier.matchParentSize()) {
        Box(
            Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.28f))
                .clickable(remember { MutableInteractionSource() }, indication = null, onClickLabel = "Close $title", onClick = onDismiss)
                .semantics { contentDescription = "Close $title" },
        )
    }
    AnimatedVisibility(
        open,
        enter = slideInHorizontally(tween(220)) { it },
        exit = slideOutHorizontally(tween(180)) { it },
        modifier = Modifier.align(Alignment.CenterEnd),
    ) {
        Surface(
            Modifier.width(width).fillMaxHeight().semantics { paneTitle = title },
            color = MaterialTheme.colorScheme.surface, shadowElevation = 12.dp,
        ) { Column { content() } }
    }
}
