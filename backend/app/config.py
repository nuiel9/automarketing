from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://automarketing:automarketing@localhost:5433/automarketing"
    admin_token: str = "dev-admin-token"
    tick_token: str = "dev-tick-token"
    public_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:3000"

    media_backend: str = "local"          # "local" | "gcs"
    media_root: str = "./media"           # local backend
    gcs_bucket: str = ""                  # gcs backend

    strategy_path: str = "./strategy.yaml"
    anthropic_api_key: str = ""

    enabled_channels: str = "dryrun"      # comma-separated: facebook,instagram,x,line,dryrun

    meta_page_id: str = ""
    meta_ig_user_id: str = ""
    meta_access_token: str = ""

    x_consumer_key: str = ""
    x_consumer_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""

    line_channel_access_token: str = ""
    line_founder_user_id: str = ""        # failure alerts go here

    def channels(self) -> list[str]:
        return [c.strip() for c in self.enabled_channels.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
