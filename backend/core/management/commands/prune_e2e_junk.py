"""e2e 가 남긴 기준데이터와 정책 오염을 걷는다 (#183).

**Contest 는 이미 걷힌다.** `seed_e2e_contests` 가 제목 접두어로 자기 것을 가르고,
`--prune-all-namespaces` 가 스위트 시작에 한 번 전부 걷는다(그 명령의 `_prune_all_namespaces`
docstring 이 왜 스위트 시작이 유일하게 안전한 시점인지 적어 뒀다 — 그때는 워커가 아직 없어
경합이 성립하지 않는다). 이 명령은 **그 관용구를 Category·DeliverableType·정책 단일 행으로
넓힌 것**이고, 같은 시점에 같은 방식으로 돈다.

**왜 `seed_e2e_contests` 안에 넣지 않았나.** 그 명령은 contests 앱의 시드다. 정책 단일 행은
policies 앱에 있고, 「공모전 시드가 플랫폼 수수료율을 되돌린다」는 배선은 다음에 읽는 사람이
납득할 수 없다. 그래서 두 앱을 다 아는 자리(core)에 청소만 하는 명령을 따로 둔다 — 사람이
쌓인 것을 한 번에 걷을 때도 이 하나만 부르면 된다.

**무엇이 「e2e 가 만든 것」인가.** 이름이 `e2e` 또는 `[e2e` 로 시작하는 행이다(대소문자
무시). 실측한 dev DB 에는 서로 다른 시절이 남긴 세 모양이 함께 있었다 —
`seed_e2e_contests` 의 네임스페이스 접두어(`[E2E-w0] 웹 서비스`), 운영자 큐 시드의
`E2E 운영자 큐용 웹서비스`, 그리고 지금은 지워진 운영자 스펙들이 화면으로 만든
`e2e 생성 종류 1788…`. 진짜 기준데이터(`웹 서비스`·`모바일 앱`·`관리자 페이지`·
`데스크톱 프로그램`·`랜딩·원페이지`, `게임`·`교육`·`라이프스타일`·`엔터테인먼트`)는 이
모양을 쓰지 않는다.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from accounts.management.commands.seed_e2e_operator_queues import (
    _refuse_in_deployed_environment,
)
from contests.models import Category, DeliverableType, DeliverableTypeChange
from policies.models import PlatformPolicy
from policies.services import UPDATABLE_FIELDS

# 이름 하나로 「e2e 가 만든 것」을 가른다. `name` 하나만 보는 이유는 그것이 이 저장소가
# Contest 에 대해 이미 쓰는 판정 기준이기 때문이다 — 새 방식을 만들지 않는다.
_E2E_NAME = Q(name__istartswith="e2e") | Q(name__istartswith="[e2e")


def _json_safe(value: object) -> object:
    """JSON 으로 그대로 낼 수 있는 값만 통과시키고, 나머지는 문자열로 바꾼다.

    `Decimal` 이 대표적이다 — `json.dumps` 가 그 자리에서 `TypeError` 로 죽는다.
    """

    return value if isinstance(value, (int, str)) and not isinstance(value, bool) else str(value)


class Command(BaseCommand):
    help = "e2e 가 남긴 Category·DeliverableType 을 지우고 플랫폼 정책을 기준값으로 되돌린다."

    def handle(self, *args, **options) -> None:
        _refuse_in_deployed_environment("prune_e2e_junk")

        skipped: list[str] = []
        deliverable_types_deleted = self._prune(DeliverableType, skipped)
        categories_deleted = self._prune(Category, skipped)
        policy_reset = self._reset_policy()

        for name in skipped:
            # **청소는 검증이 아니다.** 막힌 것이 있어도 명령은 성공으로 끝난다 — 이
            # 명령의 실패로 스위트가 빨개지면 「테스트가 깨졌다」와 「청소가 막혔다」를
            # 구별할 수 없다. 다만 조용히 넘어가지도 않게 stderr 에 남긴다.
            self.stderr.write(f"참조가 걸려 건너뛴다: {name}")

        self.stdout.write(
            json.dumps(
                {
                    "categories_deleted": categories_deleted,
                    "deliverable_types_deleted": deliverable_types_deleted,
                    "skipped": skipped,
                    "policy_reset": policy_reset,
                },
                ensure_ascii=False,
            )
        )

    def _prune(self, model: type, skipped: list[str]) -> int:
        """`model` 의 e2e 행을 하나씩 지운다. 참조가 걸린 것은 건너뛴다.

        **한 번에 `.delete()` 하지 않는다.** 그러면 참조가 걸린 행 하나가 통째로 삭제를
        막아 나머지도 살아남는다 — 예전에 `seed_e2e_contests` 가 기준데이터를 지우려다
        `ProtectedError` 로 명령 전체가 죽은 것이 정확히 그 모양이다. 행 하나가 남는 것과
        명령이 죽는 것은 값이 다르다.
        """

        deleted = 0
        for row in model.objects.filter(_E2E_NAME):
            # **살아남은 Contest 가 가리키고 있으면 건드리지 않는다.** `Contest.category` 는
            # PROTECT 라 아래 `except` 가 잡아 주지만, `Contest.deliverable_types` 는 평범한
            # M2M 이라 **아무 예외 없이** 조인 행만 사라진다 — 그 Contest 는 산출물 종류가
            # 0개가 되고(스냅샷해 둔 최소 제안 상금은 이제 아무것도 가리키지 않는다), 아무
            # 데도 보고되지 않는다. 사람이 손으로 부르는 경로(CLAUDE.md)에서 실제로 일어날
            # 수 있는 일이다: 잡데이터로 덮인 개최 화면에서 e2e 이름의 종류를 골라 만든
            # Contest 가 조용히 망가진다.
            #
            # 스위트 흐름에서는 Contest 가 먼저 걷히므로 이 검사에 걸리는 것이 없다 —
            # 손해 없이 조용한 손상만 막는다.
            if row.contests.exists():
                skipped.append(row.name)
                continue
            try:
                with transaction.atomic():
                    if model is DeliverableType:
                        # `DeliverableTypeChange.deliverable_type` 이 PROTECT 라, 이력을
                        # 남긴 채로는 종류를 지울 수 없다 — 실측에서 e2e 종류 127개 중
                        # 108개가 이력을 달고 있었다(운영자 화면으로 만들어졌기 때문이다).
                        # 이력을 건드리지 않으면 정리는 19개만 걷고 끝난다.
                        #
                        # **지우는 것은 e2e 가 만든 종류에 달린 이력뿐이다.** 진짜 종류의
                        # 이력은 대상이 아니고, 정책 변경 이력(`PolicyChange`)은 이 명령이
                        # 아예 손대지 않는다 — 그쪽은 지울 행이 없어도 값만 되돌리면 되기
                        # 때문이고, 그것이 ADR-0023 이 지키려는 감사 추적이다.
                        DeliverableTypeChange.objects.filter(deliverable_type=row).delete()
                    row.delete()
            except ProtectedError:
                skipped.append(row.name)
                continue
            deleted += 1
        return deleted

    def _reset_policy(self) -> dict[str, list[object]]:
        """정책 단일 행을 기준값으로 되돌리고, 바뀐 것만 보고한다.

        **무엇이 「정책값」인가는 `policies.services.UPDATABLE_FIELDS` 가 이미 정한다** —
        운영자 API 가 바꿀 수 있는 필드 집합이고, `POST /api/operator/policy` 가 유일한
        변경 경로이므로 **e2e 가 오염시킬 수 있는 필드와 정확히 같다.** 새 정책값이 그
        집합에 편입되면 이 명령도 같이 따라간다.

        이 집합으로 좁히지 않고 「기본값이 있는 필드 전부」로 돌렸다가 실제로 사고를
        냈다: `version` 은 정책값이 아니라 낙관적 동시성 카운터인데(#76 — GET 이 돌려준
        값과 같을 때만 갱신한다) 그것을 28에서 0으로 되돌렸다. 카운터가 뒤로 가면 나중
        쓰기가 앞선 쓰기를 조용히 덮을 길이 열린다.

        **기준값은 모델 필드의 기본값에서 읽는다** — 이 명령이 따로 적어 두면 두 곳에
        적히고, 그 뒤처짐은 「dev 에서 본 숫자가 실제 정책과 다르다」는 형태로만 드러난다.
        그건 이 티켓이 고치려는 바로 그 증상이다.

        행이 없으면 만들지 않는다 — 이 명령의 일은 청소지 초기화가 아니다.
        """

        policy = PlatformPolicy.objects.filter(pk=1).first()
        if policy is None:
            return {}

        changed: dict[str, list[object]] = {}
        for name in sorted(UPDATABLE_FIELDS):
            field = PlatformPolicy._meta.get_field(name)
            current = getattr(policy, name)
            default = field.get_default()
            if current != default:
                # 값을 JSON 으로 낼 수 있는 모양으로 바꾼다. 지금 집합은 전부 정수지만
                # 다음에 편입될 후보(`distribution_cutline_percentage`)는 Decimal 이고,
                # 그러면 `json.dumps` 가 그 자리에서 죽어 HTTP 입구로는 500 이 된다 —
                # 그 500 이 `globalSetup` 을 죽이면 스위트가 한 건도 못 돈다.
                changed[name] = [_json_safe(current), _json_safe(default)]
                setattr(policy, name, default)
        if changed:
            # `version` 은 건드리지 않는다 — 위 docstring 참고. `updated_at` 은 `auto_now`
            # 지만 **`update_fields` 에 넣지 않으면 갱신되지 않는다**(Django 가 `non_pks` 를
            # `update_fields` 로 걸러 `pre_save` 를 아예 부르지 않는다). 빠뜨리면 운영자
            # 화면이 「수수료율 1000, 마지막 변경은 324 이던 시각」을 보여준다 — 이 티켓이
            # 없애려는 바로 그 「화면의 숫자가 실제와 다르다」이다.
            policy.save(update_fields=[*changed, "updated_at"])
        return changed
