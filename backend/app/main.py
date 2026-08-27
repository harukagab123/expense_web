from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.health import database_is_connected
from app.version import APP_NAME, APP_VERSION

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Application started")
    if database_is_connected():
        logger.info("Database connection successful")
    else:
        logger.error("Database unavailable")

    yield

    logger.info("Application shutdown")


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
def read_root():
    index = settings.frontend_dist_dir / "index.html"
    if settings.app_env.lower() == "production" and index.is_file():
        return FileResponse(index)
    return {
        "name": APP_NAME,
        "status": "running",
    }


if settings.app_env.lower() == "production" and (settings.frontend_dist_dir / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist_dir / "assets"), name="frontend-assets")

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def serve_frontend(frontend_path: str):
        requested = (settings.frontend_dist_dir / frontend_path).resolve()
        try:
            requested.relative_to(settings.frontend_dist_dir.resolve())
        except ValueError:
            requested = Path("__not_allowed__")
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(settings.frontend_dist_dir / "index.html")
