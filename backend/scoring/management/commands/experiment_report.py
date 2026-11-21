"""채점 방식 비교 실험의 보고표(#1246) — 줄마다 기준 줄(첫째 줄)과 견준 숫자, 통과 기준 넷, 표본 수와 한계.

    python manage.py experiment_report contest3-r3-n16-1a2b3c4d               # 마크다운
    python manage.py experiment_report contest3-r3-n16-1a2b3c4d --format csv  # CSV
    python manage.py experiment_report contest3-r3-n16-1a2b3c4d --bill          # 청구 대조(벤더·모델·UTC 시간 창)
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError, CommandParser

from scoring.experiment import bill_parts, eligible_submissions, is_infra_failure
from contests.models import Requirement
from core import experiment_material as em
from core.clock import Clock
from scoring.experiment_report import (
    COST_ONLY_NOTE,
    NO_TRUTH_NOTE,
    RunRow,
    band_lines,
    bill_lines,
    bill_markdown,
    limits_note,
    report_rows,
    to_csv,
    to_markdown,
)
from scoring.models import ScoringExperiment


class Command(BaseCommand):
    help = "채점 방식 비교 실험 하나의 보고표를 마크다운 또는 CSV 로 찍는다(#1246)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("experiment")
        parser.add_argument("--format", choices=["md", "csv"], default="md")
        parser.add_argument("--bill", action="store_true", help="보고표 대신 청구 대조표(벤더·모델·UTC 날짜·시간 창별 합)")

    def handle(self, *args: object, **options: object) -> None:
        experiment = ScoringExperiment.objects.filter(name=options["experiment"]).first()
        if experiment is None:
            raise CommandError(f"실험 {options['experiment']} 이 없다")
        if options["bill"]:
            notes = [
                "에이전트·우리 루프는 프록시가 요청마다 센 실행 토큰의 합이다(토큰 발급 시각의 UTC 시간 창). 한 번 호출은 "
                "칸 하나를 요청 하나로 센다(칸 기록 시각). OpenAI 의 입력은 캐시 읽기를 포함한다.",
                "결과로 남지 않은 인프라 실패 칸의 토큰도 든다. 같은 제출에 같은 때 다른 실험을 돌렸으면 그 몫도 섞인다.",
            ]
            md = bill_markdown(f"청구 대조 — {experiment.name}", bill_lines(bill_parts(experiment)), notes)
            self.stdout.write(md, ending="")
            return
        runs = [
            RunRow(
                submission_id=r.subject_key,
                row=r.row,
                round=r.round,
                status=r.status,
                score=float(r.score) if r.score is not None else None,
                evidence_offered=r.evidence_offered,
                evidence_real=r.evidence_real,
                cost_usd=Decimal(r.cost_usd),
                duration_seconds=r.duration_seconds,
                verdicts=_verdicts(r.verdicts),
            )
            for r in experiment.runs.all()
            if not is_infra_failure(r.status, r.problem)  # 결과가 아니다(#1257) — 다음 실행에서 다시 돈다
        ]
        baseline = experiment.rows[0] if experiment.rows else ""
        production = sorted({r.row for r in runs if r.row.startswith("운영:")})  # 사본 재료의 운영 판정 줄(#1262)
        if experiment.contest is not None:
            required = frozenset(
                Requirement.objects.filter(contest_id=experiment.contest_id, grade=Requirement.Grade.REQUIRED)
                .values_list("pk", flat=True)
            )
            full = len(eligible_submissions(experiment.contest, None))  # 공모전에서 채점된 제출 전부
            source = f"공모전 {experiment.contest_id}"
        else:
            required = frozenset(int(i) for i in experiment.material_required_ids)
            full = len({r.submission_id for r in runs})
            source = f"사본 재료 {experiment.material}(가명 id)"
        reports = report_rows(runs, baseline=baseline, row_names=[*experiment.rows, *production], required_ids=required)
        repeat = max((r.round for r in runs), default=experiment.repeat)
        if options["format"] == "csv":
            self.stdout.write(to_csv(reports, repeat=repeat, full_submissions=full), ending="")
            return
        stale = (
            experiment.material_exported_at is not None
            and Clock.now() - experiment.material_exported_at > em.STALE_AFTER
        )
        notes = [
            *(["경고: 사본 재료를 가져온 지 7일이 넘었다 — 다 쓴 사본은 --purge-material 로 지운다."] if stale else []),
            *([COST_ONLY_NOTE] if experiment.cost_only else []),
            f"{source} · 기준 줄 {baseline}",
            *limits_note(reports, repeat=repeat),
            NO_TRUTH_NOTE,
        ]
        md = to_markdown(f"채점 방식 비교 — {experiment.name}", reports, notes, repeat=repeat, full_submissions=full)
        if production:
            md += band_lines(runs, production_row=production[0], row_names=[*experiment.rows, *production[1:]])
        self.stdout.write(md, ending="")


def _verdicts(raw: object) -> tuple[tuple[int, bool], ...]:
    """칸 기록의 판정(`[{requirement_id, met, …}]`)을 (요구사항 id, 충족)으로 — 꼴이 다른 항목은 건너뛴다."""

    out = []
    for item in raw if isinstance(raw, list) else []:
        rid = item.get("requirement_id") if isinstance(item, dict) else None
        if isinstance(rid, int) and isinstance(item.get("met"), bool):
            out.append((rid, item["met"]))
    return tuple(out)
