"""Channel-agnostic conversation handling — the read/write seam above wa_id.

`get_or_create_conversation` keys a conversation on its natural
`(channel, external_id)` pair instead of wa_id, so Messenger (PSID) and
Instagram (IGSID) conversations are first-class alongside WhatsApp. For WhatsApp,
`external_id == wa_id` and `wa_id` stays populated, so the existing
`Conversation.wa_id == wa_id` code path is unaffected (compat shim).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation

WHATSAPP = "whatsapp"


async def get_or_create_conversation(
    db: AsyncSession,
    channel: str,
    external_id: str,
    *,
    person_id=None,
    wa_id: str | None = None,
) -> Conversation:
    """Find-or-create the conversation for `(channel, external_id)`. For WhatsApp,
    wa_id defaults to external_id. Sets person_id on create, and adopts one on an
    existing conversation that has none. Caller owns the commit (this flushes)."""
    external_id = (external_id or "").strip()
    if not external_id:
        raise ValueError("external_id is required")

    conv = (await db.execute(
        select(Conversation).where(
            Conversation.channel == channel,
            Conversation.external_id == external_id,
        )
    )).scalar_one_or_none()

    if conv is None:
        conv = Conversation(
            channel=channel,
            external_id=external_id,
            wa_id=(external_id if channel == WHATSAPP else wa_id),
            person_id=person_id,
        )
        db.add(conv)
        await db.flush()
    elif person_id is not None and conv.person_id is None:
        conv.person_id = person_id

    return conv
