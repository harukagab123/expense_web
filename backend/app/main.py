from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.health import database_is_connected

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
    title="Personal Financial File Manager",
    version="0.1.0",
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
def read_root() -> dict[str, str]:
    return {
        "name": "Personal Financial File Manager",
        "status": "running",
    }
