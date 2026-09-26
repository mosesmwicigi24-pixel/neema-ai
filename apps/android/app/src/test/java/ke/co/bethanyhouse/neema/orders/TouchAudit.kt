package ke.co.bethanyhouse.neema.orders

import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import com.android.resources.ScreenOrientation

/** One tappable node as laid out: its label, and its size in dp. */
data class Tappable(val label: String, val width: Dp, val height: Dp, val labelled: Boolean) {
    fun smallerThan(min: Dp) = width < min || height < min
    override fun toString() = "\"$label\" ${width.value.toInt()}×${height.value.toInt()}dp"
}

/**
 * Reads the merged semantics tree once the content is laid out and records
 * every node with a click action — so a screenshot test can also assert touch
 * targets and labels (Paparazzi has no ComposeTestRule).
 */
class TouchAudit {
    val tappables = mutableListOf<Tappable>()

    @Composable
    fun Wrap(content: @Composable () -> Unit) {
        val view = LocalView.current
        val density = LocalDensity.current
        Box(
            Modifier.onGloballyPositioned {
                val owner = (view as? ViewRootForTest)?.semanticsOwner ?: return@onGloballyPositioned
                tappables.clear()
                fun walk(n: SemanticsNode) {
                    val c = n.config
                    if (c.getOrNull(SemanticsActions.OnClick) != null && n.boundsInRoot.width > 0f && n.boundsInRoot.height > 0f) {
                        val text = c.getOrNull(SemanticsProperties.Text)?.joinToString(" ") { it.text }
                        val desc = c.getOrNull(SemanticsProperties.ContentDescription)?.joinToString(" ")
                        val clickLabel = c.getOrNull(SemanticsActions.OnClick)?.label
                        // A text field names itself by its placeholder or what is typed in it.
                        val field = c.getOrNull(SemanticsProperties.EditableText)?.let { "field: ${it.text}" }
                        val label = listOfNotNull(desc, text, clickLabel, field).firstOrNull { it.isNotBlank() }
                        with(density) {
                            // The whole element as laid out, touch padding (minimumInteractiveComponentSize) included.
                            tappables += Tappable(label ?: "<unlabelled>", n.layoutInfo.width.toDp(), n.layoutInfo.height.toDp(), label != null)
                        }
                    }
                    n.children.forEach(::walk)
                }
                walk(owner.rootSemanticsNode)
            },
        ) { content() }
    }

    /** Tappables named [labels] (substring match) that are smaller than [min]. */
    fun tooSmall(min: Dp, vararg labels: String): List<Tappable> =
        tappables.filter { t -> labels.any { t.label.contains(it) } && t.smallerThan(min) }

    fun unlabelled(): List<Tappable> = tappables.filter { !it.labelled }
}

/** Round 7's device / font matrix. */
object Devices {
    /** 360dp wide at 130% text — the tightest phone the lens asks for. */
    val SmallPhoneLargeText = DeviceConfig.NEXUS_5.copy(fontScale = 1.3f)
    val Pixel5LargeText = DeviceConfig.PIXEL_5.copy(fontScale = 1.3f)
    /** Accessibility text at 200%. */
    val HugeText = DeviceConfig.PIXEL_6.copy(fontScale = 2.0f)
    /** ~600dp wide: an unfolded foldable / small tablet. */
    val Foldable = DeviceConfig.NEXUS_7
    val TabletLandscape = DeviceConfig.PIXEL_C
    val TabletPortrait = DeviceConfig.PIXEL_C.copy(
        screenWidth = DeviceConfig.PIXEL_C.screenHeight, screenHeight = DeviceConfig.PIXEL_C.screenWidth,
        orientation = ScreenOrientation.PORTRAIT,
    )
}
