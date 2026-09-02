"""`core.adapters.resolve_adapter`가 "없는 모듈"과 "깨진 모듈"을 구분하는지
검증하는 테스트 전용 fixture(#83 코드리뷰 지적).

이 모듈 자신은 존재하지만, 임포트되는 순간 존재하지 않는 다른 모듈을 불러오려다
`ModuleNotFoundError`로 무너진다 — "아직 구현되지 않았다"가 아니라 "이미
구현했는데 내부가 깨졌다"는 사실을 흉내낸다. `tests/test_core_adapters.py`가
`resolve_adapter`에 이 모듈의 dotted path를 넘겨, 그 예외가 `NotImplementedError`로
덮이지 않고 그대로 올라오는지 확인한다.
"""

from tests._this_dependency_does_not_exist_anywhere import Nonexistent  # noqa: F401
