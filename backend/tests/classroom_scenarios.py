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


def openai_success_body(
    item_id: int,
    *,
    is_met: bool = True,
    reasoning: str = "판정 근거",
    model: str = DEFAULT_OPENAI_MODEL_VERSION,
) -> dict:
    return {
        "model": model,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"verdicts": [{"requirement_id": item_id, "is_met": is_met, "reasoning": reasoning}]}
                    )
                },
            }
        ],
    }


def respond_with_verdict(
    client_monkeypatch,
    item_id: int,
    *,
    is_met: bool = True,
    capture: list | None = None,
) -> None:
    """다음 스캔에서 그 항목을 통과(`is_met=True`)·미달로 판정하는 성공 응답을
    흉내 낸다. `capture`를 주면 벤더로 나간 요청 본문을 그 목록에 쌓는다(프롬프트
    내용을 확인하는 테스트용)."""

    body = openai_success_body(item_id, is_met=is_met)

    def _handler(*args, **kwargs):
        if capture is not None:
            capture.append(kwargs["json"])
        return FakeVendorResponse(200, body)

    client_monkeypatch.setattr("core.llm_scoring.requests.post", _handler)


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


def fail_if_vendor_is_called(client_monkeypatch) -> None:
    """fake 어댑터 경로를 검증하는 테스트가 쓴다 — 네트워크로 나가면 그 자체가
    결함이므로 호출을 실패로 만든다."""

    def _fail(*args, **kwargs):
        raise AssertionError("fake 경로인데 core.llm_scoring.requests.post 가 불렸다 — 네트워크로 나갔다.")

    client_monkeypatch.setattr("core.llm_scoring.requests.post", _fail)
