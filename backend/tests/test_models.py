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
