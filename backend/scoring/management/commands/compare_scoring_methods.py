"""채점 방식 비교 실험을 돌린다(#1246) — `--confirm` 없이는 예상 호출 수·줄별 비용 범위·하루 상한·남은 돈만 찍는다.

    python manage.py compare_scoring_methods --contest 3 --repeat 3 --limit-submissions 16
    python manage.py compare_scoring_methods --contest 3 --rows agent:claude-sonnet-5-5,self_loop:gpt-4.1-mini --repeat 3 --confirm

같은 인자로 다시 부르면 같은 실험(이름)의 남은 칸만 돈다 — 하루 상한에 멈춘 뒤 이어 가는 길이다. `--name` 을 같게 주면
회차·건수를 늘려 이어 갈 수 있다(먼저 `--limit-submissions 2 --repeat 1` 로 단가를 재고, 같은 이름으로 전체를 돌린다).
운영 표(`Score`·`AgentRun`·`ScoreCorrection`·순위·지급)는 쓰지 않는다. 절차는 `docs/ops/scoring-experiment.md`.

에이전트·우리 루프 줄은 실행기(`agent-grader:8003`)에 닿는 컨테이너(운영은 celery-worker)에서 돌린다. `--confirm` 이면
칸을 만들기 전에 실행기에 한 번 닿아 보고, 못 닿으면 한 칸도 돌지 않고 0 아닌 코드로 끝난다(#1257). 인프라 실패 칸
(닿지 못함·바쁨·토큰 거절·상한 429)은 결과로 남기지 않고 같은 인자로 다시 부르면 다시 돈다 — 연속 3칸이면 멈춘다.
"""

from __future__ import annotations

import getpass
import hashlib
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError, CommandParser

from contests.models import Contest, ContestSubmission
from scoring import experiment as ex
from scoring.models import ScoringExperiment


def _default_name(contest_id: int, rows: list[ex.Row], repeat: int, limit: int | None) -> str:
    digest = hashlib.sha256(",".join(r.name for r in rows).encode()).hexdigest()[:8]
    return f"contest{contest_id}-r{repeat}-n{limit if limit is not None else 'all'}-{digest}"


