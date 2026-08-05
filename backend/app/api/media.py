from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.media import get_store
from app.models import ContentItem

router = APIRouter()


@router.get("/media/{token}")
def serve_media(token: str, session: Session = Depends(get_session)):
    item = session.scalar(select(ContentItem).where(ContentItem.media_token == token))
    if item is None or not item.media_path:
        raise HTTPException(404)
    store = get_store(get_settings())
    return StreamingResponse(store.open(item.media_path), media_type="video/mp4")
