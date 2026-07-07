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