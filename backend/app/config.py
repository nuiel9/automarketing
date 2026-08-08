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
    caption_provider: str = "gemini"      # "gemini" | "anthropic"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    tips_model: str = "gemini-3.6-flash"
    tts_model: str = "gemini-3.1-flash-tts-preview"
    kavee_voice: str = "Charon"

    render_dispatcher: str = "cloudrun"     # "cloudrun" | "local"
    gcp_project: str = ""
    render_job_name: str = "automarketing-render"
    render_job_region: str = "asia-southeast1"

    demo_email: str = ""
    demo_password: str = ""
    anthropic_api_key: str = ""

    # --- Motion Ad (AIVDO) ---
    aivdo_api_key: str = ""
    aivdo_base_url: str = "https://aivdo-api-b7iz53omoq-as.a.run.app"
    # AIVDO's own template for "courses, education, B2B -- structured,
    # technical, clean grid". It frames the photo in an 840x820 window with
    # the ad copy drawn OUTSIDE it, which is why the screenshot is square.
    aivdo_style: str = "blueprint"
    # Same Gemini TTS voice Phase 2 uses for Kavee, and present in AIVDO's
    # own VOICE_REGISTRY as male/Informative -- so ads sound like the channel.
    aivdo_voice: str = "Charon"
    # Seconds. A healthy render takes ~2 minutes; this is the ceiling before
    # we give up and fail the item.
    aivdo_poll_timeout: int = 900
    # Public page screenshotted for the ad photo. Deliberately a page that
    # needs no login, so this path never touches the demo account.
    ad_shot_url: str = "https://eduverse.one/th"

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
