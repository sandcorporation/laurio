"""어댑터 모드(fake/dotted-path) 선택 공용 헬퍼 (ADR-0007).

PG·스토리지·LLM 등 외부 의존성은 전부 같은 모양으로 갈아끼운다: 설정값이
`"fake"`면 결정적인 fake 구현체를, 아니면 그 값을 dotted path로 보고
`import_string`으로 실제 구현체를 불러온다. 이 선택 로직 자체를 각 앱(`scoring`,
`contests`)이 따로 구현하지 않고 여기서 하나로 공유한다 — #20(AI grill)이
두 번째 LLM 연동을 만들지 않고 #12(AI 채점)가 이미 쓰는 것과 같은 선택 방식을
재사용하기 위해서다.

`check_adapter_mode`(#83)는 배포 환경의 부팅 가드다. 반드시
`django.core.checks`로 등록해 `django.setup()` 이후에만 평가해야 한다 —
settings.py 모듈 실행 도중(=아직 앱 레지스트리가 준비되지 않은 시점)에 dotted
path를 import하면, 그 경로가 모델을 참조하는 실물 어댑터일 때
`AppRegistryNotReady`가 나고 그건 `except ImportError`로 잡히지 않아 그대로
부팅이 깨진다. `core.apps.CoreConfig.ready()`의 `core.transitions` 지연 임포트와
같은 이유다.
"""

from __future__ import annotations

from importlib import import_module
from typing import Callable, TypeVar

from django.conf import settings
from django.core.checks import Error
from django.utils.module_loading import import_string

T = TypeVar("T")


def is_fake_adapter_binding(value: str) -> bool:
    """"fake" 별칭이거나, dotted path가 가리키는 클래스명이 Fake로 시작하면 True.

    원래는 `value == "fake"`만 봤다. 그런데 STORAGE_BACKEND는 "fake"가 별칭
    dict(storage.adapters._BACKENDS)를 거쳐 실제 dotted path로 풀리고,
    LLM_ADAPTER_MODE/LLM_REQUIREMENT_CHAT_ADAPTER_MODE는 "fake"가 아니면 뭐든
    dotted path로 그대로 import한다(resolve_adapter) — 즉 운영 배포에서
    `STORAGE_BACKEND=storage.adapters.fake.FakeStorageAdapter`처럼 "fake"라는
    별칭 문자열만 피해 가면 실제로는 여전히 Fake 어댑터가 조용히 바인딩된다.
    그래서 별칭 문자열이 아니라 "가리키는 클래스가 Fake인가"를 직접 판정한다.

    `config.settings`의 배포 부팅 가드(IS_DEPLOYED_ENVIRONMENT일 때 fake 바인딩을
    거부)와 `verification.api.verify`의 identityVerificationId 소유권 확인
    (fake 모드는 그 확인을 건너뛴다)이 반드시 같은 판정을 써야 한다(#85 코드리뷰
    지적 5) — 한쪽만 dotted-path-그러나-Fake인 값을 "fake로 안 본다"고 판정하면,
    검사가 서로 다른 결론에 도달해 배포 가드는 통과했는데 본인확인 자체가 항상
    403으로 막히는 상황이 생긴다. 이 함수 하나를 두 곳 모두에서 그대로 쓴다.
    """

    if value == "fake":
        return True
    class_name = value.rsplit(".", 1)[-1]
    return class_name.startswith("Fake")


