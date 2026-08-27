from fastapi import APIRouter, Response

from app.api.attention import router as attention_router
from app.api.file_manager import router as file_manager_router
from app.api.summary import router as summary_router
from app.api.maintenance import router as maintenance_router
from app.db.health import database_is_connected
from app.version import APP_ID, APP_VERSION

api_router = APIRouter()
api_router.include_router(file_manager_router)
api_router.include_router(attention_router)
api_router.include_router(summary_router)
api_router.include_router(maintenance_router)


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


@api_router.get("/health/app")
def read_application_health(response: Response) -> dict[str, str]:
    connected = database_is_connected()
    if not connected:
        response.status_code = 503
    return {
        "status": "ok" if connected else "error",
        "app_id": APP_ID,
        "version": APP_VERSION,
    }
