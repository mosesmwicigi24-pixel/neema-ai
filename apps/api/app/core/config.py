from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_sync: str
    redis_url: str = "redis://redis:6379/0"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    refresh_token_expire_days: int = 30
    cors_origins: list[str] = ["http://localhost:3000"]
    waba_token: str = ""
    waba_phone_number_id: str = ""
    waba_api_version: str = "v21.0"
    # Approved WhatsApp template used to open a thread with a customer who reached
    # us on Messenger/Facebook (Meta requires a template to message first). Body:
    # "Hello {{1}}, this is Bethany House…". Name + language must match the
    # approved template exactly.
    wa_invite_template: str = "whatsapp_invite"
    # WhatsApp voice calling: TURN/STUN for the browser softphone's WebRTC media.
    # The dashboard fetches these to build its RTCPeerConnection. coturn on our own
    # box supplies turn_url/username/credential; a public STUN is the always-on
    # fallback for same-network testing.
    turn_url: str = ""
    turn_username: str = ""
    turn_credential: str = ""
    stun_url: str = "stun:stun.l.google.com:19302"
    wa_invite_lang: str = "en"
    n8n_api_secret: str = ""
    # ── Meta Messenger / Instagram webhook (multichannel ingestion) ──────────
    # meta_verify_token: the arbitrary secret you also paste into the Meta app's
    #   webhook "Verify token" field — echoed back during the GET handshake.
    # meta_app_secret: the Meta App Secret, used to verify the X-Hub-Signature-256
    #   on inbound POSTs. If unset, signature verification is skipped (dev only).
    # The webhook is INERT until meta_verify_token is set.
    meta_verify_token: str = ""
    meta_app_secret: str = ""
    # Page access token used to SEND Messenger/Instagram replies via the Graph
    # Send API (/me/messages). Instagram DMs use the same token once the IG
    # account is linked to the Page. Unset → outbound Messenger/IG is disabled.
    meta_page_token: str = ""
    # Per-page tokens for multi-page setups (Bethany House + Bethany House
    # Executive): "pageid:token,pageid:token". A page listed here replies with
    # its own token; anything else falls back to meta_page_token. PSIDs are
    # page-scoped, so each contact belongs to exactly one page.
    meta_page_tokens: str = ""
    meta_graph_version: str = "v21.0"

    def page_token_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in (self.meta_page_tokens or "").split(","):
            pair = pair.strip()
            if ":" in pair:
                pid, tok = pair.split(":", 1)
                if pid.strip() and tok.strip():
                    out[pid.strip()] = tok.strip()
        return out
    # When true, the Tier-2 agent auto-answers inbound Messenger/IG DMs (same KES
    # hub catalogue as WhatsApp; checkout routed to WhatsApp). Default OFF so the
    # webhook stays ingestion-only until you flip it on. Needs meta_page_token set.
    meta_agent_reply: bool = False
    # Optional WhatsApp number the Messenger/IG agent invites buyers to for checkout.
    # WhatsApp webhook front door (Option A): our API becomes the Cloud API
    # callback and TRANSPARENTLY forwards every event to n8n (messaging keeps
    # working exactly as before), while tapping `calls` events for voice. Set
    # whatsapp_forward_url to n8n's current WhatsApp webhook URL. verify token
    # falls back to meta_verify_token if unset (must match the value pasted into
    # the Meta app's WhatsApp webhook config).
    whatsapp_forward_url: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_handoff_number: str = ""
    # Second official line (calls) — quoted verbatim in prompts alongside the above.
    whatsapp_handoff_alt: str = ""
    # ── Facebook/Instagram comment engagement (comment → public reply + DM) ──
    # When true, a NEW comment on a Page post/reel/ad fires BOTH a short public
    # acknowledgement AND a private reply that opens a Messenger DM (where Neema
    # sells 1:1). Needs meta_page_token + the pages_manage_engagement /
    # pages_messaging perms (App Review for beyond-tester reach). Default OFF.
    meta_comment_reply: bool = False
    # Comma-separated Page ID(s) WE own — used to skip our own comments/replies so
    # Neema never answers itself (infinite loop). Public replies are skipped when
    # this is unset, since we then can't tell our own comment from a customer's.
    meta_page_id: str = ""
    # Optional override for the public acknowledgement. `{name}` = commenter's
    # first name (blank if unknown). Kept short and price-free by design.
    meta_comment_public_text: str = ""
    # Max FULL agent-generated public comment replies per post before falling back
    # to a lighter (still warm, varied) reply — caps AI cost + Graph rate on a
    # viral post. Buying comments beyond this still get a friendly WhatsApp nudge.
    meta_comment_agent_cap: int = 30
    # ── Business facts Neema answers logistics/FAQ questions from ─────────────
    # Free text (location/branches, hours, delivery, payment, contacts) injected
    # into the system prompt. Without it Neema only knows the catalogue and can't
    # answer "where are you located?". Keep it short and factual.
    business_info: str = ""
    # Currency display gate: Kenya (+254) customers are quoted KES; everyone else
    # (and all Messenger/IG, which have no phone) is quoted USD = round(KES / rate).
    usd_kes_rate: int = 100
    environment: str = "production"
    openai_api_key: str = ""
    # Media file serving
    media_public_url: str = ""      # e.g. https://neema.bethanyhouse.co.ke
    media_storage_path: str = "/tmp/neema_media"
    # Bethany House hub — single source of truth for catalogue & orders
    hub_api_url: str = "https://hub.bethanyhouse.co.ke"
    hub_api_token: str = ""          # Sanctum token for pushing orders (Part B)
    hub_outlet_id: int = 0           # the online/WhatsApp outlet (Part B)
    catalog_source: str = "hub"      # "hub" | "local" (falls back to local on hub failure)
    hub_catalog_ttl: int = 600       # seconds to cache the hub catalogue
    hub_push_orders: bool = True     # push confirmed WhatsApp orders into the hub (Part B)
    hub_relay_receipt: bool = True   # WhatsApp the customer the receipt/payment link (Loop C)
    hub_order_status_ttl: int = 60   # seconds to cache a hub order's live status (Loop C)
    # ── Tier 2 agent (tool-calling; coexists with Tier 1 behind a flag) ──────
    anthropic_api_key: str = ""
    tier2_model: str = "claude-sonnet-5"
    tier2_model_light: str = "claude-haiku-4-5"  # cheap model for trivial turns (per-turn routing)
    tier2_model_routing: bool = True  # route trivial turns to tier2_model_light; False = always tier2_model
    tier2_enabled_wa_ids: str = ""   # comma-separated wa_ids routed to the Tier 2 agent
    tier2_all: bool = False          # route ALL traffic to Tier 2 (full cutover)
    tier2_max_iterations: int = 8    # max tool-call loops per turn (runaway guard)
    tier2_max_tokens: int = 1024
    tier2_prompt_cache: bool = True  # cache the system+tools+conversation prefix (~90% cheaper input)
    tier2_memory: bool = True        # cross-conversation customer memory (facts + past orders)
    tier2_vision: bool = True         # let the agent SEE product photos natively (Claude vision)

    def tier2_wa_ids(self) -> set[str]:
        return {w.strip() for w in self.tier2_enabled_wa_ids.split(",") if w.strip()}

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return ["http://localhost:3000"]
            if v.startswith("["):
                import json
                return json.loads(v)
            # comma-separated fallback: http://a.com,http://b.com
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

settings = Settings()