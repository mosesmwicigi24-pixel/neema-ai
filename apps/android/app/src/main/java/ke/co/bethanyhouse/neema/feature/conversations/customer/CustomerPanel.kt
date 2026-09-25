package ke.co.bethanyhouse.neema.feature.conversations.customer

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.ui.components.EmptyState

/**
 * The customer profile / CRM panel beside a thread (components/ui/CustomerSidebar.tsx).
 *
 * CONTRACT — the inbox calls exactly this signature:
 *  - [conversation]: the open thread's row
 *  - [onClose]: hide the panel
 *  - [onOpenIdentity]: jump to this person's thread on another channel
 *  - [onNameChange]: the agent renamed the customer; the inbox patches its rows
 *  - [hideHeader]: the phone layout shows its own sheet header
 * Orders come from dash.orders; toasts go through dash.toast().
 */
@Composable
fun CustomerPanel(
    dash: DashboardViewModel,
    conversation: Conversation,
    onClose: () -> Unit,
    onOpenIdentity: (channel: String, externalId: String) -> Unit,
    onNameChange: (waId: String, newName: String) -> Unit,
    modifier: Modifier = Modifier,
    hideHeader: Boolean = false,
) {
    EmptyState(title = conversation.name ?: "Customer", subtitle = "Profile coming next", modifier = modifier)
}
