"""강의실 백엔드 테스트가 공용으로 쓰는 시나리오 빌더 (#433).

강의실 테스트 52파일이 로그인·클래스·채점 키·열린 문제·가입·제출·채점 스캔이라는
같은 준비 과정을 파일마다 조금씩 다르게 복사해 왔다. 이 모듈이 그 준비를 한 곳에
모은다 — 뒤에 오는 티켓(채점 대기 사유 통합, 통과 규칙, 보관, 상태 전이, 필드 표)이
새로 쓰는 테스트는 여기 위에 선다.

**모든 준비는 마운트된 HTTP API 로만 이뤄진다**(CLAUDE.md 「HTTP가 유일한 시임이다」) —
ORM 으로 상태를 직접 만들지 않는다. 예산 소진처럼 정상 경로로는 만들 수 없는 상태나,
거부 시각처럼 벤더만 남기는 값은 이 모듈의 책임이 아니다 — 그런 준비는 각 테스트가
`Class.objects.filter(...).update(...)` 같은 직접 조작으로 여전히 한다(스펙 #432
「Testing Decisions」).

벤더 응답을 흉내 내는 함수들(`respond_with_*`)만 예외다 — `core.llm_scoring.
requests.post`는 강의실 밖(OpenAI)이라 HTTP 로 칠 수 없는 경계이고, 지금도 모든
강의실 채점 테스트가 이 자리를 monkeypatch 해 왔다.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings

from storage.adapters.fake import FakeStorageAdapter

CLASSES_URL = "/api/classroom/classes"
JOIN_URL = "/api/classroom/join"
CO_INSTRUCTOR_INVITES_URL = "/api/classroom/co-instructor-invites"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"

#: 벤더 응답 분기 자체를 검증하는 파일이 강제로 켜는 실물 어댑터(#340,
#: ADR-0043) — 기본값(fake)은 `FakeClassroomScoringAdapter`다.
REAL_SCORING_ADAPTER = "core.llm_scoring.OpenAIScoringAdapter"

DEFAULT_OPENAI_MODEL_VERSION = "gpt-4o-mini-2024-07-18"


# --- 로그인 ------------------------------------------------------------------


def internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def login(client, uid: str = "instructor-1", *, email: str | None = None) -> dict:
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def user_id(uid: str) -> int:
    """`login(client, uid=...)`으로 만든 계정의 내부 id. ORM 조회지만 준비가
    아니라 이미 HTTP 로 만든 계정을 가리키기 위한 조회라 위 규율 밖이다 — 소스
    업로드 object_key 조립처럼 다른 준비 함수의 인자로만 쓴다."""

    return get_user_model().objects.get(username=f"kakao:{uid}").id


# --- 클래스 --------------------------------------------------------------


def create_class(
    client,
    access: str,
    *,
    name: str = "웹 스터디",
    with_key: bool = True,
    key: str = "sk-test-instructor-key",
) -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    class_id = response.json()["id"]
    if with_key:
        set_key(client, access, class_id, key)
    return class_id


def set_key(client, access: str, class_id: int, key: str = "sk-test-instructor-key") -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": key},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content


def get_class(client, access: str, class_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def patch_class(client, access: str, class_id: int, payload: dict) -> dict:
    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data=payload,
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content
    return response.json()


def archive_class(client, access: str, class_id: int) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/archive",
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content
    return response.json()


def unarchive_class(client, access: str, class_id: int) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/unarchive",
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content
    return response.json()


def join_code(client, access: str, class_id: int) -> str:
    return get_class(client, access, class_id)["join_code"]


def join(client, access: str, code: str, *, display_name: str = "참여자") -> None:
    response = client.post(
        f"{JOIN_URL}/{code}",
        data={"display_name": display_name},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content


def join_class(
    client, access: str, class_id: int, *, instructor_access: str, display_name: str = "참여자"
) -> None:
    """가장 흔한 모양 — 강사 접근 토큰으로 참가 코드를 읽어 그대로 참여한다."""

    join(client, access, join_code(client, instructor_access, class_id), display_name=display_name)


# --- 공동 강사 (#561) ------------------------------------------------------


def create_co_instructor_invite(client, access: str, class_id: int) -> dict:
    """강사(소유자 또는 공동 강사)가 초대 하나를 만든다 — `token`·`expires_at` 이 든다."""

    response = client.post(
        f"{CLASSES_URL}/{class_id}/co-instructor-invites",
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def preview_co_instructor_invite(client, token: str, access: str | None = None):
    """초대 미리보기 응답 그대로 — 로그인하지 않은 방문자는 `access=None`."""

    headers = auth_header(access) if access else {}
    return client.get(f"{CO_INSTRUCTOR_INVITES_URL}/{token}", **headers)


def accept_co_instructor_invite(client, access: str, token: str, *, display_name: str = "공동 강사"):
    """수락 응답 그대로 — 거절(404·409·410)을 보는 테스트가 상태 코드를 직접 본다."""

    return client.post(
        f"{CO_INSTRUCTOR_INVITES_URL}/{token}/accept",
        data={"display_name": display_name},
        content_type="application/json",
        **auth_header(access),
    )


def add_co_instructor(
    client, owner_access: str, class_id: int, co_access: str, *, display_name: str = "공동 강사"
) -> None:
    """가장 흔한 모양 — 소유자가 초대를 만들고 그 사람이 곧장 수락한다."""

    token = create_co_instructor_invite(client, owner_access, class_id)["token"]
    response = accept_co_instructor_invite(client, co_access, token, display_name=display_name)
    assert response.status_code == 200, response.content


def list_instructors(client, access: str, class_id: int) -> list:
    """클래스 관리 「강사」 영역의 강사 목록 — 소유자 먼저, 그다음 공동 강사를 수락한 순서로."""

    response = client.get(f"{CLASSES_URL}/{class_id}/instructors", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def list_pending_co_instructor_invites(client, access: str, class_id: int) -> list:
    """아직 쓰이지 않은 공동 강사 초대 목록 — 수락·만료·취소된 것은 빠진다."""

    response = client.get(f"{CLASSES_URL}/{class_id}/co-instructor-invites", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def cancel_co_instructor_invite(client, access: str, class_id: int, invite_id: int):
    """취소 응답 그대로 — 거절(404·409)을 보는 테스트가 상태 코드를 직접 본다."""

    return client.post(
        f"{CLASSES_URL}/{class_id}/co-instructor-invites/{invite_id}/cancel",
        content_type="application/json",
        **auth_header(access),
    )


def leave_class(client, access: str, class_id: int):
    """공동 강사가 스스로 떠난다(#563) — 응답 그대로, 거절(소유자의 409)을 보는 테스트가 본다."""

    return client.post(
        f"{CLASSES_URL}/{class_id}/instructors/me/leave",
        content_type="application/json",
        **auth_header(access),
    )


def remove_co_instructor(client, access: str, class_id: int, co_instructor_id: int):
    """소유자가 공동 강사를 내보낸다(#563) — 응답 그대로. `co_instructor_id` 는 강사 목록 줄의 `id`."""

    return client.post(
        f"{CLASSES_URL}/{class_id}/co-instructors/{co_instructor_id}/remove",
        content_type="application/json",
        **auth_header(access),
    )


def rename_my_instructor_name(client, access: str, class_id: int, display_name: str):
    """강사 한 사람이 이 클래스에서 불릴 **자기** 강사 이름을 바꾼다(#565) — 응답 그대로."""

    return client.patch(
        f"{CLASSES_URL}/{class_id}/instructors/me",
        data={"display_name": display_name},
        content_type="application/json",
        **auth_header(access),
    )


def join_preview(client, code: str, access: str | None = None) -> dict:
    """가입 링크 미리보기 — 로그인하지 않은 방문자는 `access=None`."""

    headers = auth_header(access) if access else {}
    response = client.get(f"/api/classroom/join/{code}", **headers)
    assert response.status_code == 200, response.content
    return response.json()


# --- 소유권 이전 (#564) ----------------------------------------------------


def co_instructor_id_of(client, access: str, class_id: int, display_name: str) -> int:
    """강사 목록에서 그 이름의 공동 강사 줄 id — 이전 요청·내보내기가 받는 사람을 이것으로 고른다."""

    rows = [
        r for r in list_instructors(client, access, class_id)
        if r["role"] == "co_instructor" and r["display_name"] == display_name
    ]
    assert len(rows) == 1, rows
    return rows[0]["co_instructor_id"]


def request_ownership_transfer(client, access: str, class_id: int, co_instructor_id: int):
    """소유자가 공동 강사 한 사람에게 이전을 요청한다 — 응답 그대로(거절을 보는 테스트가 본다)."""

    return client.post(
        f"{CLASSES_URL}/{class_id}/ownership-transfers",
        data={"co_instructor_id": co_instructor_id},
        content_type="application/json",
        **auth_header(access),
    )


def _transfer_action(client, access: str, class_id: int, transfer_id: int, action: str):
    return client.post(
        f"{CLASSES_URL}/{class_id}/ownership-transfers/{transfer_id}/{action}",
        content_type="application/json",
        **auth_header(access),
    )


def accept_ownership_transfer(client, access: str, class_id: int, transfer_id: int):
    return _transfer_action(client, access, class_id, transfer_id, "accept")


def decline_ownership_transfer(client, access: str, class_id: int, transfer_id: int):
    return _transfer_action(client, access, class_id, transfer_id, "decline")


def cancel_ownership_transfer(client, access: str, class_id: int, transfer_id: int):
    return _transfer_action(client, access, class_id, transfer_id, "cancel")


def pending_ownership_transfer(client, access: str, class_id: int) -> dict | None:
    """클래스 화면이 보는 대기 중 이전 요청 — 없으면 `None`."""

    return get_class(client, access, class_id)["pending_ownership_transfer"]


def transfer_ownership(
    client, owner_access: str, class_id: int, recipient_access: str, *, recipient_name: str = "공동 강사"
) -> None:
    """가장 흔한 모양 — 소유자가 요청하고 받는 공동 강사가 곧장 수락한다."""

    co_id = co_instructor_id_of(client, owner_access, class_id, recipient_name)
    requested = request_ownership_transfer(client, owner_access, class_id, co_id)
    assert requested.status_code == 201, requested.content
    accepted = accept_ownership_transfer(client, recipient_access, class_id, requested.json()["id"])
    assert accepted.status_code == 200, accepted.content


def list_taught_classes(client, access: str) -> list:
    """강사 화면의 「내 클래스」(소유한 것과 공동 강사인 것)."""

    response = client.get(CLASSES_URL, **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


# --- 문제 --------------------------------------------------------------


@dataclass
class OpenProblem:
    id: int
    class_id: int
    item_ids: list[int] = field(default_factory=list)

    @property
    def item_id(self) -> int | None:
        """가장 흔한 경우 — 필수 항목이 하나뿐일 때 그 id."""

        return self.item_ids[0] if self.item_ids else None


def add_checklist_item(
    client, access: str, class_id: int, problem_id: int, label: str, *, required: bool = True
) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": label, "required": required},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


def open_problem(client, access: str, class_id: int, problem_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content


def create_open_problem(
    client,
    access: str,
    class_id: int,
    *,
    title: str = "1주차",
    submission_formats: list[str] | None = None,
    model: str = "",
    reasoning_effort: str = "",
    model_is_reasoning: bool = False,
    required_labels: list[str] | None = None,
    optional_labels: list[str] | None = None,
    syntax_check_enabled: bool = True,
    open: bool = True,
) -> OpenProblem:
    """만들기 → 필수·선택 체크리스트 채우기 → (기본) 열기까지 한 번에.

    기본값은 지금까지 파일마다 복사돼 있던 모양 그대로다 — 제출 형식
    `repository`, 필수 항목 하나("테스트가 있다")."""

    submission_formats = submission_formats if submission_formats is not None else ["repository"]
    required_labels = required_labels if required_labels is not None else ["테스트가 있다"]
    optional_labels = optional_labels or []

    payload: dict = {
        "title": title,
        "submission_formats": submission_formats,
        "syntax_check_enabled": syntax_check_enabled,
    }
    if model:
        payload["model"] = model
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if model_is_reasoning:
        payload["model_is_reasoning"] = True

    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data=payload,
        content_type="application/json",
        **auth_header(access),
    )
    assert created.status_code == 201, created.content
    problem_id = created.json()["id"]

    item_ids = [
        add_checklist_item(client, access, class_id, problem_id, label, required=True)
        for label in required_labels
    ] + [
        add_checklist_item(client, access, class_id, problem_id, label, required=False)
        for label in optional_labels
    ]

    if open:
        open_problem(client, access, class_id, problem_id)

    return OpenProblem(id=problem_id, class_id=class_id, item_ids=item_ids)


# --- 제출 --------------------------------------------------------------


def zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def submit_repository(
    client, access: str, class_id: int, problem_id: int, url: str = "https://github.com/octocat/hello-world"
) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": url, "submission_format": "repository"},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def submit_source(
    client,
    access: str,
    class_id: int,
    problem_id: int,
    *,
    participant_user_id: int,
    files: dict[str, str] | None = None,
    raw_bytes: bytes = b"",
    write_to_storage: bool = True,
) -> dict:
    """소스 제출. `write_to_storage=False`는 업로드가 아직 도착하지 않은 상황을
    흉내 낸다(`source_not_ready`) — object_key 는 만들되 오브젝트를 쓰지 않는다."""

    object_key = f"classroom-submission:{problem_id}:{participant_user_id}:source/{uuid.uuid4().hex}"
    if write_to_storage:
        payload = zip_bytes(files) if files is not None else raw_bytes
        FakeStorageAdapter().write_object(object_key, payload)

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": object_key, "content_type": "application/zip", "submission_format": "source"},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def mine(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def my_problems(client, access: str, class_id: int) -> dict:
    """참여자의 문제 목록(#288) — 문제 하나의 제출 목록(`mine`)과 다른
    엔드포인트다(`/problems/mine` vs `/problems/{id}/mine`)."""

    response = client.get(f"{CLASSES_URL}/{class_id}/problems/mine", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def list_problems(client, access: str, class_id: int) -> list:
    response = client.get(f"{CLASSES_URL}/{class_id}/problems", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def instructor_submissions(client, access: str, class_id: int, problem_id: int) -> list:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions", **auth_header(access)
    )
    assert response.status_code == 200, response.content
    return response.json()


def roster_grid(client, access: str, class_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/roster-grid", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


# --- 채점 스캔 ------------------------------------------------------------


def run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


@contextmanager
def force_real_scoring_adapter():
    """벤더 HTTP 분기 자체(상태 코드·응답 모양별 처리)를 검증하는 파일이 쓴다 —
    기본값(fake)은 `core.llm_scoring.requests`를 아예 건드리지 않는다."""

    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE=REAL_SCORING_ADAPTER):
        yield


# --- 벤더 응답 흉내 --------------------------------------------------------
#
# `core.llm_scoring.requests.post`는 강의실 밖(OpenAI)이라 HTTP 로 칠 수 없는
# 경계다 — 실물 채점 어댑터를 강제한 테스트가 이 자리를 monkeypatch 해 그
# 경계 너머의 응답을 고른다.


class FakeVendorResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def openai_verdicts_body(
    verdicts: list[dict], *, model: str = DEFAULT_OPENAI_MODEL_VERSION, total_tokens: int = 0
) -> dict:
    """`verdicts`는 벤더 응답 그대로의 모양
    (`[{"requirement_id": ..., "is_met": ..., "reasoning": ...}, ...]`) —
    체크리스트 항목이 여럿인 시도를 한 번에 채점하는 테스트가 쓴다.
    `total_tokens`는 채점 예산(#295)을 확인하는 테스트가 쓴다 — 기본값 0은
    "이 응답은 사용량을 보고하지 않았다"는 뜻이라 예산에 더해지지 않는다."""

    body: dict = {
        "model": model,
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps({"verdicts": verdicts})}}
        ],
    }
    if total_tokens:
        body["usage"] = {
            "prompt_tokens": total_tokens,
            "completion_tokens": 0,
            "total_tokens": total_tokens,
        }
    return body


