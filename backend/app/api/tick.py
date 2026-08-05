from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import require_tick_token
from app.channels.registry import build_adapters
from app.config import get_settings
from app.db import get_session
from app.notify import line_notify
from app.publisher import run_tick

router = APIRouter(dependencies=[Depends(require_tick_token)])


@router.post("/internal/tick")
def tick(session: Session = Depends(get_session)):
    settings = get_settings()
    return run_tick(
        session,
        build_adapters(settings),
        datetime.now(timezone.utc),
        notify=line_notify,
    )
