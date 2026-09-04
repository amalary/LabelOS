from fastapi import APIRouter

from labelos_api.api.v1 import authorization_examples
from labelos_api.api.v1.analytics import router as analytics_router
from labelos_api.api.v1.approvals import router as approvals_router
from labelos_api.api.v1.artist_profiles import router as artist_profiles_router
from labelos_api.api.v1.artists import router as artists_router
from labelos_api.api.v1.campaigns import router as campaigns_router
from labelos_api.api.v1.dashboard import router as dashboard_router
from labelos_api.api.v1.marketing_content import router as marketing_content_router
from labelos_api.api.v1.me import router as me_router
from labelos_api.api.v1.onboarding import router as onboarding_router
from labelos_api.api.v1.organizations import router as organizations_router
from labelos_api.api.v1.profiles import router as profiles_router
from labelos_api.api.v1.realtime import router as realtime_router
from labelos_api.api.v1.status import router as status_router
from labelos_api.api.v1.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(analytics_router)
api_router.include_router(approvals_router)
api_router.include_router(artist_profiles_router)
api_router.include_router(artists_router)
api_router.include_router(authorization_examples.router)
api_router.include_router(campaigns_router)
api_router.include_router(dashboard_router)
api_router.include_router(marketing_content_router)
api_router.include_router(me_router)
api_router.include_router(onboarding_router)
api_router.include_router(organizations_router)
api_router.include_router(profiles_router)
api_router.include_router(realtime_router)
api_router.include_router(status_router)
api_router.include_router(webhooks_router)
