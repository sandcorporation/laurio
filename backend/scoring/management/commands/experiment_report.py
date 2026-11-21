"""채점 방식 비교 실험의 보고표(#1246) — 줄마다 기준 줄(첫째 줄)과 견준 숫자, 통과 기준 넷, 표본 수와 한계.

    python manage.py experiment_report contest3-r3-n16-1a2b3c4d               # 마크다운
    python manage.py experiment_report contest3-r3-n16-1a2b3c4d --format csv  # CSV
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError, CommandParser

from scoring.experiment_report import RunRow, limits_note, report_rows, to_csv, to_markdown
from scoring.models import ScoringExperiment


class Command(BaseCommand):
    help = "채점 방식 비교 실험 하나의 보고표를 마크다운 또는 CSV 로 찍는다(#1246)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("experiment")
        parser.add_argument("--format", choices=["md", "csv"], default="md")

    def handle(self, *args: object, **options: object) -> None:
        experiment = ScoringExperiment.objects.filter(name=options["experiment"]).first()
        if experiment is None:
            raise CommandError(f"실험 {options['experiment']} 이 없다")
        runs = [
            RunRow(
                submission_id=r.submission_id,
                row=r.row,
                round=r.round,
                status=r.status,
                score=float(r.score) if r.score is not None else None,
                evidence_offered=r.evidence_offered,
                evidence_real=r.evidence_real,
                cost_usd=Decimal(r.cost_usd),
                duration_seconds=r.duration_seconds,
            )
            for r in experiment.runs.all()
        ]
        baseline = experiment.rows[0] if experiment.rows else ""
        reports = report_rows(runs, baseline=baseline)
        if options["format"] == "csv":
            self.stdout.write(to_csv(reports), ending="")
            return
        notes = [f"공모전 {experiment.contest_id} · 기준 줄 {baseline}", *limits_note(reports, repeat=experiment.repeat)]
        self.stdout.write(to_markdown(f"채점 방식 비교 — {experiment.name}", reports, notes), ending="")
