from ninja import NinjaAPI

from accounts.api import router as accounts_router
from awards.api import router as awards_router
from contests.api import router as contests_router
from core.api import router as core_internal_router
from handovers.api import internal_router as handovers_internal_router
from handovers.api import router as handovers_router
from ledger.api import router as ledger_router
from notifications.api import router as notifications_internal_router
from payments.api import internal_router as payments_internal_router
from payments.api import router as payments_router
from payouts.api import router as payouts_router
from scoring.api import router as scoring_internal_router
from storage.api import router as storage_router
from storage.policy import StorageAccessDenied
from submissions.api import router as submissions_router
from verification.api import router as verification_router

api = NinjaAPI(title="Laurio API", version="0.1.0")

api.add_router("", accounts_router)
api.add_router("", verification_router)
api.add_router("", contests_router)
api.add_router("", payments_router)
api.add_router("", submissions_router)
api.add_router("", awards_router)
api.add_router("", handovers_router)
api.add_router("", payouts_router)
api.add_router("/ledger", ledger_router)


@api.get("/health")
def health(request):
    return {"status": "ok"}


api.add_router("/internal", core_internal_router)
api.add_router("/internal/notifications", notifications_internal_router)
api.add_router("/internal/scoring", scoring_internal_router)
api.add_router("/internal/handovers", handovers_internal_router)
api.add_router("/internal/payments", payments_internal_router)


@api.exception_handler(StorageAccessDenied)
def storage_access_denied(request, exc: StorageAccessDenied):
    return api.create_response(request, {"detail": str(exc)}, status=403)


api.add_router("/storage", storage_router)
