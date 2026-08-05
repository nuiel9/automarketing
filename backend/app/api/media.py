from typing import BinaryIO, Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.media import get_store
from app.models import ContentItem

router = APIRouter()

CHUNK_SIZE = 1 << 20  # 1 MiB


def _iter_file(f: BinaryIO, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    """Yield fixed-size chunks from a binary file object, closing it when done.

    Letting StreamingResponse iterate a raw file object directly falls back to
    Python's default line iteration, which splits on 0x0A bytes -- unbounded
    chunk sizes for binary data with no newlines, or a storm of 1-byte chunks
    for data full of them -- and never closes the handle. Reading fixed-size
    chunks avoids both, and the `finally` guarantees the file is closed even if
    the client disconnects mid-stream.
    """
    try:
        while chunk := f.read(chunk_size):
            yield chunk
    finally:
        f.close()


@router.get("/media/{token}")
def serve_media(token: str, session: Session = Depends(get_session)):
    item = session.scalar(select(ContentItem).where(ContentItem.media_token == token))
    if item is None or not item.media_path:
        raise HTTPException(404)
    store = get_store(get_settings())
    return StreamingResponse(_iter_file(store.open(item.media_path)), media_type="video/mp4")
