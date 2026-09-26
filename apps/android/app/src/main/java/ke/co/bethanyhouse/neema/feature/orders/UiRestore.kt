package ke.co.bethanyhouse.neema.feature.orders

import androidx.compose.runtime.Composable
import ke.co.bethanyhouse.neema.core.util.str as coreStr

/*
 * Moved to core (ke.co.bethanyhouse.neema.core.util.UiRestore.kt) so every
 * feature can use it; these forwards keep existing imports compiling until
 * the integrator points them at core and deletes this file.
 */

typealias SavesUi = ke.co.bethanyhouse.neema.core.util.SavesUi

@Composable
fun RestoreUi(vm: SavesUi) = ke.co.bethanyhouse.neema.core.util.RestoreUi(vm)

fun Map<String, Any?>.str(key: String): String? = coreStr(key)

val LocalMinute get() = ke.co.bethanyhouse.neema.core.util.LocalMinute

@Composable
fun MinuteTicker(content: @Composable () -> Unit) = ke.co.bethanyhouse.neema.core.util.MinuteTicker(content)

@Composable
fun liveAgo(iso: String?): String = ke.co.bethanyhouse.neema.core.util.liveAgo(iso)
