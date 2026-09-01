"""운영자 앱 08(#66) e2e 전용 — 이의 큐·상세 화면이 필요로 하는 나머지 데이터.

`seed_e2e_operator_queues.seed_pending_appeal()`이 이미 「할 일」 홈의 건수
검증용 심판 대기 이의 하나를 만든다(#65). 이 명령은 그 함수가 이미 돌려주는 것
(submission_id·reason·dev_access — #66이 그쪽에 추가했다) 위에, 이 티켓만
필요로 하는 것 두 가지를 얹는다:

1. **소스에 심는 유일한 마커.** "소스가 기본으로 접혀 있다"(ADR-0022, "펼치기
   전 화면의 어디에도 소스 내용이 없다")를 e2e로 증명하려면 펼치기 전 화면
   전체에 그 마커가 없고, 펼친 뒤에만 있어야 한다 — 호출마다 다른 uuid를 섞어
   서로 다른 e2e 실행이 서로 다른 값을 보게 만든다(고정 문자열이면 다른 실행이
   이미 만든 값과 우연히 겹쳐 오탐할 수 있다).
2. **`--rule uphold|reject`.** "상태 필터로 인용·기각된 건도 볼 수 있다"와
   "이미 심판된 이의는 폼 없이 결과를 읽기 전용으로 보여준다"는 #66의 AC지만,
   심판 자체를 만드는 화면(#67)은 이 티켓이 만들지 않는다 — 그래서 심판이
   끝난 이의가 필요할 때는 이미 있는 운영자 API(`POST
   /operator/appeals/{id}/rule`)를 시드 단계에서 대신 불러 만든다.

Contest 발행·본인인증·제출·마감은 seed_e2e_operator_queues.py의 헬퍼를 그대로
쓴다 — 그 흐름은 이미 그 파일이 검증해 뒀고, 여기서 또 손으로 조립하면 그
검증이 갈라진다.

배포 환경에서는 돌지 않는다(seed_e2e_operator_queues.py의 다른 e2e 전용
명령들과 같은 이유 — 실제 Contest·Payment·Appeal·Operator 심판을 만든다).
"""

from __future__ import annotations

import json
import uuid

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.test import Client
from django.utils import timezone

from .seed_e2e_operator_queues import (
    DEADLINE_OFFSET,
    SCORING_RUN_PENDING_URL,
    _auth_header,
    _clear_stale_seed_contests,
    _close_contest,
    _internal_headers,
    _publish_contest,
    _refuse_in_deployed_environment,
    _submit,
    _verified_user,
)

OPERATOR_APPEALS_URL = "/api/operator/appeals"
OPERATOR_ORIGIN = "http://testserver"

# 이 명령이 심판에 쓰는 Operator는 고정된 이름으로 멱등하게 재사용한다(코드리뷰
# 지적 없이도 seed_e2e_operator.py가 이미 정한 관용구 — 매 호출마다 새 계정을
# 만들 필요가 없다).
RULER_USERNAME = "e2e-op-appeal-ruler"
RULER_PASSWORD = "e2e-op-appeal-ruler-pw-9134-xyz"


def _ruler_client() -> Client:
    call_command(
        "seed_e2e_operator",
        "--username",
        RULER_USERNAME,
        "--password",
        RULER_PASSWORD,
        "--superuser",
    )
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": RULER_USERNAME, "password": RULER_PASSWORD},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def seed_appeal_for_detail(*, rule: str | None) -> dict:
    client = Client()
    uid = uuid.uuid4().hex[:8]
    marker = f"e2e-source-marker-{uuid.uuid4().hex}"
    deadline = timezone.now() + DEADLINE_OFFSET
    sponsor, contest = _publish_contest(
        client,
        sponsor_uid=f"e2e-appealdetail-sponsor-{uid}",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, f"e2e-appealdetail-dev-{uid}")
    submission = _submit(
        client,
        dev,
        contest["id"],
        requirement_id=requirement_id,
        source_bytes=f"print('{marker}')\n".encode("utf-8"),
    )
    _close_contest(client, contest, deadline=deadline)

    scoring_resp = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
    assert scoring_resp.status_code == 200, scoring_resp.content

    # 이의 사유에 marker 를 넣으면 안 된다. 상세 화면은 사유를 정상적으로
    # 보여주므로, 사유에 marker 가 있으면 "펼치기 전 화면 어디에도 소스가
    # 없다"는 단언이 구현과 무관하게 **항상** 실패한다 — 픽스처가 자기
    # 테스트를 스스로 무너뜨린다. marker 는 오직 소스에만 있어야 그 단언이
    # 실제로 소스 누출을 묻는 질문이 된다.
    reason = f"e2e 상세 시드 — 요구사항이 실제로는 충족됐습니다. (case {uid})"
    appeal_resp = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": reason},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert appeal_resp.status_code == 201, appeal_resp.content
    appeal_id = appeal_resp.json()["id"]

    result: dict = {
        "appeal_id": appeal_id,
        "contest_id": contest["id"],
        "submission_id": submission["id"],
        "reason": reason,
        "dev_access": dev["access"],
        "source_marker": marker,
        "status": "pending",
        "ruling": None,
    }

    if rule is not None:
        ruler = _ruler_client()
        payload: dict[str, str | int] = {
            "decision": rule,
            "ruling_note": f"e2e 심판 시드 — {rule} 처리.",
        }
        if rule == "uphold":
            payload["correction_amount"] = 12345
        rule_resp = ruler.post(
            f"{OPERATOR_APPEALS_URL}/{appeal_id}/rule",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ORIGIN=OPERATOR_ORIGIN,
        )
        assert rule_resp.status_code == 200, rule_resp.content
        result["status"] = rule_resp.json()["status"]

        # 심판 응답(AppealOut)에는 ruled_by_username이 없다 — 그건 상세 응답
        # (AppealDetailOut.ruling, RulingOut)에만 있다. 손으로 재구성하지 않고
        # 상세를 다시 조회해 그대로 쓴다 — decision이 입력(uphold/reject)과
        # 출력(upheld/rejected)에서 어휘가 다른 것(#66이 발견한 함정) 같은 것을
        # 여기서 또 틀리지 않기 위해서다.
        detail_resp = ruler.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}")
        assert detail_resp.status_code == 200, detail_resp.content
        result["ruling"] = detail_resp.json()["ruling"]

    return result


class Command(BaseCommand):
    help = "운영자 앱 08(#66) 이의 큐·상세 e2e에 필요한 이의 하나를 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--rule",
            choices=["uphold", "reject"],
            default=None,
            help="지정하면 이의를 만든 뒤 그 결정으로 즉시 심판까지 마친다.",
        )

    def handle(self, *args, **options) -> None:
        _refuse_in_deployed_environment()
        # 이 명령도 자기 접두어(TITLE_PREFIX)의 Contest를 만든다 — 이번 실행이
        # 심지 않은 것을 먼저 정리한다(seed_e2e_operator_queues.py의
        # `_own_title_prefix` 설명 참고). #66이 이 명령을 새로 더하며 호출
        # 빈도가 크게 늘었으므로, 여기서도 같은 정리를 빠뜨리면 축적이 다시
        # 시작된다.
        _clear_stale_seed_contests()
        result = seed_appeal_for_detail(rule=options.get("rule"))
        # 명령이 마지막 줄에 JSON 한 덩어리만 찍는다 — 다른 seed_e2e_* 명령과 같은 관용구.
        self.stdout.write(json.dumps(result))
