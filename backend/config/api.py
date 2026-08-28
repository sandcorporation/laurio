from ninja import NinjaAPI

api = NinjaAPI(title="Laurio API", version="0.1.0")


@api.get("/health")
def health(request):
    return {"status": "ok"}