def resolve_adapter(*, mode: str, fake_factory: Callable[[], T], not_implemented_hint: str) -> T:
    """`mode`가 `"fake"`면 `fake_factory()`를, 아니면 dotted path를 import해 인스턴스화한다.

    dotted path가 가리키는 **모듈 자체가 없으면** "아직 구현되지 않았다"는
    뜻이므로 `NotImplementedError`로 안내한다. 반면 그 모듈은 있는데 **내부에서
    부르는 다른 모듈**이 없어 깨지면 그대로 올려보낸다(#83 코드리뷰 지적) —
    "아직 구현되지 않았다"와 "이미 구현했는데 깨졌다"는 서로 다른 사실이고,
    후자를 전자의 메시지로 덮으면 실제 버그를 찾는 사람이 엉뚱한 곳(존재하지
    않는 걸 왜 구현하냐는 질문)을 보게 된다.
    """

    if mode == "fake":
        return fake_factory()

    module_path, _, class_name = mode.rpartition(".")
    if not module_path:
        raise NotImplementedError(
            f"{not_implemented_hint}\n({mode!r}는 'module.ClassName' 형태의 dotted path가 아니다.)"
        )

    try:
        module = import_module(module_path)
    except ModuleNotFoundError as exc:
        if exc.name == module_path:
            # module_path 자신이 없다 — 아직 구현되지 않았다는 뜻 그대로다.
            raise NotImplementedError(not_implemented_hint) from exc
        # module_path는 실제로 있는데, 그 모듈이 내부에서 부르는 다른 모듈이
        # 없어서 무너졌다 — "아직 구현되지 않았다"가 아니라 "이미 구현됐는데
        # 깨졌다"다. 원인을 숨기지 않고 그대로 전파한다.
        raise

    try:
        adapter_cls = getattr(module, class_name)
    except AttributeError as exc:
        raise NotImplementedError(not_implemented_hint) from exc

    return adapter_cls()


def check_adapter_mode(*, setting_name: str, protocol: type) -> list[Error]:
    """배포 환경에서 어댑터 모드 값이 "fake"도 아니고 실제로 쓸 수도 없으면 `Error`를 낸다 (#83).

    호출자는 반드시 `django.core.checks.register`로 등록해야 한다 — 그래야
    `django.setup()` 이후(`manage.py check`/`migrate`/`runserver` 부팅
    파이프라인)에만 평가된다.

    "import만 되면 통과"가 아니다(#83 코드리뷰 지적) — 실제로 인자 없이
    인스턴스화하고, 그 인스턴스가 `protocol`이 요구하는 멤버를 전부 갖췄는지도
    `isinstance`로 확인한다. `payments.adapters.PGError`처럼 존재는 하지만
    전혀 엉뚱한 클래스를 가리키는 오타가 이 검사를 통과하고 첫 결제에서야
    (그것도 `AttributeError`라는 알아보기 어려운 모양으로) 죽는 것을 막는다.
    `protocol`은 `@runtime_checkable` Protocol이어야 한다.

    dev는 대상이 아니다 — 오타를 부팅 실패로 바꿀 만큼 배포와 같은 무게가
    아니다.
    """

    if not settings.IS_DEPLOYED_ENVIRONMENT:
        return []

    value = getattr(settings, setting_name, "")
    if value == "fake":
        return []

    try:
        adapter_cls = import_string(value)
    except ImportError as exc:
        return [
            Error(
                f"{setting_name}={value!r} 를 임포트할 수 없다 ({exc}).",
                hint=(
                    '"fake"이거나 실제 어댑터 클래스의 dotted path'
                    '("module.ClassName")여야 한다.'
                ),
                id="core.E001",
            )
        ]

    try:
        instance = adapter_cls()
    except Exception as exc:  # noqa: BLE001 - 어댑터 생성자가 무엇을 던지든 부팅 가드가 잡아야 한다
        return [
            Error(
                f"{setting_name}={value!r} 가 가리키는 클래스를 인자 없이 생성할 수 없다 "
                f"({exc}).",
                hint=(
                    "core.adapters.resolve_adapter는 어댑터를 인자 없이 생성한다 — "
                    "생성자가 필수 인자를 요구하면 안 된다."
                ),
                id="core.E002",
            )
        ]

    if not isinstance(instance, protocol):
        return [
            Error(
                f"{setting_name}={value!r} 가 가리키는 클래스가 "
                f"{protocol.__module__}.{protocol.__qualname__} 계약을 만족하지 않는다.",
                hint="그 Protocol이 요구하는 메서드를 전부 구현해야 한다.",
                id="core.E003",
            )
        ]

    return []
