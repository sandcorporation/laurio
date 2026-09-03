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
from django.conf import settings
from django.core.cache import caches
from django.test import override_settings

from payments.adapters import FakePGAdapter
from storage.adapters.fake import FakeStorageAdapter


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


@pytest.fixture(scope="session", autouse=True)
def _scope_session_cache_to_xdist_worker(worker_id):
    """워커마다 다른 Redis DB 인덱스를 준다 — `-n` 으로 병렬 실행할 때만 (#104).

    아래 `_reset_operator_sessions` 가 매 테스트마다 세션 캐시를 비우는데, Django 의
    RedisCache 는 그것을 **FLUSHDB** 로 구현한다 — **키 접두어로는 막을 수 없다.**
    워커 넷이 같은 인덱스를 쓰면 한 워커의 정리가 다른 워커의 로그인 세션을 통째로
    지우고, 피해자는 원인과 무관한 401 무더기를 본다. Postgres 쪽은 pytest-django 가
    워커별 테스트 DB 를 알아서 만들어 주지만 캐시는 그렇지 않다.

    `override_settings` 로 바꾸는 이유 — Django 의 캐시 핸들러가 `setting_changed`
    신호를 듣고 연결을 다시 만든다. 값만 바꾸면 이미 열린 연결이 옛 인덱스를 계속
    쓴다.
    """

    if worker_id == "master":
        yield
        return

    base, _, index = settings.SESSION_REDIS_URL.rpartition("/")
    offset = int(worker_id.removeprefix("gw"))
    scoped = int(index) + offset + 1
    if scoped > 15:
        raise RuntimeError(
            f"워커 {worker_id} 의 세션 Redis 인덱스가 {scoped} 라 Redis 기본 범위(0~15)를 "
            f"넘는다. SESSION_REDIS_URL 의 인덱스를 낮추거나 워커 수를 줄여라 — "
            "인덱스가 겹치면 워커들이 서로의 세션을 FLUSHDB 로 지운다."
        )

    caches_setting = {
        name: dict(config) for name, config in settings.CACHES.items()
    }
    caches_setting["sessions"]["LOCATION"] = f"{base}/{scoped}"
    with override_settings(CACHES=caches_setting):
        yield


@pytest.fixture(autouse=True)
def _reset_operator_sessions():
    """Operator 세션은 실제 Redis 에 산다(#43) — DB 처럼 롤백되지 않는다.

    `@pytest.mark.django_db` 가 되돌리는 것은 Postgres 트랜잭션뿐이다. 세션은
    Redis 에 그대로 남아 다음 테스트가 남의 로그인 상태를 물려받는다 — 하필
    "로그아웃하면 그 자리에서 막힌다"를 검증하는 테스트들이 그 오염에 가장 약하다.
    매 테스트 전후로 세션 캐시를 비운다.

    별도 DB 인덱스(settings.SESSION_REDIS_URL 의 /1)를 쓰므로 Celery 브로커의
    키를 지우지 않는다.
    """

    caches["sessions"].clear()
    yield
    caches["sessions"].clear()
