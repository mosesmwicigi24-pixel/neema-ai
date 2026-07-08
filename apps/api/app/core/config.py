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
    meta_graph_version: str = "v21.0"
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