from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.items import router as items_router
from app.api.media import router as media_router
from app.api.tick import router as tick_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AutoMarketing")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(media_router)
    app.include_router(items_router)
    app.include_router(tick_router)

    return app


app = create_app()
