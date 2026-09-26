package ke.co.bethanyhouse.neema.feature.conversations

import ke.co.bethanyhouse.neema.core.api.InboxQuery
import kotlinx.serialization.Serializable

/**
 * What the inbox keeps on disk (per agent, in the snapshot cache) so that
 * Android killing the app in the background loses none of the agent's work:
 * which filters and which conversation were open, every half-typed reply
 * (each customer keeps their own), notes, AI drafts being edited, files
 * picked but not sent, and every send that had not been confirmed.
 *
 * The web keeps none of this across a reload (one `replyText` for the whole
 * view); on a phone the OS reloads the app on its own, so the app does.
 * A sign-out wipes it: the next agent on a shared phone sees nothing.
 */
@Serializable
internal data class InboxMemory(
    val activeId: String = "",
    val threadOpen: Boolean = false,
    val tab: String = "all",
    val channel: String = "all",
    val mode: String = "all",
    val tag: String? = null,
    /** The search box as typed (the query it runs is [q], after the pause). */
    val search: String = "",
    val q: String = "",
    val showFilters: Boolean = false,
    /** Each person's composer, by composer key (the open one included). */
    val composers: Map<String, SavedComposer> = emptyMap(),
    val txMode: Map<String, Boolean> = emptyMap(),
    /** Half-written internal notes, by conversation. */
    val notes: Map<String, String> = emptyMap(),
    /** The open thread's dialog: "note" | "transfer" | null. */
    val dialog: String? = null,
    /** Sends not yet confirmed (or refused and waiting for Retry / Edit). */
    val outbox: List<SavedOutgoing> = emptyList(),
) {
    val filters: InboxQuery get() = InboxQuery(tab = tab, channel = channel, mode = mode, tag = tag, q = q)
    val isEmpty: Boolean get() = this == InboxMemory()
}

@Serializable
internal data class SavedQuote(
    val msgId: String? = null, val sender: String? = null, val text: String = "", val channel: String = "whatsapp",
    val mediaUrl: String? = null, val mediaType: String? = null,
)

@Serializable
internal data class SavedMedia(
    val uri: String, val name: String, val mime: String, val size: Long, val caption: String = "",
    /** It was re-encoded to fit (the bytes are rebuilt from [uri] on restore). */
    val reencoded: Boolean = false,
    val error: String? = null,
    val unconfirmed: Boolean = false,
)

@Serializable
internal data class SavedComposer(
    val replyText: String = "",
    val quoted: SavedQuote? = null,
    val draftVisible: Boolean = false,
    val draftExpanded: Boolean = false,
    val draftText: String = "",
    val draftEditing: Boolean = false,
    val media: List<SavedMedia> = emptyList(),
    val lostMedia: List<String> = emptyList(),
) {
    val isEmpty: Boolean get() = this == SavedComposer()
}

@Serializable
internal data class SavedOutgoing(
    val localId: String,
    val convId: String,
    val kind: String,
    val text: String,
    val replyToId: String? = null,
    val origText: String? = null,
    val origLang: String? = null,
    val typed: String = text,
    val quoted: SavedQuote? = null,
    val known: List<String> = emptyList(),
    val failed: Boolean = false,
    /** Its first attempt got no answer: a retry looks for it on the server before sending again. */
    val checking: Boolean = false,
    val retried: Boolean = false,
    /** Refused with a 401: it never left, and goes once the agent signs in again. */
    val authHeld: Boolean = false,
    /** The bubble as it was drawn (text, time, quote). */
    val bubble: ThreadMsg,
    val error: String? = null,
)

internal fun Quoted.saved() = SavedQuote(msgId, sender, text, channel, mediaUrl, mediaType)
internal fun SavedQuote.live() = Quoted(msgId, sender, text, channel, mediaUrl, mediaType)

internal fun ComposerUi.saved(): SavedComposer = SavedComposer(
    replyText = replyText, quoted = quoted?.saved(),
    draftVisible = draftVisible, draftExpanded = draftExpanded, draftText = draftText, draftEditing = draftEditing,
    media = media.map { SavedMedia(it.uri.toString(), it.name, it.mime, it.size, it.caption, it.bytes != null, it.error, it.unconfirmed) },
    lostMedia = lostMedia,
)

/** Everything but the files, which need a check that Android still lets the app read them. */
internal fun SavedComposer.liveWithoutMedia(): ComposerUi = ComposerUi(
    replyText = replyText, quoted = quoted?.live(),
    draftVisible = draftVisible, draftExpanded = draftExpanded, draftText = draftText, draftEditing = draftEditing,
    lostMedia = lostMedia,
)

/** The media viewer across rotation and process death (rememberSaveable). */
internal val ViewerSaver = androidx.compose.runtime.saveable.Saver<Viewer?, ArrayList<String?>>(
    save = { v ->
        when (v) {
            null -> null
            is Viewer.Image -> arrayListOf("image", v.url)
            is Viewer.Video -> arrayListOf("video", v.url, v.messageId)
            is Viewer.Album -> arrayListOf<String?>("album", v.start.toString()).apply { v.items.forEach { add(it.src); add(it.caption) } }
        }
    },
    restore = { l ->
        when (l.getOrNull(0)) {
            "image" -> l.getOrNull(1)?.let { Viewer.Image(it) }
            "video" -> l.getOrNull(1)?.let { Viewer.Video(it, l.getOrNull(2)) }
            "album" -> {
                val items = l.drop(2).chunked(2).mapNotNull { p -> p.getOrNull(0)?.let { AlbumItem(it, p.getOrNull(1)) } }
                if (items.isEmpty()) null else Viewer.Album(items, (l.getOrNull(1)?.toIntOrNull() ?: 0).coerceIn(0, items.lastIndex))
            }
            else -> null
        }
    },
)