def openai_success_body(
    item_id: int,
    *,
    is_met: bool = True,
    reasoning: str = "판정 근거",
    model: str = DEFAULT_OPENAI_MODEL_VERSION,
    total_tokens: int = 0,
) -> dict:
    return openai_verdicts_body(
        [{"requirement_id": item_id, "is_met": is_met, "reasoning": reasoning}],
        model=model,
        total_tokens=total_tokens,
    )


def respond_with_verdicts(
    client_monkeypatch,
    verdicts: list[dict],
    *,
    model: str = DEFAULT_OPENAI_MODEL_VERSION,
    total_tokens: int = 0,
    capture: list | None = None,
    capture_call: list | None = None,
) -> None:
    """다음 스캔에서 체크리스트 항목마다 주어진 판정을 그대로 돌려주는 성공
    응답을 흉내 낸다(`respond_with_verdict`의 다항목 판). `capture`를 주면
    벤더로 나간 요청 본문(`json`)만 그 목록에 쌓는다(프롬프트 내용을 확인하는
    테스트용). `capture_call`을 주면 `requests.post`에 실제로 건 인자
    전체(`headers`·`json`·`timeout`)를 쌓는다 — 타임아웃·헤더처럼 본문 밖의
    것을 확인하는 테스트용(#469, `capture`와 동시에 줄 수 있다)."""

    body = openai_verdicts_body(verdicts, model=model, total_tokens=total_tokens)

    def _handler(*args, **kwargs):
        if capture is not None:
            capture.append(kwargs["json"])
        if capture_call is not None:
            capture_call.append(kwargs)
        return FakeVendorResponse(200, body)

    client_monkeypatch.setattr("core.llm_scoring.requests.post", _handler)


