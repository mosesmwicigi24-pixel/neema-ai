package ke.co.bethanyhouse.neema.feature.orders

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.ui.theme.Neema

/**
 * A refresh failed while data is on screen: the data stays, and this thin
 * amber line over it says why, with a Retry. (Nothing on screen: the screen
 * shows `ErrorState` instead.)
 */
@Composable
fun StaleBanner(reason: String, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    val c = Neema.colors
    val shape = RoundedCornerShape(10.dp)
    val fg = if (c.isDark) Color(0xFFFCD34D) else Color(0xFF92400E)
    Row(
        modifier.fillMaxWidth().clip(shape)
            .background(if (c.isDark) c.amberDim else Color(0xFFFFFBEB))
            .border(1.dp, if (c.isDark) c.amber.copy(alpha = 0.35f) else Color(0xFFFDE68A), shape)
            .padding(start = 12.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.CloudOff, contentDescription = null, tint = fg, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f).padding(vertical = 6.dp)) {
            Text("Couldn't refresh — showing what was loaded", fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.SemiBold, color = fg)
            Text(reason, fontSize = 12.sp, lineHeight = 16.sp, color = fg.copy(alpha = 0.85f))
        }
        Text(
            "Retry", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg,
            modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onRetry)
                .padding(horizontal = 10.dp, vertical = 8.dp),
        )
    }
}

/**
 * An action's failure shown where the operator is typing (a sheet or dialog),
 * so it is never missed. [pending]: not a failure yet — the outcome is being
 * checked — so it reads amber, not red.
 */
@Composable
fun InlineError(message: String, modifier: Modifier = Modifier, pending: Boolean = false) {
    val c = Neema.colors
    val fg = when {
        pending -> if (c.isDark) Color(0xFFFCD34D) else Color(0xFF92400E)
        else -> if (c.isDark) Color(0xFFFCA5A5) else Color(0xFFB91C1C)
    }
    val bg = when {
        pending -> if (c.isDark) c.amberDim else Color(0xFFFFFBEB)
        else -> if (c.isDark) c.redDim else Color(0xFFFEF2F2)
    }
    Text(
        message,
        fontSize = 12.sp, lineHeight = 16.sp, color = fg,
        modifier = modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(bg)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    )
}
