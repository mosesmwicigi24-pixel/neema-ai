package ke.co.bethanyhouse.neema.core.ui.theme

import kotlin.math.abs

/**
 * The app's own text size (owner, 2026-11-20: "a button where you can enlarge
 * or reduce the fonts; that setting affects the entire app"). A multiplier on
 * top of the phone's own font size, applied once in [NeemaTheme], so every
 * screen follows it. Steps, not a slider: A− and A+ move one step.
 */
object TextScale {
    val STEPS = listOf(0.85f, 0.9f, 1f, 1.1f, 1.2f, 1.3f, 1.45f, 1.6f)
    const val DEFAULT = 1f

    /** The nearest step (a stored value from another version still lands on one). */
    fun clamp(v: Float): Float = STEPS.minBy { abs(it - v) }
    fun bigger(v: Float): Float = STEPS.getOrElse(STEPS.indexOf(clamp(v)) + 1) { STEPS.last() }
    fun smaller(v: Float): Float = STEPS.getOrElse(STEPS.indexOf(clamp(v)) - 1) { STEPS.first() }
    fun canGrow(v: Float) = clamp(v) < STEPS.last()
    fun canShrink(v: Float) = clamp(v) > STEPS.first()
    /** "100%", "120%". */
    fun label(v: Float): String = "${Math.round(clamp(v) * 100)}%"
}