def respond_with_verdict(
    client_monkeypatch,
    item_id: int,
    *,
    is_met: bool = True,
    total_tokens: int = 0,
    capture: list | None = None,
    capture_call: list | None = None,
) -> None:
    """다음 스캔에서 그 항목을 통과(`is_met=True`)·미달로 판정하는 성공 응답을
    흉내 낸다. `capture`를 주면 벤더로 나간 요청 본문을 그 목록에 쌓는다(프롬프트
    내용을 확인하는 테스트용)."""

    respond_with_verdicts(
        client_monkeypatch,
        [{"requirement_id": item_id, "is_met": is_met, "reasoning": "판정 근거"}],
        total_tokens=total_tokens,
        capture=capture,
        capture_call=capture_call,
    )


def respond_with_key_rejection(
    client_monkeypatch, *, status_code: int = 401, message: str = "Incorrect API key"
) -> None:
    """자격증명 자체가 거부됐다(#354·#355) — 채점 키 상태가 "거부됨"으로
    바뀌고 `ClassroomScore`는 생기지 않는다."""

    body = {"error": {"message": message}}
    client_monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: FakeVendorResponse(status_code, body)
    )


def respond_with_model_rejection(
    client_monkeypatch,
    *,
    status_code: int = 400,
    message: str = "The model `gpt-5` does not exist",
) -> None:
    """그 키로 그 모델을 쓸 수 없다(#403) — `error.code == "model_not_found"`."""

    body = {"error": {"message": message, "code": "model_not_found"}}
    client_monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: FakeVendorResponse(status_code, body)
    )


