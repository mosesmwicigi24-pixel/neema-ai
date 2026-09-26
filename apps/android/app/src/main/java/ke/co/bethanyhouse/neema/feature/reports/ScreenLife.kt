package ke.co.bethanyhouse.neema.feature.reports

import androidx.compose.runtime.Composable

/*
 * These moved to core/util (ScreenLife.kt). The aliases keep every existing
 * `import ke.co.bethanyhouse.neema.feature.reports.{Coalescer, ScreenLife,
 * TrackShown}` compiling; new code should import from core.util directly.
 * `quietly` in ReportsViewModel.kt is the same function as core.util.quietly.
 */

typealias Coalescer = ke.co.bethanyhouse.neema.core.util.Coalescer
typealias ScreenLife = ke.co.bethanyhouse.neema.core.util.ScreenLife

/** Marks [life]'s screen as on display for as long as this is composed. */
@Composable
fun TrackShown(life: ScreenLife) = ke.co.bethanyhouse.neema.core.util.TrackShown(life)
