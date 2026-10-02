"""프로젝트 전역 pytest 픽스처.

`FakeStorageAdapter._store`(#12)와 `FakePGAdapter._final_refund_status`(#17
리뷰 지적)는 둘 다 인스턴스가 아니라 클래스 레벨 딕셔너리다 —
`storage.adapters.get_storage_adapter()`/`payments.adapters.get_adapter()`가
호출마다 새 인스턴스를 만들기 때문에, 한 요청에서 남긴 상태가 다른 요청(채점
스캔, 환불 재확인 스캔 등)에서도 보이려면 인스턴스를 넘어 프로세스 수명 동안
유지되는 저장소가 필요해서 그렇게 설계했다. 하지만 DB는
`@pytest.mark.django_db`가 트랜잭션 롤백으로 테스트마다 초기화해주는 반면, 이
딕셔너리들은 아무도 비우지 않으면 프로세스(테스트 세션) 수명 내내 쌓인다 —
테스트 간 격리가 깨지고(다른 테스트가 쓴 object_key/환불 상태가 남의 세션에도
보임) 메모리도 계속 자란다(#12 리뷰 지적, #17 리뷰 지적). autouse로 매 테스트
전후 비운다.
"""

import pytest
from django.core.cache import caches

from contests.search import FakeContestSearchAdapter
from contests.view_flush_store import InMemoryChangedContestsStore
from core.events import FakeEventBus
from payments.adapters import FakePGAdapter
from storage.adapters.fake import FakeStorageAdapter


# --- 시험 하나의 CPU 한도 ----------------------------------------------------
#
# 시험 하나의 본문(call 단계)이 쓴 CPU 시간이 한도를 넘으면 실패로 바꾼다
# (2026-10-02). 벽시계가 아니라 CPU 로 재는 이유: 벽시계는 CI 가 붐빌 때
# 한도 근처의 시험이 빌드마다 번갈아 떨어진다. 자식 프로세스 몫
# (`RUSAGE_CHILDREN` — 문법 검사가 파일마다 서브프로세스를 띄운다)도 더한다.
# 준비(픽스처)는 재지 않는다 — 그쪽은 따로 줄인다.
#
# 한도는 `CODEMIT_TEST_CPU_LIMIT`(초, 기본 1.0)이고 CI 는 1.5 를 준다. 0 이면
# 끈다. Postgres 가 질의를 처리하는 시간은 다른 프로세스라 여기 잡히지 않는다.

import os
import resource
import time

_CPU_LIMIT_SECONDS = float(os.environ.get("CODEMIT_TEST_CPU_LIMIT", "1.0"))


def _cpu_seconds() -> float:
    from tests.boot_process import charged_cpu_seconds

    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    # forkserver 자식은 이 프로세스의 자식이 아니라 RUSAGE_CHILDREN 에 안 잡힌다
    # — 자식이 돌려준 몫을 더한다(`tests/boot_process.py`).
    return time.process_time() + children.ru_utime + children.ru_stime + charged_cpu_seconds()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    started = _cpu_seconds()
    try:
        return (yield)
    finally:
        item._codemit_cpu_seconds = _cpu_seconds() - started


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    spent = getattr(item, "_codemit_cpu_seconds", None)
    if report.when == "call" and spent is not None:
        report.user_properties.append(("cpu_seconds", round(spent, 3)))
        if _CPU_LIMIT_SECONDS > 0 and spent > _CPU_LIMIT_SECONDS and report.passed:
            report.outcome = "failed"
            report.longrepr = (
                f"시험 본문이 CPU {spent:.2f}초를 썼다 — 한도 {_CPU_LIMIT_SECONDS:.2f}초"
                " (CODEMIT_TEST_CPU_LIMIT). 원인을 찾아 줄인다; 한도를 늘리지 않는다."
            )
    return report


class _StubKeyCheckResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def json(self):  # pragma: no cover - check_key()는 본문을 읽지 않는다
        return {}