def respond_with_permanent_failure(client_monkeypatch, *, model: str = DEFAULT_OPENAI_MODEL_VERSION) -> None:
    """재시도해도 같은 결과인 실패(잘린 응답, `finish_reason != "stop"`) — 유예
    없이 즉시 전체 미달로 끝난다."""

    body = {"model": model, "choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
    client_monkeypatch.setattr("core.llm_scoring.requests.post", lambda *a, **k: FakeVendorResponse(200, body))


def respond_with_transient_failure(
    client_monkeypatch, *, status_code: int = 500, message: str = "internal error"
) -> None:
    """재시도하면 풀릴 수 있는 실패 — 상한(5회)까지 물러선다."""

    body = {"error": {"message": message}}
    client_monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: FakeVendorResponse(status_code, body)
    )


#: 2026-10-06 클래스 5 가 실제로 받은 응답의 모양(#586) — 크레딧이 바닥난 키.
QUOTA_EXHAUSTED_BODY = {
    "error": {
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "type": "insufficient_quota",
        "code": "credit_balance_exhausted",
    }
}

#: 요청 빈도 제한(#586) — 크레딧과 무관하게 잠시 뒤 풀린다.
RATE_LIMITED_BODY = {
    "error": {
        "message": "Rate limit reached for requests",
        "type": "requests",
        "code": "rate_limit_exceeded",
    }
}


