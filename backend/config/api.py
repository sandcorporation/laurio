from ninja import NinjaAPI

from core.api import router as core_internal_router

api = NinjaAPI(title="Laurio API", version="0.1.0")


@api.get("/health")
def health(request):
    return {"status": "ok"}


api.add_router("/internal", core_internal_router)
