package ke.co.bethanyhouse.neema.testing

import android.graphics.Canvas
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.compose.ui.platform.ViewRootForTest
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsNode
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import app.cash.paparazzi.RenderExtension

/**
 * Round 7: a cheap accessibility check on top of Paparazzi. Add it to the
 * rule and every snapshot also records the rendered Compose semantics:
 *
 * ```
 * private val probe = A11yProbe()
 * @get:Rule val paparazzi = Paparazzi(deviceConfig = …, renderExtensions = setOf(probe))
 *
 * @Test fun touchTargets() {
 *     paparazzi.snapshot { AppFrame { MyScreen() } }
 *     probe.assertAccessible()            // every tappable ≥ 48dp and labelled
 * }
 * ```
 *
 * Note: the extension wraps the rendered view, so a rule with a probe
 * writes images that differ from one without; use it on a dedicated test
 * class rather than on the one holding your existing goldens.
 */
class A11yProbe : RenderExtension {
    /** What one tappable node looked like on the last frame. */
    data class Tappable(val label: String, val widthDp: Float, val heightDp: Float, val role: String?) {
        override fun toString() = "\"$label\" ${widthDp.toInt()}×${heightDp.toInt()}dp${role?.let { " ($it)" } ?: ""}"
    }

    @Volatile var tappables: List<Tappable> = emptyList()
        private set

    override fun renderView(contentView: View): View = object : FrameLayout(contentView.context) {
        init { addView(contentView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)) }
        override fun dispatchDraw(canvas: Canvas) {
            super.dispatchDraw(canvas)
            tappables = collect(this)
        }
    }

    private fun collect(root: View): List<Tappable> {
        val out = mutableListOf<Tappable>()
        fun visit(v: View) {
            if (v is ViewRootForTest) {
                val density = v.view.resources.displayMetrics.density
                walk(v.semanticsOwner.rootSemanticsNode, density, out)
            }
            if (v is ViewGroup) for (i in 0 until v.childCount) visit(v.getChildAt(i))
        }
        visit(root)
        return out
    }

    private fun walk(node: SemanticsNode, density: Float, out: MutableList<Tappable>) {
        val cfg = node.config
        val clickable = cfg.getOrNull(SemanticsActions.OnClick) != null
        val hidden = cfg.getOrNull(SemanticsProperties.InvisibleToUser) != null
        if (clickable && !hidden) {
            val label = cfg.getOrNull(SemanticsProperties.ContentDescription)?.joinToString(" ")
                ?: cfg.getOrNull(SemanticsProperties.Text)?.joinToString(" ") { it.text }?.takeIf { it.isNotBlank() }
                ?: cfg.getOrNull(SemanticsProperties.EditableText)?.text?.takeIf { it.isNotBlank() }
                ?: cfg.getOrNull(SemanticsProperties.StateDescription)
                ?: ""
            val size = node.size
            out += Tappable(label.trim(), size.width / density, size.height / density, cfg.getOrNull(SemanticsProperties.Role)?.toString())
        }
        node.children.forEach { walk(it, density, out) }
    }

    /** Tappables smaller than [minDp] on either side (excluding [exempt] labels). */
    fun undersized(minDp: Float = 48f, exempt: Set<String> = emptySet()): List<Tappable> =
        tappables.filter { it.label !in exempt && (it.widthDp < minDp - 0.5f || it.heightDp < minDp - 0.5f) }

    /** Tappables TalkBack would announce with no words. */
    fun unlabelled(): List<Tappable> = tappables.filter { it.label.isBlank() }

    /** Fails with a readable list when a tappable is unlabelled or under [minDp]. */
    fun assertAccessible(minDp: Float = 48f, exempt: Set<String> = emptySet()) {
        check(tappables.isNotEmpty()) { "A11yProbe saw no tappable nodes — was it added to the Paparazzi rule's renderExtensions?" }
        val small = undersized(minDp, exempt)
        val blank = unlabelled()
        if (small.isNotEmpty() || blank.isNotEmpty()) throw AssertionError(
            buildString {
                if (blank.isNotEmpty()) append("Unlabelled tappables: $blank\n")
                if (small.isNotEmpty()) append("Tappables under ${minDp.toInt()}dp: $small\n")
                append("All tappables: $tappables")
            },
        )
    }
}