def respond_with_quota_exhausted(client_monkeypatch) -> list:
    """키의 OpenAI 크레딧이 떨어졌다(429 `insufficient_quota`, #586). 불린 횟수를 세는
    목록을 돌려준다 — 「그동안 벤더를 부르지 않는다」를 평범한 assertion 으로 본다."""

    return track_vendor_calls(client_monkeypatch, status_code=429, body=QUOTA_EXHAUSTED_BODY)


def respond_with_rate_limit(client_monkeypatch) -> list:
    """요청 빈도 제한에 걸렸다(429 `rate_limit_exceeded`, #586)."""

    return track_vendor_calls(client_monkeypatch, status_code=429, body=RATE_LIMITED_BODY)


def fail_if_vendor_is_called(client_monkeypatch) -> None:
    """fake 어댑터 경로를 검증하는 테스트가 쓴다 — 네트워크로 나가면 그 자체가
    결함이므로 호출을 실패로 만든다."""

    def _fail(*args, **kwargs):
        raise AssertionError("fake 경로인데 core.llm_scoring.requests.post 가 불렸다 — 네트워크로 나갔다.")

    client_monkeypatch.setattr("core.llm_scoring.requests.post", _fail)


def raise_vendor_network_error(client_monkeypatch, exc: Exception) -> None:
    """벤더 채점 호출(POST)이 네트워크 오류로 실패한다 — 타임아웃·연결 끊김
    등, 재시도하면 풀릴 수 있는 실패다."""

    def _raise(*args, **kwargs):
        raise exc

    client_monkeypatch.setattr("core.llm_scoring.requests.post", _raise)


