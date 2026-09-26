package ke.co.bethanyhouse.neema.feature.reports

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.ui.theme.Neema

/**
 * A load that failed, said in place: an amber notice with the reason and a
 * Retry. Used where a card or a screen would otherwise sit on "Loading…"
 * forever, or show figures that are not the server's.
 */
@Composable
fun LoadProblem(
    message: String,
    modifier: Modifier = Modifier,
    title: String? = null,
    retrying: Boolean = false,
    onRetry: (() -> Unit)? = null,
) {
    val c = Neema.colors
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
            .background(c.amberDim)
            .border(1.dp, c.amber.copy(alpha = 0.35f), RoundedCornerShape(10.dp))
            .padding(start = 12.dp, top = 10.dp, bottom = 10.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.CloudOff, null, tint = c.amber, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            if (title != null) Text(title, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
            Text(message, fontSize = 12.sp, lineHeight = 17.sp, color = c.text.copy(alpha = 0.72f))
        }
        if (onRetry != null) {
            TextButton(
                onClick = onRetry, enabled = !retrying,
                contentPadding = PaddingValues(horizontal = 10.dp),
                modifier = Modifier.defaultMinSize(minHeight = 36.dp),
            ) {
                Text(if (retrying) "Retrying…" else "Retry", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.gold2)
            }
        }
    }
}
