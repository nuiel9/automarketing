from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.channels.registry import build_adapters
from app.config import get_settings
from app.db import get_session
from app.notify import line_notify
from app.publisher import run_tick

router = APIRouter()


@router.post("/internal/tick")
def tick(
    x_tick_token: str = Header(default=""),
    session: Session = Depends(get_session),
):
    settings = get_settings()
    if x_tick_token != settings.tick_token:
        raise HTTPException(401)
    return run_tick(
        session,
        build_adapters(settings),
        datetime.now(timezone.utc),
        notify=line_notify,
    )