def track_vendor_calls(client_monkeypatch, *, status_code: int = 200, body: dict | None = None) -> list:
    """"이 시나리오에서는 벤더(POST)가 아예 불리지 않아야 한다"를 보는
    테스트가 쓴다. 예외를 던지는 `fail_if_vendor_is_called`와 달리, 실제로
    불렸을 때 그 사실이 목록에 남아 테스트 본문에서 평범한 assertion으로
    확인할 수 있다 — 스캔의 넓은 `except Exception`이 예외를 삼켜 확인이
    안 되는 것을 피한다(`classroom.scoring._score_one`)."""

    calls: list = []

    def _handler(*args, **kwargs):
        calls.append(kwargs.get("json"))
        return FakeVendorResponse(status_code, body or {})

    client_monkeypatch.setattr("core.llm_scoring.requests.post", _handler)
    return calls


# --- 벤더 응답 흉내 — 키 확인·모델 목록(GET /v1/models) ---------------------
#
# 저장 시점 키 확인(`OpenAIScoringAdapter.check_key`)과 모델 목록 조회
# (`list_openai_models`)는 같은 왕복을 공유한다(#469) — 흉내도 하나로 합친다.


class FakeVendorModelsResponse:
    def __init__(self, status_code: int, model_ids: list[str] | None = None) -> None:
        self.status_code = status_code
        self._model_ids = model_ids

    def json(self):
        if self._model_ids is None:
            return {}
        return {"data": [{"id": model_id} for model_id in self._model_ids]}


def respond_to_models_endpoint(
    client_monkeypatch, *, status_code: int = 200, model_ids: list[str] | None = None
) -> None:
    """GET `/v1/models` 응답을 고른다 — 키 확인은 `status_code`만 본다(#354).
    모델 목록 조회(#401)는 `status_code`가 200일 때 `model_ids`까지 본다."""

    client_monkeypatch.setattr(
        "core.llm_scoring.requests.get",
        lambda *a, **k: FakeVendorModelsResponse(status_code, model_ids),
    )


def raise_models_endpoint_network_error(client_monkeypatch, exc: Exception) -> None:
    """GET `/v1/models`이 네트워크 오류로 실패한다 — 키 확인은 "미검증"으로
    저장되고, 모델 목록 조회는 저장소의 기본 목록으로 물러난다."""

    def _raise(*args, **kwargs):
        raise exc

    client_monkeypatch.setattr("core.llm_scoring.requests.get", _raise)


def track_models_endpoint_calls(client_monkeypatch, *, model_ids: list[str] | None = None) -> list:
    """"벤더(GET)가 몇 번 불리는가"를 보는 테스트가 쓴다(#401 AC "같은 키로
    두 번 물으면 벤더를 한 번만 부른다") — `track_vendor_calls`의 GET 쪽."""

    calls: list = []

    def _handler(*args, **kwargs):
        calls.append(1)
        return FakeVendorModelsResponse(200, model_ids)

    client_monkeypatch.setattr("core.llm_scoring.requests.get", _handler)
    return calls


# --- 호환 서버 (#601) --------------------------------------------------------


def put_compatible_server(client, access: str, class_id: int, server_url: str, auth_value: str = ""):
    return client.put(
        f"{CLASSES_URL}/{class_id}/compatible-server",
        data={"server_url": server_url, "auth_value": auth_value},
        content_type="application/json",
        **auth_header(access),
    )


