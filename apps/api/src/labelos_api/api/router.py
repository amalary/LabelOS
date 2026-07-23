from fastapi import APIRouter

from labelos_api.api.v1 import authorization_examples
from labelos_api.api.v1.artists import router as artists_router
from labelos_api.api.v1.me import router as me_router
from labelos_api.api.v1.onboarding import router as onboarding_router
from labelos_api.api.v1.status import router as status_router
from labelos_api.api.v1.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(artists_router)
api_router.include_router(authorization_examples.router)
api_router.include_router(me_router)
api_router.include_router(onboarding_router)
api_router.include_router(status_router)
api_router.include_router(webhooks_router)
