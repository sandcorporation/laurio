from ninja import NinjaAPI

from accounts.api import router as accounts_router
from contests.api import router as contests_router
from core.api import router as core_internal_router
from ledger.api import router as ledger_router
from notifications.api import router as notifications_internal_router
from payments.api import router as payments_router
from verification.api import router as verification_router

api = NinjaAPI(title="Laurio API", version="0.1.0")

api.add_router("", accounts_router)
api.add_router("", verification_router)
api.add_router("", contests_router)
api.add_router("", payments_router)
api.add_router("/ledger", ledger_router)


@api.get("/health")
def health(request):
    return {"status": "ok"}


api.add_router("/internal", core_internal_router)
api.add_router("/internal/notifications", notifications_internal_router)
