"""채점 방식 실험의 재료 사본을 운영에서 꺼낸다(#1262) — 강의실 제출을 가명으로, 파일 하나(tar.gz, 0600)에.

    python manage.py export_experiment_material --classroom-submissions 101,102,103 --name cls-2611 --out cls-2611.tar.gz

읽기만 한다(운영 DB·저장소에 쓰지 않는다). 화면에는 담은 건수와 파일 크기만 찍는다. 절차는 `docs/ops/scoring-experiment.md`.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from classroom.experiment_material import collect
from core import experiment_material as em
from core.clock import Clock


def _ids(text: str) -> list[int]:
    try:
        ids = [int(p) for p in text.split(",") if p.strip()]
    except ValueError as exc:
        raise CommandError("--classroom-submissions 는 쉼표로 이은 제출 번호다") from exc
    if not ids or len(set(ids)) != len(ids):
        raise CommandError("--classroom-submissions 가 비었거나 같은 번호가 두 번 있다")
    return ids


def _skipped_line(skipped: dict[str, list[int]]) -> str:
    if not skipped:
        return ""
    total = sum(len(v) for v in skipped.values())
    parts = ", ".join(f"{reason} {len(v)}({','.join(map(str, v))})" for reason, v in skipped.items())
    return f"건너뜀 {total}건 — {parts}"


class Command(BaseCommand):
    help = (
        "강의실 제출을 채점 방식 실험의 가명 사본(tar.gz, 0600)으로 꺼낸다(#1262) — 읽기만 한다. "
        "운영 서버에 남은 export 파일은 work 로 옮긴 뒤 지운다(대장)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--classroom-submissions", required=True, help="강의실 제출 번호, 쉼표로")
        parser.add_argument("--name", required=True, help="실험 재료 이름 — 가명의 솔트이자 개발 환경의 폴더 이름")
        parser.add_argument("--out", required=True, help="쓸 파일(있으면 거절)")

    def handle(self, *args: object, **options: object) -> None:
        ids = _ids(str(options["classroom_submissions"]))
        name = str(options["name"])
        try:
            items, skipped = collect(ids, name=name)
            if not items:
                raise em.MaterialError("꺼낼 수 있는 제출이 없다 — " + (_skipped_line(skipped) or "건너뜀 0건"))
            size = em.write(Path(str(options["out"])), name=name, exported_at=Clock.now(), items=items)
        except em.MaterialError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{len(items)}건 · {size} 바이트")
        if skipped:
            self.stdout.write(_skipped_line(skipped))
