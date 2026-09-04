"""e2e 시드 등록부 (#156).

e2e 는 시드 한 번마다 `uv run python manage.py` 로 Django 를 새로 부팅했다 — 심는 데이터
양과 무관한 순수 시동 비용이 **약 0.9초**이고, 스위트 한 번에 백 번 넘게 치른다. 이미 떠
있는 프로세스가 답하면 그 비용이 통째로 사라진다.

**이름은 등록부에서만 온다.** `core.scans.SCAN_REGISTRY` 와 같은 규약이다 — 요청이 준
문자열을 그대로 관리 명령 이름으로 넘기면 그건 시드 표면이 아니라 **내부 토큰 하나로 아무
관리 명령이나 돌리는 표면**이다(`createsuperuser`, `flush`, `dumpdata` …).

**옵션도 시드마다 허용 목록을 갖는다** — 각 명령이 받는 것 전부가 아니라 e2e 가 실제로
쓰는 것만 연다. 목록에 없는 이름은 명령으로 넘어가기 전에 거부된다. 이것은 명령의 인자
표면이 나중에 늘어났을 때 그 새 인자가 자동으로 HTTP 로도 열리는 것을 막는 장치다.

구현 자체는 관리 명령이 그대로 갖는다 — 여기는 **두 번째 입구**일 뿐이다. 명령을
`call_command` 로 in-process 호출하므로 로직이 두 벌이 되지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedEntry:
    command: str
    # 요청이 고를 수 있는 옵션 이름 → 관리 명령의 옵션 이름. 여기 없는 것은 400 이다.
    options: frozenset[str]


E2E_SEED_REGISTRY: dict[str, SeedEntry] = {
    "contests": SeedEntry(
        command="seed_e2e_contests",
        options=frozenset({"namespace", "bulk", "prune_all_namespaces"}),
    ),
    "operator": SeedEntry(
        command="seed_e2e_operator",
        # `superuser` 는 연다 — 운영자 앱의 일부 화면이 superuser 만 볼 수 있어
        # e2e 가 실제로 그 계정을 필요로 한다. 이 표면 자체가 내부 토큰과 배포 환경
        # 거부 뒤에 있고, 비밀번호도 dev 고정 상수라 여기서 더 좁혀도 얻는 것이 없다.
        options=frozenset({"username", "password", "superuser"}),
    ),
    "operator-queues": SeedEntry(
        command="seed_e2e_operator_queues",
        options=frozenset({"only", "clear", "prune_other_runs", "run_id"}),
    ),
    "operator-appeal": SeedEntry(
        command="seed_e2e_operator_appeal",
        # 이 시드도 `_own_title_prefix` 로 자기 것을 가르므로 run_id 를 받는다.
        options=frozenset({"rule", "run_id"}),
    ),
    # 심지 않고 읽기만 하는 것도 여기 둔다 — e2e 가 원장을 직접 세는 자리다(#67).
    # 같은 입구를 쓰는 편이 「시드는 HTTP, 조회는 서브프로세스」보다 낫다.
    "ledger-entry-count": SeedEntry(
        command="count_ledger_entries",
        options=frozenset({"contest_id"}),
    ),
}
