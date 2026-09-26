package ke.co.bethanyhouse.neema.feature.conversations

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.model.CallInsights
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.calls.CallIcons
import ke.co.bethanyhouse.neema.feature.calls.CallTone
import ke.co.bethanyhouse.neema.feature.calls.agentFirst
import ke.co.bethanyhouse.neema.feature.calls.callRowWords

/**
 * A WhatsApp call in the thread, where it happened (CALLING_UX.md §7): a
 * centred pill — incoming / outgoing / missed icon, the server's label
 * ("Incoming call · 4:12", "Missed call"), who took it, the time — and, when
 * the call was summarised, a card under it: the summary, the next action and
 * "Use as reply", which puts the AI's follow-up in the composer (never sends).
 */
@Composable
internal fun ThreadCallEvent(msg: ThreadMsg, onUseAsReply: (String) -> Unit) {
    val call = msg.call
    val c = Neema.colors
    val words = call?.let(::callRowWords)
    val tone = when (words?.tone) {
        CallTone.Bad -> if (c.isDark) Palette.Red300 else Palette.Red700
        CallTone.Warn -> if (c.isDark) Palette.Amber300 else Palette.Amber700
        CallTone.Live, CallTone.Good -> if (c.isDark) Palette.Emerald300 else Palette.Emerald700
        else -> c.textMid
    }
    val label = msg.body.ifBlank { words?.label ?: "Call" }
    val agent = agentFirst(msg.agentName ?: call?.agentName)
    val time = msg.createdAt?.let { Fmt.time(it) }.orEmpty()
    val line = listOfNotNull(label, agent, time.ifEmpty { null }).joinToString(" · ")
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Row(
            Modifier.clip(RoundedCornerShape(50)).background(if (c.isDark) c.bg3 else Palette.Stone100)
                .border(1.dp, if (c.isDark) c.border else Palette.Stone200, RoundedCornerShape(50))
                .padding(horizontal = 12.dp, vertical = 6.dp)
                .clearAndSetSemantics { contentDescription = "WhatsApp call: $line" },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(words?.icon ?: CallIcons.Phone, null, tint = tone, modifier = Modifier.size(13.dp))
            Spacer(Modifier.width(6.dp))
            Text(label, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = tone, maxLines = 1)
            val rest = listOfNotNull(agent, time.ifEmpty { null }).joinToString(" · ")
            if (rest.isNotEmpty()) Text(" · $rest", fontSize = 11.sp, color = c.textMid, maxLines = 1)
        }
        val summary = (msg.eventReason ?: call?.summary)?.takeIf { it.isNotBlank() }
        val insights = call?.insights
        if (summary != null || insights != null) CallSummaryCard(summary, insights, onUseAsReply)
    }
}

@Composable
private fun CallSummaryCard(summary: String?, insights: CallInsights?, onUseAsReply: (String) -> Unit) {
    val c = Neema.colors
    val green = if (c.isDark) Palette.Emerald300 else Palette.Emerald700
    Column(
        Modifier.padding(top = 6.dp).fillMaxWidth(0.88f).widthIn(max = 560.dp).clip(RoundedCornerShape(12.dp))
            .background(if (c.isDark) ChannelColors.WhatsApp.copy(alpha = 0.08f) else Palette.Emerald50)
            .border(1.dp, ChannelColors.WhatsApp.copy(alpha = 0.3f), RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text("CALL SUMMARY", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp, color = green)
        summary?.let {
            Spacer(Modifier.height(4.dp))
            Text(it, fontSize = 12.sp, lineHeight = 17.sp, color = c.text)
        }
        insights?.nextAction?.let {
            Spacer(Modifier.height(6.dp))
            Text("Next: $it", fontSize = 12.sp, lineHeight = 17.sp, color = c.text, fontWeight = FontWeight.Medium)
        }
        insights?.commitments?.takeIf { it.isNotEmpty() }?.let {
            Spacer(Modifier.height(4.dp))
            Text("Agreed: ${it.joinToString("; ")}", fontSize = 11.sp, lineHeight = 16.sp, color = c.textMid)
        }
        insights?.followUpMessage?.let { reply ->
            Spacer(Modifier.height(4.dp))
            Box(
                Modifier.heightIn(min = 48.dp).clip(RoundedCornerShape(50))
                    .clickable(role = Role.Button, onClickLabel = "Put the suggested reply in the message box") { onUseAsReply(reply) },
                contentAlignment = Alignment.CenterStart,
            ) {
                Row(
                    Modifier.clip(RoundedCornerShape(50)).background(ChannelColors.WhatsApp.copy(alpha = 0.16f))
                        .padding(horizontal = 12.dp, vertical = 7.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center,
                ) {
                    Icon(CallIcons.Chat, null, tint = green, modifier = Modifier.size(13.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Use as reply", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = green, textAlign = TextAlign.Center)
                }
            }
        }
    }
}