@pytest.fixture(autouse=True)
def _default_openai_key_check_never_hits_the_network(monkeypatch):
    """`PUT .../classes/{id}/openai-key`(#354)는 저장할 때마다 `core.llm_scoring.
    requests.get`으로 벤더에게 실제로 묻는다. `CLASSROOM_SCORING_ADAPTER_MODE`를
    실물 어댑터로 강제하는 테스트 파일이 여럿(#340, ADR-0043) 있고, 그 파일들은
    채점(`requests.post`) 경로가 관심사라 키 확인까지 매번 monkeypatch하지
    않는다 — 그 상태로 두면 가짜 키로 `_set_key()`를 부르는 순간 실제
    api.openai.com에 네트워크 요청이 나간다(브라우저 걷기·CI에서 절대 있어선
    안 되는 일이다).

    기본값을 여기서 한 번 "확인함"으로 깔아 둔다 — 키 확인 자체를 검증하는
    테스트(`test_classroom_scoring_key_status.py`)는 자기 테스트 안에서 같은
    자리를 다시 monkeypatch해 이 기본값을 덮어쓴다(monkeypatch는 테스트당 같은
    인스턴스라 나중 호출이 그대로 이긴다)."""

    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _StubKeyCheckResponse(200))


@pytest.fixture(autouse=True)
def _reset_fake_storage_adapter():
    FakeStorageAdapter._store.clear()
    yield
    FakeStorageAdapter._store.clear()


@pytest.fixture(autouse=True)
def _reset_fake_pg_adapter():
    FakePGAdapter._final_refund_status.clear()
    yield
    FakePGAdapter._final_refund_status.clear()


@pytest.fixture(autouse=True)
def _reset_fake_event_bus():
    """`core.events.FakeEventBus._queues`도 클래스 레벨이라 위 둘과 같은 이유로
    비운다 — 안 그러면 한 테스트가 발행한 신호가 같은 recipient_id를 재사용하는
    (오토인크리먼트 PK라 흔하다) 다음 테스트의 큐에 남는다."""

    FakeEventBus._queues.clear()
    yield
    FakeEventBus._queues.clear()


@pytest.fixture(autouse=True)
def _reset_changed_contests_store():
    """`InMemoryChangedContestsStore._ids`도 클래스 레벨이다(#446) — 조회를
    기록하는 요청과 옮기기 스캔을 부르는 요청이 서로 다른 인스턴스라도 같은
    「바뀐 공모전」 집합을 봐야 해서 `FakeEventBus._queues`와 같은 이유로
    그렇게 설계했다. 비우지 않으면 한 테스트가 남긴 id가 다음 테스트의
    "바뀐 것이 없다" 단언을 깬다."""

    InMemoryChangedContestsStore._ids.clear()
    yield
    InMemoryChangedContestsStore._ids.clear()


@pytest.fixture(autouse=True)
def _reset_fake_search_adapter():
    """`contests.search.FakeContestSearchAdapter._indexed`도 클래스 레벨이라
    위와 같은 이유로 비운다 — 안 그러면 한 테스트가 색인한 contest_id가(오토인크리먼트
    PK라 흔하다) 다음 테스트의 색인 기록에 남는다."""

    FakeContestSearchAdapter._indexed.clear()
    yield
    FakeContestSearchAdapter._indexed.clear()


@pytest.fixture(autouse=True)
def _reset_operator_sessions():
    """Operator 세션은 실제 Redis 에 산다(#43) — DB 처럼 롤백되지 않는다.

    `@pytest.mark.django_db` 가 되돌리는 것은 Postgres 트랜잭션뿐이다. 세션은
    Redis 에 그대로 남아 다음 테스트가 남의 로그인 상태를 물려받는다 — 하필
    "로그아웃하면 그 자리에서 막힌다"를 검증하는 테스트들이 그 오염에 가장 약하다.
    매 테스트 전후로 세션 캐시를 비운다.

    **이 캐시는 테스트에서 LocMem 이다**(config/settings.py 의 `_RUNNING_TESTS`) — 즉
    이 `clear()` 는 이 프로세스 안만 비운다. 예전에는 실물 Redis 라 FLUSHDB 였고, 그래서
    워커마다 인덱스를 갈라 줘야 했으며 호스트에서 돌린 pytest 가 떠 있는 dev 환경까지
    지웠다.

    **세션 때문만은 아니다.** 세션 키는 무작위이고 어떤 테스트도 세션 수를 세지 않아
    남은 세션은 무해하다. 실제로 이 정리에 기대는 것은 **ContestView 카운터**다 —
    `contests/view_tracking.py` 가 같은 캐시 별칭에 `timeout=None` 으로 영구 저장하고,
    `tests/test_contest_metrics.py` 가 그 값을 0·1·2·3 으로 정확히 단언한다.
    """

    caches["sessions"].clear()
    yield
    caches["sessions"].clear()
