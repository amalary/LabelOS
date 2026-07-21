from fastapi import APIRouter

from labelos_api.api.v1.me import router as me_router
from labelos_api.api.v1.status import router as status_router

api_router = APIRouter()
api_router.include_router(me_router)
api_router.include_router(status_router)