def set_compatible_server(client, access: str, class_id: int, server_url: str, auth_value: str = "") -> dict:
    response = put_compatible_server(client, access, class_id, server_url, auth_value)
    assert response.status_code == 200, response.content
    return response.json()


class FakeCompatibleServer:
    """강사의 호환 서버를 흉내 낸다 — `classroom.scoring_connection.SafeOutbound` 자리에 꽂는다.

    호환 서버로 나가는 왕복은 전부 안전한 바깥 호출(`core.safe_outbound`)을 거치므로, 그 경계
    너머(강사의 서버)를 여기서 고른다. 주소 확인(`check`)은 진짜 모듈에 맡기되 이름은 공인
    IP 하나로 풀린 것으로 친다. `requests` 는 OpenAI 키 연결 몫이라 이 흉내와 섞이지 않는다.

    - `model_ids`: `GET …/models` 가 내놓는 목록(`None` 이면 목록을 주지 않는다 — 404).
    - `accepted_auth`: 이 값의 Bearer 만 받는다(`None` 이면 인증을 보지 않는다).
    - `refuse`: 모든 요청을 이 이유(`OutboundReason`)로 거부한다 — 닿지 않음·인증서 등.
    - `verdicts`: 채점 요청에 돌려줄 판정 몸통(`openai_verdicts_body` 모양).
    - `error`: 채점 요청에서 던질 예외(예상 못한 실패).
    - `keeps_format`: 모델 시험 호출(#602)에 판정 형식대로 답하는가 — 거짓이면 글로만 답한다.
      시험 호출은 `verdicts` 와 상관없이 이 값으로 답한다(`probe_requests` 로 따로 센다).
    """

    def __init__(
        self,
        *,
        model_ids: list[str] | None = None,
        accepted_auth: str | None = None,
        refuse=None,
        verdicts: dict | None = None,
        error: Exception | None = None,
        keeps_format: bool = True,
    ) -> None:
        self.model_ids = model_ids
        self.accepted_auth = accepted_auth
        self.refuse = refuse
        self.verdicts = verdicts
        self.error = error
        self.keeps_format = keeps_format
        self.requests: list[dict] = []

    @property
    def probe_requests(self) -> list[dict]:
        from classroom.scoring_model_probe import PROBE_PROMPT

        return [r for r in self.requests if r["json"] and r["json"]["messages"][-1]["content"] == PROBE_PROMPT]

    @property
    def scoring_requests(self) -> list[dict]:
        probes = self.probe_requests
        return [r for r in self.requests if r["method"] == "POST" and r not in probes]

    def install(self, monkeypatch) -> "FakeCompatibleServer":
        monkeypatch.setattr("classroom.scoring_connection.SafeOutbound", lambda: self)
        return self

    def check(self, url: str):
        from core.safe_outbound import SafeOutbound

        return SafeOutbound(resolver=lambda host, port: ["93.184.216.34"]).check(url)

    def get(self, url, *, headers, timeout):
        return self.request("GET", url, headers=headers, timeout=timeout)

    def post_json(self, url, body, *, headers, timeout):
        return self.request("POST", url, headers=headers, timeout=timeout, json=body)

    def request(self, method, url, *, headers, timeout, json=None):
        from core.safe_outbound import OutboundRefused

        self.check(url)
        self.requests.append({"method": method, "url": url, "headers": dict(headers), "json": json})
        if self.refuse is not None:
            raise OutboundRefused(self.refuse, "흉내")
        if self.accepted_auth is not None and headers.get("Authorization") != f"Bearer {self.accepted_auth}":
            return FakeVendorResponse(401, {"error": {"message": "unauthorized"}})
        if url.endswith("/models"):
            if self.model_ids is None:
                return FakeVendorResponse(404, {"error": {"message": "not found"}})
            return FakeVendorModelsResponse(200, list(self.model_ids))
        from classroom.scoring_model_probe import PROBE_PROMPT, PROBE_REQUIREMENT_ID

        if json is not None and json["messages"][-1]["content"] == PROBE_PROMPT:
            if not self.keeps_format:
                return FakeVendorResponse(
                    200, {"choices": [{"finish_reason": "stop", "message": {"content": "Sure! hello is printed."}}]}
                )
            return FakeVendorResponse(200, openai_success_body(PROBE_REQUIREMENT_ID, model=json["model"]))
        if self.error is not None:
            raise self.error
        return FakeVendorResponse(200, self.verdicts)
