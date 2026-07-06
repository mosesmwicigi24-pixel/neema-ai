from pydantic import BaseModel
from typing import Any

class OutboundDto(BaseModel):
    wa_id: str
    ai_reply: str
    session_id: str | None = None
    # Audio reply fields — populated when the workflow responds with TTS audio
    is_audio_reply: bool = False
    audio_url: str | None = None       # stable URL of the TTS mp3 file
    transcription: str | None = None   # original user voice message transcription
    cart_text: str | None = None       # cart summary text to accompany the audio

class SessionDto(BaseModel):
    wa_id: str
    session_id: str | None = None
    turns: int = 0
    start_ts: str | None = None
    last_ts: str | None = None

class MessageDto(BaseModel):
    wa_id: str
    name: str | None = None
    direction: str = "inbound"
    text: str = ""
    ts_ms: int | None = None
    ts_iso: str | None = None
    docid: str | None = None
    # Media fields — populated when n8n forwards an image/document/video/audio message
    media_type: str | None = None
    media_url:  str | None = None
    media_id:      str | None = None
    media_caption: str | None = None
    mime_type:     str | None = None
    filename:      str | None = None
    # Image analysis — populated by the Product Image Recognition sub-workflow.
    # The GPT-4o description of the image; stored in media_caption so the UI
    # can render it as a collapsible "Image Analysis" block (analogous to the
    # audio transcription toggle). The user's own caption text (if any) is
    # carried in `text` and rendered below the image in the conversation view.
    image_analysis: str | None = None

class UpsertMessagePatchDto(BaseModel):
    inbound_text: str | None = None
    outbound_text: str | None = None
    direction: str | None = None
    ts_ms: int | None = None

class UserDto(BaseModel):
    wa_id: str
    phone: str | None = None
    name: str | None = None
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
    country: str | None = None           
    country_iso: str | None = None       
    flag_url: str | None = None          
    only_if_empty: list[str] = [] 

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


class UsageDto(BaseModel):
    """Logged by n8n after each LLM call so token spend is measurable.
    Read prompt/completion/cached tokens straight from the OpenAI node's
    `usage` object (`$json.usage.prompt_tokens`, etc.)."""
    wa_id: str | None = None
    workflow: str | None = None
    node: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # cached_tokens = usage.prompt_tokens_details.cached_tokens (OpenAI)
    cached_tokens: int = 0


class RouteDto(BaseModel):
    """Ask the server whether this inbound message actually needs the
    expensive model. Lets n8n dedupe retries, short-circuit trivial turns
    with a cheap path, and enforce a per-conversation cool-off — all without
    spending a classifier token."""
    wa_id: str
    text: str = ""
    msg_id: str | None = None
    media_type: str | None = None