from datetime import datetime, timezone

from app.models import Caption, ContentItem, Publication


def test_item_caption_publication_roundtrip(db):
    item = ContentItem(slug="w32-clip-tgat", topic="TGAT คณิต", status="idea")
    item.captions.append(Caption(channel="facebook", body="ทดสอบ", hashtags=["#TGAT"]))
    item.publications.append(
        Publication(channel="facebook", scheduled_at=datetime.now(timezone.utc))
    )
    db.add(item)
    db.commit()

    loaded = db.get(ContentItem, item.id)
    assert loaded.captions[0].hashtags == ["#TGAT"]
    assert loaded.publications[0].status == "pending"
    assert loaded.publications[0].attempts == 0


def test_item_carries_scenario_and_render_error(db):
    item = ContentItem(
        slug="w32-demo-tgat", topic="t", status="idea",
        format="demo", scenario="tgat-demo", render_error=None,
    )
    db.add(item)
    db.commit()
    loaded = db.get(ContentItem, item.id)
    assert loaded.format == "demo"
    assert loaded.scenario == "tgat-demo"
    assert loaded.render_error is None


def test_content_item_carries_an_aivdo_job_id(db):
    """Credits are deducted at dispatch and never refunded afterwards.

    If the render job dies mid-poll, the AIVDO job still completes and the 5
    credits are gone; the stuck-render sweep would re-dispatch and spend 5
    more. Persisting the id lets a retry resume polling instead.
    """
    from app.models import ContentItem

    item = ContentItem(slug="w32-ad", topic="หัวข้อ", status="rendering",
                       format="motion_ad", aivdo_job_id="abc123")
    db.add(item); db.commit(); db.refresh(item)

    assert item.aivdo_job_id == "abc123"


def test_aivdo_job_id_defaults_to_none(db):
    from app.models import ContentItem

    item = ContentItem(slug="w32-tips", topic="หัวข้อ", status="idea", format="tips")
    db.add(item); db.commit(); db.refresh(item)

    assert item.aivdo_job_id is None
