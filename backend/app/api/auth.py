from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

_scheme = HTTPBearer(auto_error=False)


def require_admin(cred: HTTPAuthorizationCredentials | None = Depends(_scheme)) -> None:
    if cred is None or cred.credentials != get_settings().admin_token:
        raise HTTPException(401, "invalid admin token")


def require_tick_token(x_tick_token: str = Header(default="")) -> None:
    if x_tick_token != get_settings().tick_token:
        raise HTTPException(401, "invalid tick token")
