from ninja import NinjaAPI

from accounts.api import router as accounts_router
from contests.api import router as contests_router
from ledger.api import router as ledger_router
from verification.api import router as verification_router

api = NinjaAPI(title="Laurio API", version="0.1.0")

api.add_router("", accounts_router)
api.add_router("", verification_router)
api.add_router("", contests_router)
api.add_router("/ledger", ledger_router)


@api.get("/health")
def health(request):
    return {"status": "ok"}
