"""e2e 를 무엇을, 몇 조각으로 돌지 — 바뀐 파일 → 앱 폴더 → 조각(#1089, spec #1079).

    python3 scripts/ci/e2e_plan.py --base <기준 커밋>   # PR: 바뀐 앱의 시험만
    python3 scripts/ci/e2e_plan.py --all                # 매시 main(e2e.yml): 전부 — 병합 대기열은 e2e 를 돌지 않는다(#1111)

시험 파일은 `frontend/e2e/<앱>/`(공개), `frontend/e2e/operator/<앱>/`(운영자), `frontend/e2e/classroom/`(강의실, 앱 `classroom`)에
둔다. 폴더 이름이 앱 표시다 — `backend/app_deps.toml` 의 앱 이름이거나 `frontend`(백엔드 앱이 없는 화면·BFF 시험).
`backend/**/tests/**` 는 e2e 를 고르지 않는다(#1110). 바뀐 백엔드 앱 → `scripts/app_deps.py` 의 `affected` 가 고른 앱들의 폴더. 앞단(frontend/·operator/·classroom/)이 바뀌면 그
앱의 시험 전부, 시험 폴더만 바뀌면 그 폴더만, 그 밖(공유 시험 도우미·설정·워크플로·packages·루트)은 전부.

출력(줄마다 `KEY=값`): `E2E=0|1`, `MATRIX={"include":[{"name","project","paths","seconds"}…]}`. 폴더의 시험 파일을
**기록된 시험 시간**으로 조각에 나눠 담는다(#1112, `shards`) — 조각마다 실행기가 하나라 나란히 돈다. 기록은
`--durations <파일>`(계획 잡이 복원한 매시 기록, 없거나 비면 저장소의 씨앗) — 읽는 법·갱신은 `e2e_durations.py`.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_deps import affected, load_table  # noqa: E402
from e2e_durations import read_record  # noqa: E402
from paths import kind  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "frontend" / "e2e"
PSEUDO_APP = "frontend"  # 백엔드 앱이 없는 시험 — 앞단이 바뀔 때만 돈다
PROJECTS = ("public", "operator", "classroom")
#: 조각 하나가 맡을 시험 시간(기록 기준, 초). 기록 합 ~130초 → 전부면 MAX_SHARDS. 층 캐시가 찬 뒤(#1116) 조각 하나의
#: 시험 밖 준비(체크아웃·캐시 복원·굽기·띄우기·정리)가 121~187초(평균 149초)이고 시험은 조각당 12~25초다. 그 준비 표본으로
#: 조각 수를 시뮬레이션하면 8→5조각에서 e2e 끝 중앙값이 +4초(p90 +6초)인데 e2e 실행기 시간은 ~34% 준다 — 그래서 25초·5조각.
SHARD_SECONDS = 25.0
MAX_SHARDS = 5
TEST_CALL = re.compile(r"^\s*test(?:\.[a-z]+)*\(", re.MULTILINE)



def folders() -> dict[str, dict[str, dict[str, int]]]:
    """project → {앱: {시험 파일(frontend 기준): 시험 수}}. 시험 파일이 있는 폴더만."""

    out: dict[str, dict[str, dict[str, int]]] = {"public": {}, "operator": {}, "classroom": {}}
    for spec in sorted(E2E.rglob("*.spec.ts")):
        rel = spec.relative_to(E2E).parts
        count = len(TEST_CALL.findall(spec.read_text(encoding="utf-8")))
        project, app = ("classroom", "classroom") if rel[0] == "classroom" else ("operator", rel[1]) if rel[0] == "operator" else ("public", rel[0])
        out[project].setdefault(app, {})[spec.relative_to(ROOT / "frontend").as_posix()] = count
    return out


def select(changed: list[str], table: dict, present: dict[str, dict[str, dict[str, int]]]) -> dict[str, set[str]]:
    """바뀐 파일 → project → 돌 앱 폴더 집합."""

    everything = {p: set(apps) for p, apps in present.items()}
    picked: dict[str, set[str]] = {p: set() for p in present}
    backend: list[str] = []
    for f in changed:
        if kind(f) == "docs":
            continue
        if kind(f) == "backend":
            if "tests" not in f.split("/")[1:-1]:  # 백엔드 시험 파일은 화면 시험이 기대지 않는다 — 건너뛴다
                backend.append(f)
        elif f.startswith("frontend/e2e/classroom/") and not f.startswith("frontend/e2e/classroom/lib/"):
            picked["classroom"].add("classroom")
        elif f.startswith("frontend/e2e/operator/"):
            rest = f.split("/")[3:]
            if len(rest) > 1 and rest[0] in present["operator"]:
                picked["operator"].add(rest[0])
            else:
                return everything
        elif f.startswith("frontend/e2e/") and f.count("/") >= 3 and f.split("/")[2] in present["public"]:
            picked["public"].add(f.split("/")[2])
        elif f.startswith("frontend/") and not f.startswith("frontend/e2e/"):
            picked["public"] |= everything["public"]
        elif f.startswith("operator/"):
            picked["operator"] |= everything["operator"]
        elif f.startswith("classroom/"):
            picked["classroom"] |= everything["classroom"]
        else:  # 공유 시험 도우미·설정·워크플로·packages·루트
            return everything
    if backend:
        apps = affected(backend, table)
        if apps is None:
            return everything
        for project, names in present.items():
            picked[project] |= {a for a in names if a in apps}
    return picked


def costs(record: Mapping[str, float], present: Mapping[str, Mapping[str, Mapping[str, int]]]) -> dict[str, float]:
    """시험 파일 → 기록된 시간(초). 기록에 없는 파일(새 시험)은 지금 있는 파일의 기록 평균 — 0 이나 한 조각에 몰리지 않게."""

    every = [f for apps in present.values() for files in apps.values() for f in files]
    known = [record[f] for f in every if f in record]
    default = sum(known) / len(known) if known else 1.0
    return {f: record.get(f, default) for f in every}


def shards(present: Mapping[str, Mapping[str, Mapping[str, int]]], chosen: Mapping[str, set[str]], cost: Mapping[str, float]) -> list[dict[str, str]]:
    """고른 폴더의 시험 파일을 기록된 시간으로 조각에 나눈다(#1112).

    조각 수는 시간 합을 SHARD_SECONDS 로 나눈 것(프로젝트 수 ~ MAX_SHARDS). 조각 하나는 프로젝트 하나만 돌므로(e2e.sh 의
    CODEMIT_E2E_TARGETS) 프로젝트마다 한 조각에서 시작해, 조각당 시간이 가장 긴 프로젝트에 하나씩 더 준다. 프로젝트
    안에서는 긴 파일부터 가장 가벼운 조각에(같으면 앞 조각) — 같은 파일·기록이면 어디서나 같은 조각이 나온다.
    """

    files = {p: sorted(f for a in chosen[p] for f in present[p][a]) for p in PROJECTS}
    load = {p: sum(cost[f] for f in files[p]) for p in PROJECTS}
    live = [p for p in PROJECTS if files[p]]
    if not live:
        return []
    total = max(len(live), min(MAX_SHARDS, math.ceil(sum(load.values()) / SHARD_SECONDS)))
    count = dict.fromkeys(live, 1)
    while sum(count.values()) < total:
        room = [p for p in live if count[p] < len(files[p])]
        if not room:
            break
        grow = max(room, key=lambda p: (load[p] / count[p], -PROJECTS.index(p)))
        count[grow] += 1
    out: list[dict[str, str]] = []
    for p in live:
        bins: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(count[p])]
        for f in sorted(files[p], key=lambda f: (-cost[f], f)):
            i = min(range(count[p]), key=lambda k: (bins[k][0], k))
            bins[i] = (bins[i][0] + cost[f], bins[i][1] + [f])
        out += [
            {"name": f"{p}-{i + 1}", "project": p, "paths": " ".join(sorted(b)), "seconds": f"{t:.0f}"}
            for i, (t, b) in enumerate(x for x in bins if x[1])
        ]
    return out


def plan(changed: list[str] | None, record: Mapping[str, float] | None = None) -> dict[str, list[dict[str, str]]]:
    present = folders()
    if changed is None:
        chosen = {p: set(apps) for p, apps in present.items()}
    else:
        chosen = select(changed, load_table(), present)
    return {"include": shards(present, chosen, costs(read_record() if record is None else record, present))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="기준 커밋 — 이 뒤로 바뀐 파일만 본다")
    parser.add_argument("--all", action="store_true", help="전부(매시 main, e2e.yml)")
    parser.add_argument("--durations", type=Path, help="시간 기록(매시 e2e.yml 이 캐시에 둔 것) — 없으면 씨앗 기록")
    args = parser.parse_args()
    record = read_record(args.durations)
    if args.all or not args.base:
        matrix = plan(None, record)
    else:
        diff = subprocess.run(["git", "diff", "--name-only", args.base, "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True)
        matrix = plan(diff.stdout.split(), record)
    print(f"E2E={1 if matrix['include'] else 0}")
    print("MATRIX=" + json.dumps(matrix, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
