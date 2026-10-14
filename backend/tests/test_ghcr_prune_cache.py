"""빌드 캐시 정리가 옛 이름의 캐시 태그를 지우고 지금 이름의 것은 남기는지 (#727).

#711·#712 로 빌드 캐시 이름이 `codemit-buildcache:<앱>-staging/-prod` 에서 `<서비스>-<아키텍처>` 로
바뀌었다. 정리 잡(`Jenkinsfile.ghcr-prune` → `scripts/ci/ghcr_prune.py`)은 캐시를 갱신 순서로만 잘랐는데,
2026-10-15 ghcr 실측은 살아 있는 태그가 열둘(여섯 × 둘)이라 `--keep-cache 10` 이 드물게 굽는 search·
pgbouncer 의 캐시를 지우고, 옛 이름 여섯은 그보다 최근에 갱신돼 남는 모양이었다.
"""

from __future__ import annotations

import importlib.util

from django.conf import settings

_spec = importlib.util.spec_from_file_location(
    "ghcr_prune", settings.BASE_DIR.parent / "scripts" / "ci" / "ghcr_prune.py"
)
ghcr_prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ghcr_prune)


def _version(n: int, updated: str, *tags: str) -> dict:
    return {
        "id": n,
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": updated,
        "metadata": {"container": {"tags": list(tags)}},
    }


def test_cache_keeps_every_live_tag_and_drops_every_old_name():
    # 2026-10-15 ghcr 의 모양 — 지금 이름 여덟이 가장 최근, 옛 이름 여섯, 그 뒤에 search·pgbouncer.
    live_recent = [
        _version(i, f"2026-10-14T23:{i:02d}:00Z", f"{svc}-{arch}")
        for i, (svc, arch) in enumerate(
            (s, a) for s in ("backend", "frontend", "operator", "classroom") for a in ("amd64", "arm64")
        )
    ]
    old_names = [
        _version(20 + i, "2026-10-14T22:21:00Z", f"{app}-{env}")
        for i, (app, env) in enumerate((a, e) for a in ("frontend", "operator", "classroom") for e in ("staging", "prod"))
    ]
    live_rare = [
        _version(40 + i, "2026-10-14T20:00:00Z", f"{svc}-{arch}")
        for i, (svc, arch) in enumerate((s, a) for s in ("search", "pgbouncer") for a in ("amd64", "arm64"))
    ]
    untagged = [_version(60 + i, f"2026-10-13T{i:02d}:00:00Z") for i in range(12)]

    doomed = {v["id"] for v in ghcr_prune.doomed_cache_versions(live_recent + old_names + live_rare + untagged, 10)}

    assert doomed.isdisjoint(v["id"] for v in live_recent + live_rare)
    assert {v["id"] for v in old_names} <= doomed
    # 태그 없는 것은 예전처럼 최근 10개만 남긴다 — 가장 오래된 둘이 지워진다.
    assert {v["id"] for v in untagged} & doomed == {60, 61}
