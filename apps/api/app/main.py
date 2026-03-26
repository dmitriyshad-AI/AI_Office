from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.director_heartbeat import director_heartbeat_service
from app.routers.projects import router as project_router


settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    director_heartbeat_service.start()
    try:
        yield
    finally:
        director_heartbeat_service.stop()


app = FastAPI(
    title="AI Office API",
    version="0.1.0",
    summary="API for the local Virtual AI Office",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(project_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "service": "ai-office-api",
        "version": "0.1.0",
        "status": "ok",
    }


@app.get("/health")
def healthcheck() -> dict[str, object]:
    auth_enabled = bool(settings.api_key or settings.api_keys)
    return {
        "status": "ok",
        "service": "api",
        "auth_mode": "api_key" if auth_enabled else "disabled",
        "director_heartbeat": {
            "enabled": settings.director_heartbeat_enabled,
            "auto_run_enabled": settings.director_auto_run_enabled,
            "poll_seconds": settings.director_heartbeat_poll_seconds,
            "max_dispatch_per_tick": settings.director_heartbeat_max_dispatch_per_tick,
            "stale_run_grace_seconds": settings.director_stale_run_grace_seconds,
            "stale_run_auto_retry_window_seconds": (
                settings.director_stale_run_auto_retry_window_seconds
            ),
            "running": director_heartbeat_service.is_running(),
        },
    }
