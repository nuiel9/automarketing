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
