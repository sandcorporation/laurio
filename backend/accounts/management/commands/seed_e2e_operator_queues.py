"""운영자 앱 07(#65) e2e 전용 — 「할 일」 세 큐에 각각 한 건씩 심는다.

「할 일」 홈은 세 가지를 센다: 심판 대기 이의(appeals?status=pending), 신원 대기
지급(payouts?blocked_on=identity), Seller 대기 지급(payouts?blocked_on=seller).
그 숫자가 맞는지 e2e로 확인하려면 실제로 그 상태에 있는 데이터가 있어야 하고,
그 상태들은 손으로 ORM 행을 조립해서는 안전하게 재현되지 않는다 — 원장 분개·
Escrow 해제·Seller 등록 같은 불변식이 서비스 계층 여러 곳에 걸쳐 있다
(ADR-0003·ADR-0004·ADR-0020). 그래서 `backend/tests/test_appeals.py`·
`backend/tests/test_payouts.py`가 이미 검증해 둔 것과 **같은 HTTP 흐름**을
`django.test.Client`(pytest 없이도 쓸 수 있는 일반 Django 유틸리티)로 그대로
반복한다 — appeals·payouts 앱의 소스를 고치지 않고, 이미 있는 공개 API만 부른다.

멱등하지 않다 — 부를 때마다 새 Contest·Submission·Appeal·Payout이 생긴다(부제·
UID에 타임스탬프를 섞어 충돌을 피한다). 그래서 이 명령을 쓰는 e2e 스펙은 절대
카운트를 고정값으로 단언하지 않고, "부르기 전 baseline 대비 정확히 1씩 늘었다"는
증분으로 검증해야 한다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from contextvars import ContextVar
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.utils import timezone

from awards.models import Award
from contests.models import Category, Contest, DeliverableType
from core.transitions import claim_transition
from policies.scope import current_policy

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
PAYOUTS_URL = "/api/payouts"
SCORING_RUN_PENDING_URL = "/api/internal/scans/submission-scoring"

# 이 명령이 심은 Contest 는 전부 이 접두어로 시작한다(코드리뷰 지적) — clear_queues()가
# "이 명령이 만든 것"만 골라 지우려면 다른 시드·실사용 데이터와 구별할 표식이
# 필요하다(frontend/e2e/lib/seed.ts, contests/management/commands/
# seed_e2e_contests.py의 title__startswith 관용구와 같은 원칙). 이 접두어는
# "가족 전체"(모든 실행이 심은 Contest)를 가리킨다 — clear_queues()는 실행을
# 가리지 않고 이 가족 전체에서 지우는 게 맞다(그 함수는 "큐를 0건으로" 만드는
# 것이 목적이라 실행 경계가 무관하다). 아래 `_own_title_prefix()`가 그 안에서
# "이번 실행이 심은 것"만 가리키는 더 좁은 접두어를 만든다.
TITLE_PREFIX = "[e2e-op-queue] "

# Contest를 발행할 때 쓰는 마감까지의 여유. **정렬 문제를 마감 값으로 풀지
# 않는다**(코드리뷰 지적) — 한때 이 값을 400일로 밀어 정렬 앞자리를 피해
# 보려 했는데, `_close_contest`가 그 마감을 근거로 시계를 얼리고 전역
# `/api/internal/tick`을 태우는 구조였던 탓에, "마감을 미래로 미룬다"가
# 곧 "그 시각까지의 전역 스캔 반경을 넓힌다"와 같은 말이 되어 DB의 모든
# PUBLISHED Contest를 CLOSED/JUDGING_ENDED로, 그 Submission들을 채점까지
# 끝내 버렸다(Score는 append-only라 되돌릴 수 없다) — 정렬 버그보다 훨씬
# 심각한 사고였다. `_close_contest`를 이 Contest 하나만 좁게 전이시키는
# 방식으로 고친 지금은(아래), 마감이 실시간 기준으로 아직 오지 않았어도
# 무관하다 — 그래서 원래 값(1시간)으로 되돌린다. 정렬 문제의 진짜 원인은
# 마감이 아니라 축적이었다 — `_own_title_prefix`·`_clear_stale_seed_contests`
# 참고.
DEADLINE_OFFSET = timedelta(hours=1)

# 이 명령들이 만드는 Contest는 지금까지 아무도 지우지 않아 스위트를 반복
# 실행할 때마다 쌓였다(코드리뷰 지적) — clear_queues()는 Appeal·Payout
# 행만 지우고 Contest는 그대로 둔다. 전부 prize=1,000,000이라 `?sort=prize`
# 정렬(`-prize, id`)에서 "[E2E] underfunded"(seed_e2e_contests.py, 매번
# 재생성돼 항상 최대 id → 동점 그룹 맨 뒤)를 계속 뒤로 밀어내다, 누적이
# 페이지 크기(20)를 넘으면 그 Contest가 1페이지 밖으로 나가 목록 e2e가
# 깨진다. #66이 이 명령들의 호출 빈도를 3배로 늘리면서 이 결함이 로컬에서
# 두 번만 돌려도 드러날 만큼 빨라졌다.
#
# **예전에는 벽시계 기준 1시간 컷오프(STALE_AFTER)로 "오래된 것"을
# 정리했는데, 그 기준이 정확히 "연속 두 번 실행"이라는 경우를 보존했다**
# (코드리뷰가 실제로 재현: 깨끗한 스택에서 스위트를 연달아 두 번 돌리면
# 1회차가 심은 Contest는 정의상 1시간이 안 지나 살아남고, 2회차 것과 합쳐
# 공개 목록 1페이지를 밀어냈다). 시간은 "이번 실행이 만든 것"과 "이전
# 실행이 남긴 것"을 구별하지 못한다 — 두 실행이 1시간 안에 겹치면 매번
# 똑같이 재현되는 결함이었다.
#
# 그래서 시간 대신 **실행 하나를 식별하는 토큰**을 쓴다.
# `LAURIO_E2E_RUN_ID`(frontend/e2e/global-setup.ts가 스위트 시작 시 한 번
# 발급해 모든 시드 호출에 실어 보낸다)를 Contest 제목에 새겨, "이번 실행이
# 심은 것"만 자기 것으로 인식한다 — 그 외의 가족-접두어 Contest는 전부
# (얼마나 오래됐든) 다른 실행이 남긴 것이므로 정리 대상이다. 같은 실행
# 안에서 여러 번 호출해도(다른 --only, 같은 테스트의 두 번째 시드) 서로의
# 형제를 지우지 않는다 — 토큰이 같기 때문이다. 이 명령이 프론트엔드
# 시드 헬퍼를 거치지 않고 손으로(또는 pytest에서) 불릴 때를 위해, 환경변수가
# 없으면 이 프로세스 안에서만 유효한 임의 토큰으로 대체한다 — 그 경우
# "실행"의 경계는 이 파이썬 프로세스의 수명이 된다.
_FALLBACK_RUN_ID = uuid.uuid4().hex[:8]


# 요청으로 받은 run id (#156). 시드를 HTTP 로 부르면 **부르는 쪽의 환경변수가 백엔드
# 프로세스에 있을 리 없다** — 서브프로세스를 띄우던 시절에는 환경변수가 곧 전달 수단이었다.
# ContextVar 인 것은 요청마다 갈려야 하기 때문이다(모듈 전역이면 동시 요청이 서로의 값을
# 덮는다).
_RUN_ID_OVERRIDE: ContextVar[str | None] = ContextVar("laurio_e2e_run_id", default=None)


def _run_id() -> str:
    return _RUN_ID_OVERRIDE.get() or os.environ.get("LAURIO_E2E_RUN_ID") or _FALLBACK_RUN_ID


def _own_title_prefix() -> str:
    """이번 실행이 심은 Contest에만 붙는, TITLE_PREFIX(가족 전체)보다 좁은
    접두어. `_clear_stale_seed_contests`가 "내 것"과 "다른 실행이 남긴 것"을
    가르는 유일한 기준이다."""

    return f"{TITLE_PREFIX}[{_run_id()}] "


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _login(client: Client, uid: str) -> dict:
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.test"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _verify(client: Client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"사람|1995-01-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _verified_user(client: Client, uid: str) -> dict:
    pair = _login(client, uid)
    _verify(client, pair["access"], ci=f"{uid}-ci")
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert me.status_code == 200, me.content
    return {"access": pair["access"], "user_id": me.json()["id"]}


def _sign_payment(*, webhook_id: str, order_id: str, status: str) -> str:
    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _clear_stale_seed_contests() -> int:
    """자기 가족-접두어(TITLE_PREFIX)의 Contest 중 **이번 실행이 심지 않은
    것**을 정리한다 — 위 `_own_title_prefix` 설명 참고. 나이가 아니라 실행
    토큰으로 가른다: `_own_title_prefix()`로 시작하지 않으면(=이번
    `LAURIO_E2E_RUN_ID`가 아니면) 얼마나 최근에 만들어졌든 다른 실행이 남긴
    것이므로 지운다. 삭제 범위는 항상 TITLE_PREFIX 가족으로만 좁힌다: 다른
    시드(seed_dev_data, seed_e2e_contests.py)나 실제 데이터, 그리고 이
    명령을 모르는 다른 체인의 e2e 데이터는 절대 건드리지 않는다 —
    clear_queues()가 이미 세운 것과 같은 안전 속성이다.

    **Award를 Contest보다 먼저 지운다.** `Award.submission`이 PROTECT라
    (awards/models.py — 감사 기록 보존) Contest를 바로 지우면
    `ProtectedError`가 난다. Award를 먼저 지우면 그 보호가 풀리고,
    Award -> Handover -> Payout -> TaxIdentity/PayoutWebhookDelivery는 전부
    CASCADE라 함께 정리된다.

    **감사 기록도 Contest보다 먼저 지운다.** `AppealRuling.appeal`과
    `SourceReading.appeal`/`.submission`은 PROTECT다(#72) — 예전에는 CASCADE라
    Contest 한 줄을 지우면 "누가 심판했는가"와 "누가 소스를 봤는가"가 통째로
    조용히 사라졌다. 이제는 지우려면 여기처럼 **명시적으로 한 줄을 써야 한다**.
    그 한 줄이 코드에 남는 것이 그 결정의 목적이므로, 편의를 위해 CASCADE로
    되돌리지 마라.

    지운 Contest 개수를 돌려준다 — `--prune-other-runs`(아래 Command)가 그
    수를 그대로 stdout에 찍어, globalSetup이 스위트 시작 전에 실제로 무언가를
    정리했는지 눈으로 확인할 수 있게 한다.
    """

    own_prefix = _own_title_prefix()
    stale_contest_ids = list(
        Contest.objects.filter(title__startswith=TITLE_PREFIX)
        .exclude(title__startswith=own_prefix)
        .values_list("id", flat=True)
    )
    if not stale_contest_ids:
        return 0

    from appeals.models import AppealRuling, SourceReading

    Award.objects.filter(contest_id__in=stale_contest_ids).delete()
    # 감사 기록 -> Appeal/Submission -> Contest 순서. PROTECT라 순서가 곧 조건이다.
    SourceReading.objects.filter(submission__contest_id__in=stale_contest_ids).delete()
    AppealRuling.objects.filter(appeal__submission__contest_id__in=stale_contest_ids).delete()
    Contest.objects.filter(id__in=stale_contest_ids).delete()
    return len(stale_contest_ids)


def _category() -> Category:
    category, _ = Category.objects.get_or_create(name="E2E 운영자 큐")
    return category


def _deliverable_type() -> DeliverableType:
    dtype, _ = DeliverableType.objects.get_or_create(
        name="E2E 운영자 큐용 웹서비스", defaults={"minimum_prize": 500_000}
    )
    return dtype


def _publish_contest(client: Client, *, sponsor_uid: str, deadline_at, requirements=None) -> tuple[dict, dict]:
    sponsor = _verified_user(client, sponsor_uid)
    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{_own_title_prefix()}{sponsor_uid}의 공모전",
            "category_id": _category().id,
            "deliverable_type_ids": [_deliverable_type().id],
            "prize": 1_000_000,
            "deadline_at": deadline_at.isoformat(),
            "requirements": requirements or [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert response.status_code == 200, response.content
    contest = response.json()

    payment_resp = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert payment_resp.status_code == 201, payment_resp.content
    payment = payment_resp.json()

    webhook_id = f"wh-{contest['id']}-{uuid.uuid4().hex}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign_payment(webhook_id=webhook_id, order_id=payment["order_id"], status="paid")
    webhook_resp = client.post(f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json")
    assert webhook_resp.status_code == 200, webhook_resp.content

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    contest = detail.json()
    assert contest["status"] == "published", contest
    return sponsor, contest


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(
    client: Client,
    dev: dict,
    contest_id: int,
    *,
    requirement_id: int | None = None,
    source_bytes: bytes = b"print('e2e queue seed')\n",
) -> dict:
    # source_bytes는 운영자 앱 08(#66)이 덧붙였다 — 이의 상세 e2e가 "소스가 아직
    # 안 왔다 → 펼치면 왔다"를 판정하려면 호출마다 다른 유일한 마커를 소스에 심을
    # 수 있어야 한다. 기본값은 그대로라 기존 호출부(seed_pending_appeal 등)는
    # 영향받지 않는다.
    from storage.adapters.fake import FakeStorageAdapter

    source_key = _source_object_key(contest_id, dev["user_id"])
    FakeStorageAdapter().write_object(source_key, source_bytes)

    responses = []
    if requirement_id is not None:
        responses.append({"requirement_id": requirement_id, "is_met": True, "evidence": []})

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={"source_object_key": source_key, "requirement_responses": responses},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _close_contest(client: Client, contest: dict, *, deadline) -> None:
    """이 Contest **하나만** PUBLISHED -> CLOSED로 좁게 전이시킨다.

    **예전에는 시계를 얼리고 `/api/internal/tick`(전역 스캔)을 태웠다** —
    코드리뷰에서 심각 결함으로 지적됐다: 그 틱은 DB의 **모든** PUBLISHED
    Contest를 스캔해 CLOSED로, 이어서 같은 틱이 JUDGING_ENDED로도 옮기고,
    곧바로 뒤에서 부르는 `scoring/run-pending`이 그 Submission들에
    append-only `Score`를 남긴다 — `seed_dev_data`가 만든 개발 데이터가
    e2e 한 번에 조용히 전부 채점 완료 상태가 될 수 있었다. 시계를 미래로
    얼릴수록 그 반경이 넓어지는 구조였다(예전 FAR_FUTURE_DEADLINE 실수가
    정확히 그 반경을 400일치로 넓혔다).

    지금은 `core.transitions.claim_transition` — 스케줄러 틱이 내부에서
    쓰는 것과 같은 원자적 빌딩 블록 — 을 이 Contest의 pk 하나에만 직접
    적용한다. 스캔이 없으니 다른 Contest는 손대지 않고, 시계를 얼릴
    필요도 없어 그 흔적을 되돌리는 코드(_unfreeze)도 함께 사라진다.
    `extra_fields`는 contests/apps.py에 등록된 실제 전이 규칙과 같은 계산
    (judging_ends_at = 이 Contest의 deadline_at + PlatformPolicy.judging_period_days,
    #78/ADR-0023)을 그대로 재현한다 — Award 엔드포인트가 이 값을 실시간과
    비교하므로(awards/api.py) 값 자체는 여전히 정확해야 한다.
    """

    ok = claim_transition(
        Contest,
        contest["id"],
        from_state=Contest.Status.PUBLISHED,
        to_state=Contest.Status.CLOSED,
        state_field="status",
        now=timezone.now(),
        extra_fields={
            "judging_ends_at": deadline
            + timedelta(days=current_policy().judging_period_days)
        },
    )
    assert ok, f"Contest {contest['id']} 를 PUBLISHED -> CLOSED 로 전이하지 못했다."


def seed_pending_appeal() -> dict:
    """채점까지 끝난 Submission에 이의를 하나 걸어둔다 — /operator/appeals?status=pending에서 보인다."""

    client = Client()
    uid = uuid.uuid4().hex[:8]
    deadline = timezone.now() + DEADLINE_OFFSET
    sponsor, contest = _publish_contest(
        client,
        sponsor_uid=f"e2e-appeal-sponsor-{uid}",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, f"e2e-appeal-dev-{uid}")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id)
    _close_contest(client, contest, deadline=deadline)

    scoring_resp = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
    assert scoring_resp.status_code == 200, scoring_resp.content

    reason = "e2e 큐 시드 — AI가 놓친 근거가 실제로 소스에 있습니다."
    appeal_resp = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": reason},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert appeal_resp.status_code == 201, appeal_resp.content
    # submission_id·reason·dev_access는 운영자 앱 08(#66)이 덧붙였다 — 이의 상세
    # 화면 e2e가 "제기 사유가 실제로 보이는가"와 "펼침이 Developer 쪽 열람 기록
    # (GET /submissions/{id}/source-readings)에 실제로 한 건을 남기는가"를
    # 검증하려면 이 값들이 필요하다. 기존 키(appeal_id·contest_id)는 그대로라
    # home.spec.ts 등 이미 이 함수를 쓰는 곳은 영향받지 않는다.
    return {
        "appeal_id": appeal_resp.json()["id"],
        "contest_id": contest["id"],
        "submission_id": submission["id"],
        "reason": reason,
        "dev_access": dev["access"],
    }


def _ready_for_payout(uid: str) -> tuple[Client, dict, dict, dict]:
    client = Client()
    deadline = timezone.now() + DEADLINE_OFFSET
    sponsor, contest = _publish_contest(client, sponsor_uid=f"e2e-payout-sponsor-{uid}", deadline_at=deadline)
    dev = _verified_user(client, f"e2e-payout-dev-{uid}")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    award_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert award_resp.status_code == 200, award_resp.content

    handover_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(sponsor["access"])
    )
    assert handover_resp.status_code == 200, handover_resp.content

    return client, sponsor, dev, contest


def _request_and_confirm_payout(client: Client, dev: dict, contest_id: int, *, seller_simulate: str | None) -> dict:
    requested = client.post(f"{CONTESTS_URL}/{contest_id}/payout", **_auth_header(dev["access"]))
    assert requested.status_code == 201, requested.content
    idempotency_key = requested.json()["idempotency_key"]

    body: dict = {}
    if seller_simulate is not None:
        body["seller_simulate"] = seller_simulate
    confirm_resp = client.post(
        f"{PAYOUTS_URL}/{idempotency_key}/confirm",
        data=body,
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert confirm_resp.status_code == 200, confirm_resp.content
    return confirm_resp.json()


def seed_identity_pending_payout() -> dict:
    """확정됐지만 신원(주민등록번호) 대기 — /operator/payouts?blocked_on=identity에서 보인다."""

    uid = uuid.uuid4().hex[:8]
    client, _sponsor, dev, contest = _ready_for_payout(uid)
    result = _request_and_confirm_payout(client, dev, contest["id"], seller_simulate=None)
    assert result["status"] == "confirmed_identity_pending", result
    return {"idempotency_key": result["idempotency_key"], "contest_id": contest["id"]}


def seed_seller_pending_payout() -> dict:
    """확정됐지만 Seller 등록 대기 — /operator/payouts?blocked_on=seller에서 보인다."""

    uid = uuid.uuid4().hex[:8]
    client, _sponsor, dev, contest = _ready_for_payout(uid)
    result = _request_and_confirm_payout(client, dev, contest["id"], seller_simulate="review_required")
    assert result["status"] == "confirmed_seller_pending", result
    return {"idempotency_key": result["idempotency_key"], "contest_id": contest["id"]}


def clear_queues() -> dict:
    """세 큐를 이 명령이 심은 데이터에 한해서만 빈 상태로 되돌린다 — "0건은
    0건이라고 명시적으로 말한다"는 인수조건(#65)을 e2e로 확인하려면 실제로 0인
    상태가 필요하다.

    **삭제 범위는 이 명령이 만든 Contest(TITLE_PREFIX)로만 좁힌다**(코드리뷰
    지적) — 애초의 "status가 pending/대기 상태인 건 전부"는 다른 시드나 실제
    운영 데이터까지 함께 지울 수 있는 너무 넓은 조건이었다. `manage.py
    seed_dev_data`가 만든 Appeal·Payout이나, 이 명령을 모르는 다른 체인의 e2e
    데이터는 절대 건드리지 않는다.

    Payout을 지우면 TaxIdentity·PayoutWebhookDelivery가 CASCADE로 함께 지워진다
    (payouts/models.py) — 원장 분개(journal_entry_id)는 FK가 아니라 그대로 남지만,
    이 명령이 만든 Contest·Payout에 한정된 삭제라 감사 기록 보존을 신경 쓸
    대상이 아니다.
    """
    from appeals.models import Appeal, SourceReading
    from payouts.models import Payout

    # 심판 대기(pending) Appeal 이라 AppealRuling 은 없지만, **SourceReading 은
    # 있을 수 있다** — 운영자가 심판하기 전에 소스를 펼쳐 보는 것이 정상 경로다.
    # `SourceReading.appeal` 이 PROTECT 이므로(#72) 먼저 지우지 않으면 여기서
    # ProtectedError 가 난다. 감사 기록을 지우는 일은 이렇게 눈에 보여야 한다.
    SourceReading.objects.filter(
        appeal__status="pending",
        appeal__submission__contest__title__startswith=TITLE_PREFIX,
    ).delete()
    appeals_deleted, _ = Appeal.objects.filter(
        status="pending", submission__contest__title__startswith=TITLE_PREFIX
    ).delete()
    payouts_deleted, _ = Payout.objects.filter(
        status__in=[Payout.Status.CONFIRMED_IDENTITY_PENDING, Payout.Status.CONFIRMED_SELLER_PENDING],
        handover__award__contest__title__startswith=TITLE_PREFIX,
    ).delete()
    return {"appeals_deleted": appeals_deleted, "payouts_deleted": payouts_deleted}


def _refuse_in_deployed_environment(command_name: str = "seed_e2e_operator_queues") -> None:
    # 이 명령은 실제 Contest·Payment·Payout을 만들고(--clear는 그것도 모자라
    # 지운다) 운영 이미지에 그대로 들어간다 — ADR-0019가 Django admin을 내린
    # 이유(행을 직접 편집·삭제할 수 있으면 감사 추적에 우회로가 남는다)가 여기도
    # 그대로 적용된다. dev·CI(IS_DEPLOYED_ENVIRONMENT가 아닌 곳)에서만 돈다 —
    # config/settings.py의 다른 배포 가드들과 같은 판정 기준이다.
    if settings.IS_DEPLOYED_ENVIRONMENT:
        raise CommandError(
            f"LAURIO_DEPLOYMENT_TARGET={settings.LAURIO_DEPLOYMENT_TARGET} 인데 "
            # **이름을 인자로 받는다.** 이 헬퍼는 세 명령이 함께 쓰는데, 메시지가
            # 자기 이름을 하드코딩하고 있어서 `prune_e2e_junk` 를 staging 에서 친
            # 사람에게 「seed_e2e_operator_queues 가 거부됐다」고 말했다 — HTTP
            # 입구(core/api.py)는 이 문자열을 그대로 422 본문으로 내보낸다.
            f"이 명령을 실행하려 했다 — {command_name} 는 e2e 전용이라 "
            "배포 환경에서 실행할 수 없다(실제 데이터를 만들거나 지운다)."
        )


class Command(BaseCommand):
    help = "운영자 앱 「할 일」 세 큐(심판 대기 이의·신원 대기 지급·Seller 대기 지급)에 한 건씩 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--only",
            choices=["appeal", "identity", "seller"],
            default=None,
            help="지정하면 그 하나만 심는다. 생략하면 셋 다 심는다.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="심지 않고 이 명령이 심은 데이터만 빈 상태로 되돌린다(다른 옵션과 함께 쓰지 않는다).",
        )
        parser.add_argument(
            "--run-id",
            default=None,
            help=(
                "이번 실행을 가리키는 토큰. 안 주면 예전처럼 LAURIO_E2E_RUN_ID 환경변수를 "
                "읽는다 — HTTP 로 부를 때는(#156) 부르는 쪽의 환경변수가 이 프로세스에 없으므로 "
                "이 인자로 실어 보낸다."
            ),
        )
        parser.add_argument(
            "--prune-other-runs",
            action="store_true",
            help=(
                "심지 않고 다른 실행(다른 LAURIO_E2E_RUN_ID)이 남긴 own-prefix "
                "Contest만 정리한다(다른 옵션과 함께 쓰지 않는다). frontend/e2e/"
                "global-setup.ts가 스위트 시작 시 딱 한 번 부른다 — 이 명령을 처음 "
                "실제로 부르는 시점(대개 operator 프로젝트의 첫 테스트)까지 기다리면, "
                "그전에 먼저 도는 public 프로젝트 테스트가 이전 실행이 남긴 Contest를 "
                "이미 관찰해 버린다(#70 코드리뷰가 실제로 재현)."
            ),
        )

    def handle(self, *args, **options) -> None:
        _refuse_in_deployed_environment("seed_e2e_operator_queues")

        run_id = options.get("run_id")
        token = _RUN_ID_OVERRIDE.set(run_id) if run_id else None
        try:
            self._handle(**options)
        finally:
            if token is not None:
                _RUN_ID_OVERRIDE.reset(token)

    def _handle(self, **options) -> None:

        if options.get("clear"):
            result = clear_queues()
            self.stdout.write(json.dumps(result))
            return

        if options.get("prune_other_runs"):
            pruned = _clear_stale_seed_contests()
            self.stdout.write(json.dumps({"pruned": pruned}))
            return

        # 심기 전에 자기 가족-접두어의, 이번 실행이 심지 않은 Contest부터
        # 정리한다(`_own_title_prefix` 설명 참고) — 축적이 공개 목록 정렬을
        # 오염시키는 근본 원인이었다. globalSetup이 스위트 시작 시 이미 한 번
        # 정리했더라도(위 --prune-other-runs), 이 실행 도중 다른 체인/프로세스가
        # 남긴 것까지 잡도록 매 호출마다 다시 돈다 — 멱등하고 비용도 작다.
        _clear_stale_seed_contests()

        only = options.get("only")
        result: dict = {}

        if only in (None, "appeal"):
            result["appeal"] = seed_pending_appeal()
        if only in (None, "identity"):
            result["identity_pending_payout"] = seed_identity_pending_payout()
        if only in (None, "seller"):
            result["seller_pending_payout"] = seed_seller_pending_payout()

        # 명령이 마지막 줄에 JSON 한 덩어리만 찍는다 — 다른 seed_e2e_* 명령과 같은 관용구.
        self.stdout.write(json.dumps(result))
