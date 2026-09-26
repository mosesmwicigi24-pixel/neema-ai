package ke.co.bethanyhouse.neema.feature.conversations

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaMono
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.em
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

/**
 * Port of lib/waText.tsx: render WhatsApp-style inline formatting the way
 * WhatsApp does — *bold* (and legacy Markdown **bold**), _italics_,
 * ~strikethrough~, `monospace` and ```monospace``` — and make links tappable.
 * Display-only; the stored text is untouched. Longer delimiters are listed
 * first so `**x**` / ```x``` win over `*x*` / `x` at the same position.
 */
private val TOKEN = Regex("(```[^`]+```|\\*\\*[^*\\n]+\\*\\*|\\*[^*\\n]+\\*|_[^_\\n]+_|~[^~\\n]+~|`[^`\\n]+`)")
private val URL = Regex("(https?://[^\\s<>\"]+|www\\.[^\\s<>\"]+)", RegexOption.IGNORE_CASE)

/**
 * [formatWa] for composition: the regex passes over a long message run once
 * per text (and link colour), not on every recomposition of its bubble.
 */
@androidx.compose.runtime.Composable
fun rememberWa(text: String?, linkColor: Color = Palette.Blue600): AnnotatedString =
    androidx.compose.runtime.remember(text, linkColor) { formatWa(text, linkColor) }

fun formatWa(text: String?, linkColor: Color = Palette.Blue600): AnnotatedString {
    if (text.isNullOrEmpty()) return AnnotatedString("")
    val styled = buildAnnotatedString {
        var last = 0
        for (m in TOKEN.findAll(text)) {
            if (m.range.first > last) append(text.substring(last, m.range.first))
            val part = m.value
            when {
                part.startsWith("```") && part.length > 6 ->
                    withStyle(SpanStyle(fontFamily = NeemaMono, fontSize = 0.95.em)) { append(part.substring(3, part.length - 3)) }
                part.startsWith("**") && part.endsWith("**") && part.length > 4 ->
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(part.substring(2, part.length - 2)) }
                part.startsWith("*") && part.length > 2 ->
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(part.substring(1, part.length - 1)) }
                part.startsWith("_") && part.length > 2 ->
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(part.substring(1, part.length - 1)) }
                part.startsWith("~") && part.length > 2 ->
                    withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) { append(part.substring(1, part.length - 1)) }
                part.startsWith("`") && part.length > 2 ->
                    withStyle(SpanStyle(fontFamily = NeemaMono, fontSize = 0.95.em)) { append(part.substring(1, part.length - 1)) }
                else -> append(part)
            }
            last = m.range.last + 1
        }
        if (last < text.length) append(text.substring(last))
    }
    // Links are found on the rendered text so a link inside *bold* still works.
    val plain = styled.text
    val links = URL.findAll(plain).toList()
    if (links.isEmpty()) return styled
    return buildAnnotatedString {
        append(styled)
        val style = TextLinkStyles(SpanStyle(color = linkColor, textDecoration = TextDecoration.Underline))
        for (m in links) {
            // Trailing punctuation belongs to the sentence, not the URL.
            var end = m.range.last + 1
            while (end > m.range.first && plain[end - 1] in ".,;:!?)") end--
            val raw = plain.substring(m.range.first, end)
            val url = if (raw.startsWith("www.", ignoreCase = true)) "https://$raw" else raw
            addLink(LinkAnnotation.Url(url, style), m.range.first, end)
        }
    }
}
