from app.config import Settings


def test_video_factory_settings_defaults():
    # These strings must match eduverse-one's Kavee config — a silent drift
    # here would mean the marketing voice stops being the product voice.
    settings = Settings(_env_file=None)
    assert settings.tips_model == "gemini-3.6-flash"
    assert settings.tts_model == "gemini-3.1-flash-tts-preview"
    assert settings.kavee_voice == "Charon"
    assert settings.render_dispatcher == "cloudrun"
    assert settings.render_job_name == "automarketing-render"
    assert settings.render_job_region == "asia-southeast1"


def test_aivdo_settings_have_production_defaults():
    from app.config import Settings

    s = Settings()
    assert s.aivdo_base_url == "https://aivdo-api-b7iz53omoq-as.a.run.app"
    # blueprint is AIVDO's own template for "courses, education, B2B".
    assert s.aivdo_style == "blueprint"
    # Charon is the same Gemini TTS voice Phase 2 uses for Kavee, so ads
    # sound like the rest of the channel.
    assert s.aivdo_voice == "Charon"
    assert s.aivdo_poll_timeout == 900
    assert s.ad_shot_url == "https://eduverse.one/th"
    # The key is a secret; it must never carry a baked-in default.
    assert s.aivdo_api_key == ""


def test_motion_ad_is_a_renderable_format():
    from app.api.items import RENDERABLE_FORMATS

    assert "motion_ad" in RENDERABLE_FORMATS
    # 9 characters, and content_items.format is String(20) -- no migration.
    assert len("motion_ad") <= 20
