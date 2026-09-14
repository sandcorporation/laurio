from ninja import NinjaAPI

from accounts.api import router as accounts_router
from accounts.operator_api import router as operator_router
from appeals.api import operator_router as appeals_operator_router
from appeals.api import router as appeals_router
from awards.api import router as awards_router
from classroom.api import router as classroom_router
from classroom.internal_api import router as classroom_internal_router
from classroom.template_api import router as classroom_template_router
from classroom.template_operator_api import operator_router as classroom_template_operator_router
from contests.api import router as contests_router
from contests.operator_api import operator_router as contests_operator_router
from contests.submission_api import router as submissions_router
from core.api import router as core_internal_router
from handovers.api import router as handovers_router
from ledger.api import router as ledger_router
from notifications.api import public_router as notifications_router
from notifications.api import router as notifications_internal_router
from payments.api import router as payments_router
from payouts.api import operator_router as payouts_operator_router
from payouts.api import router as payouts_router
from policies.api import operator_router as policies_operator_router
from scoring.api import router as scoring_internal_router
from storage.api import router as storage_router
from storage.policy import StorageAccessDenied
from verification.api import router as verification_router
from verification.operator_api import operator_router as verification_operator_router

api = NinjaAPI(title="Laurio API", version="0.1.0")

api.add_router("", accounts_router)
api.add_router("", verification_router)
api.add_router("", contests_router)
api.add_router("", payments_router)
api.add_router("", submissions_router)
api.add_router("", awards_router)
api.add_router("", handovers_router)
api.add_router("", payouts_router)
api.add_router("", appeals_router)
api.add_router("/notifications", notifications_router)
api.add_router("/ledger", ledger_router)
api.add_router("/classroom", classroom_router)
api.add_router("/classroom", classroom_template_router)


@api.get("/health")
def health(request):
    return {"status": "ok"}


api.add_router("/internal", core_internal_router)
api.add_router("/internal/notifications", notifications_internal_router)
api.add_router("/internal/scoring", scoring_internal_router)
api.add_router("/internal/classroom", classroom_internal_router)


@api.exception_handler(StorageAccessDenied)
def storage_access_denied(request, exc: StorageAccessDenied):
    return api.create_response(request, {"detail": str(exc)}, status=403)


# 운영자 표면(#43, ADR-0019). InternalAuth 와 다르다 — 저쪽은 Celery beat 가 부르는
# 자동 스캔 전용이고, 사람이 판단하는 행위는 전부 이 접두어 아래에서 신원과 함께
# 이루어진다. 라우터 자체가 기본 거부이며 Origin 검증 미들웨어가 경로 접두어로
# 걸려 있다.
api.add_router("/operator", operator_router)
api.add_router("/operator", appeals_operator_router)
api.add_router("/operator", payouts_operator_router)
api.add_router("/operator", policies_operator_router)
api.add_router("/operator", contests_operator_router)
api.add_router("/operator", verification_operator_router)
api.add_router("/operator", classroom_template_operator_router)

api.add_router("/storage", storage_router)