class Command(BaseCommand):
    help = "채점 방식(한 번 호출·에이전트·우리 루프) × 모델을 같은 제출에 돌려 실험 표에만 남긴다(#1246)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--contest", type=int, required=True)
        parser.add_argument("--rows", default=None, help="방식:모델,… (첫째가 기준 줄). 비면 기본 줄 일곱")
        parser.add_argument("--repeat", type=int, default=3)
        parser.add_argument("--limit-submissions", type=int, default=None)
        parser.add_argument("--name", default=None, help="실험 이름. 비면 인자에서 만든다(같은 인자 = 같은 실험)")
        parser.add_argument("--by", default=None, help="만든 사람(기록용). 비면 OS 사용자")
        parser.add_argument("--confirm", action="store_true", help="이것이 있어야 모델을 부른다")

    def handle(self, *args: object, **options: object) -> None:
        contest_id = int(options["contest"])  # type: ignore[call-overload]  # argparse 가 int 로 줬다
        repeat = int(options["repeat"])  # type: ignore[call-overload]  # argparse 가 int 로 줬다
        limit_raw = options["limit_submissions"]
        limit = int(limit_raw) if limit_raw is not None else None  # type: ignore[call-overload]  # argparse int
        if repeat < 1 or (limit is not None and limit < 1):
            raise CommandError("--repeat 와 --limit-submissions 는 1 이상이다")
        contest = Contest.objects.filter(pk=contest_id).first()
        if contest is None:
            raise CommandError(f"공모전 {contest_id} 이 없다")
        try:
            rows = ex.parse_rows(options["rows"])  # type: ignore[arg-type]  # argparse str|None
        except ex.ExperimentError as exc:
            raise CommandError(str(exc)) from exc
        name = str(options["name"] or _default_name(contest_id, rows, repeat, limit))
        experiment = ScoringExperiment.objects.filter(name=name).first()
        if experiment is not None and (experiment.contest_id != contest_id or experiment.rows != [r.name for r in rows]):
            raise CommandError(f"실험 {name} 은 다른 공모전·줄로 만들어졌다 — 다른 --name 을 쓴다")

        plan = ex.plan(contest, rows, repeat=repeat, limit=limit, experiment=experiment)
        grader = ex.grader_problem() if ex.needs_grader(rows) else None
        self._preview(name, plan, repeat, resumed=experiment is not None)
        if ex.needs_grader(rows):
            self.stdout.write(grader or f"실행기 {ex.GRADER_ADDRESS} 에 닿는다.")
        if not options["confirm"]:
            self.stdout.write("--confirm 이 없어 모델을 부르지 않았다.")
            return
        if not plan.cells:
            self.stdout.write("남은 칸이 없다.")
            return
        if grader is not None and ex.needs_grader([row for _s, row, _n in plan.cells]):
            raise CommandError(f"{grader}. 한 칸도 만들지 않았다.")
        if experiment is not None and (experiment.repeat, experiment.limit_submissions) != (repeat, limit):
            # 같은 실험을 넓혀 이어 간다(먼저 2건 × 1회로 단가를 재고 전체로, 대장 #4345) — 끝난 칸은 다시 돌지 않는다.
            experiment.repeat, experiment.limit_submissions = repeat, limit
            experiment.save(update_fields=["repeat", "limit_submissions"])
        if experiment is None:
            experiment = ScoringExperiment.objects.create(
                name=name, contest=contest, created_by=str(options["by"] or getpass.getuser()),
                rows=[r.name for r in rows], repeat=repeat, limit_submissions=limit, daily_limit_usd=plan.daily_limit_usd,
            )
        self._run(experiment, plan)

    def _preview(self, name: str, plan: ex.Plan, repeat: int, *, resumed: bool) -> None:
        w = self.stdout.write
        w(f"실험 {name}{' (이어서)' if resumed else ''}")
        w(f"제출 {len(plan.submissions)}건 × 회차 {repeat} — 남은 호출 {len(plan.cells)}칸")
        w("줄 | 남은 칸 | 끝난 칸 | 예상 비용(USD) | 칸당 최대")
        for rp in plan.rows:
            w(f"{rp.row.name} | {rp.pending} | {rp.done} | {rp.low_usd:.2f}~{rp.high_usd:.2f} | {rp.per_run_high_usd:.4f}")
        low = sum((rp.low_usd for rp in plan.rows), Decimal(0))
        high = sum((rp.high_usd for rp in plan.rows), Decimal(0))
        w(f"합계 예상 {low:.2f}~{high:.2f} USD")
        w(f"실험 하루 상한 {plan.daily_limit_usd} USD · 오늘 쓴 돈 {plan.spent_today_usd:.4f} · 남은 돈 {plan.remaining_usd:.4f}")
        if plan.daily_limit_usd <= 0:
            w("실험 하루 상한이 0(꺼짐)이다 — 운영자 앱 운영 설정의 AGENT_EXPERIMENT_DAILY_LIMIT_USD 를 정해야 돈다.")

    def _run(self, experiment: ScoringExperiment, plan: ex.Plan) -> None:
        per_run_high = {rp.row: rp.per_run_high_usd for rp in plan.rows}
        inputs: dict[int, ex._Inputs | Exception] = {}
        done = 0  # 남긴 칸
        infra = 0  # 결과로 남기지 않은 칸
        streak = 0  # 연속 인프라 실패
        for index, (submission, row, round_no) in enumerate(plan.cells, start=1):
            remaining = plan.daily_limit_usd - ex.spent_today_experiment_usd()
            if remaining < per_run_high[row]:
                left = len(plan.cells) - done
                self.stdout.write(
                    f"하루 상한에 닿아 멈췄다 — 남은 돈 {max(remaining, Decimal(0)):.4f} < 칸당 최대 {per_run_high[row]:.4f}. "
                    f"남은 칸 {left}개는 같은 명령으로 이어 돈다."
                )
                return
            if submission.pk not in inputs:
                inputs[submission.pk] = self._load(submission)
            run = ex.run_cell(experiment, submission, row, round_no, inputs[submission.pk])
            head = f"[{index}/{len(plan.cells)}] 제출 {submission.pk} {row.name} 회차 {round_no}"
            if isinstance(run, ex.InfraFailure):
                infra += 1
                streak += 1
                self.stdout.write(f"{head}: 인프라 실패(결과로 남기지 않는다) — {run.problem[:200]}")
                if streak >= ex.MAX_CONSECUTIVE_INFRA_FAILURES:
                    raise CommandError(
                        f"인프라 실패가 연속 {streak}칸이라 멈췄다. 남은 칸 {len(plan.cells) - done}개는 같은 명령으로 이어 돈다."
                    )
                continue
            streak = 0
            done += 1
            score = "—" if run.score is None else f"{run.score}"
            self.stdout.write(
                f"{head}: {run.status} {score} ${run.cost_usd:.4f}{(' — ' + run.problem[:120]) if run.problem else ''}"
            )
        tail = f" 인프라 실패 {infra}칸은 남기지 않았다 — 같은 명령으로 다시 돈다." if infra else ""
        self.stdout.write(f"칸 {done}개를 돌렸다.{tail} 보고표: manage.py experiment_report {experiment.name}")

    @staticmethod
    def _load(submission: ContestSubmission) -> ex._Inputs | Exception:
        try:
            return ex.load_inputs(submission)
        except Exception as exc:  # noqa: BLE001 - 입력을 못 받은 제출은 그 칸들을 실패로 남긴다
            return exc
