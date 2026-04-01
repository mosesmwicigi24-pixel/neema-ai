from pydantic import BaseModel
from typing import Any

class OutboundDto(BaseModel):
    wa_id: str
    ai_reply: str
    session_id: str | None = None

class SessionDto(BaseModel):
    wa_id: str
    session_id: str | None = None
    turns: int = 0
    start_ts: str | None = None
    last_ts: str | None = None

class MessageDto(BaseModel):
    wa_id: str
    direction: str = "inbound"
    text: str = ""
    ts_ms: int | None = None
    ts_iso: str | None = None
    docid: str | None = None
    # Media fields — populated when n8n forwards an image/document/video/audio message
    media_type: str | None = None   # "image" | "document" | "video" | "audio"
    media_url:  str | None = None   # publicly reachable download URL

class UpsertMessagePatchDto(BaseModel):
    inbound_text: str | None = None
    outbound_text: str | None = None
    direction: str | None = None
    ts_ms: int | None = None

class UserDto(BaseModel):
    wa_id: str
    phone: str | None = None
    last_text: str | None = None
    last_direction: str | None = None
    state: dict | None = None

class UserFactsDto(BaseModel):
    wa_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    age: int | None = None

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