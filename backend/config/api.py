from ninja import NinjaAPI

from storage.api import router as storage_router
from storage.policy import StorageAccessDenied

api = NinjaAPI(title="Laurio API", version="0.1.0")


@api.get("/health")
def health(request):
    return {"status": "ok"}


@api.exception_handler(StorageAccessDenied)
def storage_access_denied(request, exc: StorageAccessDenied):
    return api.create_response(request, {"detail": str(exc)}, status=403)


api.add_router("/storage", storage_router)
