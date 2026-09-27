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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
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
    // Who took it — not for calls nobody answered (as the web's pill).
    val agent = agentFirst(msg.agentName ?: call?.agentName)
        ?.takeIf { call?.status !in setOf("missed", "no_answer", "cancelled", "failed") }
    val time = (call?.startedAt ?: msg.createdAt)?.let { Fmt.time(it) }.orEmpty()
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
        val summary = (call?.summary ?: msg.eventReason)?.trim()?.takeIf { it.isNotEmpty() }
        val insights = call?.insights
        val facts = listOf("Products" to insights?.products, "Objections" to insights?.objections, "Commitments" to insights?.commitments)
            .mapNotNull { (k, v) -> v?.takeIf { it.isNotEmpty() }?.let { k to it } }
        val followUp = insights?.followUpMessage?.trim()?.takeIf { it.isNotEmpty() }
        if (summary != null || insights?.nextAction != null || followUp != null || facts.isNotEmpty()) {
            CallSummaryCard(summary, insights?.nextAction, facts, followUp, onUseAsReply)
        }
    }
}

/**
 * The web's CallPill card: the summary (three lines, then "Show more"), the
 * next action, products / objections / commitments, and the suggested reply
 * — shown in full, so the agent sees what "Use as reply" puts in the box.
 */
@Composable
private fun CallSummaryCard(
    summary: String?,
    nextAction: String?,
    facts: List<Pair<String, List<String>>>,
    followUp: String?,
    onUseAsReply: (String) -> Unit,
) {
    val c = Neema.colors
    val green = if (c.isDark) Palette.Emerald300 else Palette.Emerald700
    var more by rememberSaveable(summary) { mutableStateOf(false) }
    var used by rememberSaveable(followUp) { mutableStateOf(false) }
    Column(
        Modifier.padding(top = 6.dp).fillMaxWidth(0.88f).widthIn(max = 560.dp).clip(RoundedCornerShape(12.dp))
            .background(if (c.isDark) ChannelColors.WhatsApp.copy(alpha = 0.08f) else Color.White)
            .border(1.dp, if (c.isDark) ChannelColors.WhatsApp.copy(alpha = 0.3f) else Palette.Emerald100, RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .semantics { contentDescription = "Call summary" },
    ) {
        Text("CALL SUMMARY", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp, color = green)
        summary?.let {
            val long = it.length > 220
            Spacer(Modifier.height(4.dp))
            Text(
                it, fontSize = 12.sp, lineHeight = 17.sp, color = c.text,
                maxLines = if (long && !more) 3 else Int.MAX_VALUE, overflow = TextOverflow.Ellipsis,
            )
            if (long) {
                Box(
                    Modifier.heightIn(min = 32.dp).clickable(role = Role.Button) { more = !more },
                    contentAlignment = Alignment.CenterStart,
                ) { Text(if (more) "Show less" else "Show more", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = green) }
            }
        }
        nextAction?.let {
            Spacer(Modifier.height(6.dp))
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append("Next: ") }
                    append(it)
                },
                fontSize = 12.sp, lineHeight = 17.sp, color = c.text,
            )
        }
        if (facts.isNotEmpty()) Spacer(Modifier.height(6.dp))
        facts.forEach { (k, v) ->
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = c.textMid)) { append("$k: ") }
                    append(v.joinToString(" · "))
                },
                fontSize = 11.sp, lineHeight = 16.sp, color = c.text,
            )
        }
        followUp?.let { reply ->
            Spacer(Modifier.height(8.dp))
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                    .background(if (c.isDark) Color.White.copy(alpha = 0.05f) else Palette.Call.SuggestedReplyBg)
                    .padding(horizontal = 10.dp, vertical = 8.dp),
            ) {
                Text("SUGGESTED REPLY", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp, color = c.textMid)
                Spacer(Modifier.height(2.dp))
                Text(reply, fontSize = 12.sp, lineHeight = 17.sp, color = c.text)
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.heightIn(min = 48.dp)
                            .clickable(role = Role.Button, onClickLabel = "Put the suggested reply in the message box") { onUseAsReply(reply); used = true },
                        contentAlignment = Alignment.CenterStart,
                    ) {
                        Row(
                            Modifier.clip(RoundedCornerShape(8.dp)).background(Palette.Call.ReplyGreen)
                                .padding(horizontal = 12.dp, vertical = 9.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center,
                        ) {
                            Text("Use as reply", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color.White, textAlign = TextAlign.Center)
                        }
                    }
                    Spacer(Modifier.width(8.dp))
                    Text(
                        if (used) "In the reply box — edit, then send" else "Goes in the reply box — not sent",
                        fontSize = 11.sp, color = c.textMid, modifier = Modifier.weight(1f).semantics { liveRegion = LiveRegionMode.Polite },
                    )
                }
            }
        }
    }
}
