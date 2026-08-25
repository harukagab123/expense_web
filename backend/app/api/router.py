from fastapi import APIRouter, Response

from app.api.attention import router as attention_router
from app.api.file_manager import router as file_manager_router
from app.db.health import database_is_connected

api_router = APIRouter()
api_router.include_router(file_manager_router)
api_router.include_router(attention_router)


@api_router.get("/health")
def read_health(response: Response) -> dict[str, str]:
    if database_is_connected():
        return {"status": "ok", "database": "connected"}

    response.status_code = 503
    return {"status": "error", "database": "unavailable"}


@api_router.get("/health/db")
def read_database_health(response: Response) -> dict[str, str]:
    if database_is_connected():
        return {"status": "ok", "database": "connected"}

    response.status_code = 503
    return {"status": "error", "database": "unavailable"}
