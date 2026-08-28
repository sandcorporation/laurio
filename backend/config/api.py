from ninja import NinjaAPI

from ledger.api import router as ledger_router

api = NinjaAPI(title="Laurio API", version="0.1.0")

api.add_router("/ledger", ledger_router)


@api.get("/health")
def health(request):
    return {"status": "ok"}
