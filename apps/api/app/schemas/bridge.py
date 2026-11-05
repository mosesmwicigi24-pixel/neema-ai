"""DTOs of the messaging service and the hub bridge: what the WhatsApp
pipeline persists and what the Bethany House hub pushes into Neema."""
from pydantic import BaseModel
from typing import Any

class MessageDto(BaseModel):
    wa_id: str
    name: str | None = None
    direction: str = "inbound"
    text: str = ""
    ts_ms: int | None = None
    ts_iso: str | None = None
    docid: str | None = None
    # Media fields — populated for an image/document/video/audio message
    media_type: str | None = None
    media_url:  str | None = None
    media_id:      str | None = None
    media_caption: str | None = None
    mime_type:     str | None = None
    filename:      str | None = None
    # Image analysis — an optional description of the image, stored in
    # media_caption so the UI can render it as a collapsible "Image Analysis"
    # block (analogous to the
    # audio transcription toggle). The user's own caption text (if any) is
    # carried in `text` and rendered below the image in the conversation view.
    image_analysis: str | None = None
    # What a non-plain message IS (services/inbound_kinds.py): location,
    # contact, reaction, call-permission reply, unsupported + Meta's errors and
    # a redacted payload copy. Stored on messages.raw_meta; None for text/media.
    raw_meta: dict | None = None


class OrderEventDto(BaseModel):
    wa_id: str
    session_id: str | None = None
    event_type: str | None = None
    items: list[Any] = []
    subtotal: float = 0
    currency: str = "KES"
    status: str = "open"
    payment_status: str = "unpaid"
    fulfillment_status: str = "pending"
    reply_text: str | None = None
    channel: str = "whatsapp"
    state: dict = {}


class CustomerHistoryDto(BaseModel):
    wa_id: str
    last_status: str | None = None
    has_open_order: bool = False
    last_event: dict | None = None
    counts: dict | None = None


class PaymentDto(BaseModel):
    """An M-Pesa (or other) payment the hub captured, relayed here to bind the
    payer into the phone-anchored person world (docs/MULTICHANNEL_IDENTITY_PLAN.md
    lever 2). Only `payer_msisdn` is required; the rest enrich the link. Extra
    fields the hub sends are ignored."""
    payer_msisdn: str                       # the paying phone (any format; canonicalized to E.164)
    payer_name: str | None = None           # M-Pesa registered name
    mpesa_ref: str | None = None            # M-Pesa transaction code (portable token)
    hub_order_id: int | None = None         # hub order this paid (to stamp the local order_event)
    order_number: str | None = None         # human order number (portable token)
    region: str = "KE"                      # default region for a local number
