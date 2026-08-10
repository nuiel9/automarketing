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

    # _env_file=None, matching the sibling test above: without it, a
    # developer with a real AIVDO_API_KEY (or an overridden poll timeout) in
    # backend/.env would fail this test on the class defaults it's meant to
    # check.
    s = Settings(_env_file=None)
    assert s.aivdo_base_url == "https://aivdo-api-b7iz53omoq-as.a.run.app"
    # blueprint is AIVDO's own template for "courses, education, B2B".
    assert s.aivdo_style == "blueprint"
    # Charon is the same Gemini TTS voice Phase 2 uses for Kavee, so ads
    # sound like the rest of the channel.
    assert s.aivdo_voice == "Charon"
    # Below the render Cloud Run job's --task-timeout=15m (900s) so poll()'s
    # own timeout error fires instead of the task being killed first.
    assert s.aivdo_poll_timeout == 600
    assert s.ad_shot_url == "https://eduverse.one/th"
    # The key is a secret; it must never carry a baked-in default.
    assert s.aivdo_api_key == ""


def test_frontend_origin_accepts_more_than_one_origin():
    # Cloud Run gives a service TWO hostnames -- a legacy short one and a
    # project-numbered one -- and the Cloud Console shows the second while
    # this deployment was configured with the first. Allowing only one origin
    # means browsing the other fails every request at preflight, which
    # presents to the operator as "my admin token doesn't work" (login only
    # writes localStorage, so it appears to succeed either way).
    s = Settings(_env_file=None, frontend_origin="https://a.example, https://b.example")
    assert s.origins() == ["https://a.example", "https://b.example"]


def test_a_single_frontend_origin_still_works():
    # The deployed config passes exactly one origin; parsing must not change
    # what that means.
    s = Settings(_env_file=None, frontend_origin="https://a.example")
    assert s.origins() == ["https://a.example"]


def test_motion_ad_is_a_renderable_format():
    from app.api.items import RENDERABLE_FORMATS
    from app.models import ContentItem

    assert "motion_ad" in RENDERABLE_FORMATS
    # Assert against the actual column, not a copy of its length as a
    # literal -- this must fail if content_items.format is ever narrowed
    # below what "motion_ad" needs, not just restate today's numbers.
    assert len("motion_ad") <= ContentItem.__table__.c.format.type.length
