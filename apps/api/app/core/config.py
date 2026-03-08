from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_sync: str
    redis_url: str = "redis://redis:6379/0"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cors_origins: list[str] = ["http://localhost:3000"]
    waba_token: str = ""
    waba_phone_number_id: str = ""
    waba_api_version: str = "v21.0"
    n8n_api_secret: str = ""
    environment: str = "production"

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