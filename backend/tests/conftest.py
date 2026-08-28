"""프로젝트 전역 pytest 픽스처.

`FakeStorageAdapter._store`(#12)는 인스턴스가 아니라 클래스 레벨 딕셔너리다 —
`storage.adapters.get_storage_adapter()`가 호출마다 새 인스턴스를 만들기 때문에,
한 요청에서 쓴 바이트가 다른 요청(채점 스캔 등)에서도 보이려면 인스턴스를 넘어
프로세스 수명 동안 유지되는 저장소가 필요해서 그렇게 설계했다. 하지만 DB는
`@pytest.mark.django_db`가 트랜잭션 롤백으로 테스트마다 초기화해주는 반면, 이
딕셔너리는 아무도 비우지 않으면 프로세스(테스트 세션) 수명 내내 쌓인다 — 테스트
간 격리가 깨지고(다른 테스트가 쓴 object_key가 남의 세션에도 보임) 메모리도 계속
자란다(#12 리뷰 지적). autouse로 매 테스트 전후 비운다.
"""

import pytest

from storage.adapters.fake import FakeStorageAdapter


@pytest.fixture(autouse=True)
def _reset_fake_storage_adapter():
    FakeStorageAdapter._store.clear()
    yield
    FakeStorageAdapter._store.clear()
