from fastapi import APIRouter, Response

from app.db.health import database_is_connected

api_router = APIRouter()


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
