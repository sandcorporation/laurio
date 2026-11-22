"""채점 방식 비교 실험을 돌린다(#1246) — `--confirm` 없이는 예상 호출 수·줄별 비용 범위·하루 상한·남은 돈만 찍는다.

    python manage.py compare_scoring_methods --contest 3 --repeat 3 --limit-submissions 16
    python manage.py compare_scoring_methods --contest 3 --repeat 1 --limit-submissions 8 --pick spread
    python manage.py compare_scoring_methods --contest 3 --rows agent:claude-sonnet-5-5,self_loop:gpt-4.1-mini --repeat 3 --confirm

같은 인자로 다시 부르면 같은 실험(이름)의 남은 칸만 돈다 — 하루 상한에 멈춘 뒤 이어 가는 길이다. `--name` 을 같게 주면
회차·건수를 늘려 이어 갈 수 있다(먼저 `--limit-submissions 2 --repeat 1` 로 단가를 재고, 같은 이름으로 전체를 돌린다).
운영 표(`Score`·`AgentRun`·`ScoreCorrection`·순위·지급)는 쓰지 않는다. 절차는 `docs/ops/scoring-experiment.md`.

미리 보기는 뽑힌 제출마다 기대 점수(운영 점수)·미충족 수를 찍는다. 기대 점수가 모두 같으면 방식을 가를 수 없어
`--confirm` 을 거절한다 — 비용만 잴 것이면 `--cost-only` 를 같이 준다(#1261, 보고표가 「점수 비교 아님」을 찍는다).

사본 재료(#1262) — 운영 강의실 제출을 가명으로 꺼낸 파일(`export_experiment_material`)을 개발 환경에서 읽는다:

    python manage.py compare_scoring_methods --material ~/.cache/codemit-work/experiment-material/cls/cls.tar.gz --repeat 1
    python manage.py compare_scoring_methods --purge-material cls

사본에서는 운영 DB·저장소·GitHub 를 부르지 않는다. 기대 점수는 사본의 운영 점수(필수 충족 비율)이고, `classroom_call:<모델>`
줄이 강의실 운영 채점과 같은 프롬프트로 한 번 부른다. `--confirm` 이면 이 명령의 직접 호출만 실험 키로 실제 벤더에 나간다
(개발 환경의 어댑터 모드는 그대로 fake). 벤더 키가 빈 줄은 미리 보기에 「키 없음」이고 `--confirm` 이 거절한다.

에이전트·우리 루프 줄은 실행기(`agent-grader:8003`)에 닿는 컨테이너(운영은 celery-worker)에서 돌린다. `--confirm` 이면
칸을 만들기 전에 실행기에 한 번 닿아 보고, 못 닿으면 한 칸도 돌지 않고 0 아닌 코드로 끝난다(#1257). 인프라 실패 칸
(닿지 못함·바쁨·토큰 거절·상한 429)은 결과로 남기지 않고 같은 인자로 다시 부르면 다시 돈다 — 연속 3칸이면 멈춘다.
"""

from __future__ import annotations

import getpass
import hashlib
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from django.core.management.base import BaseCommand, CommandError, CommandParser

from contests.models import Contest, ContestSubmission
from core import experiment_material as em
from core.clock import Clock
from scoring import experiment as ex
from scoring.models import ScoringExperiment


def _default_name(contest_id: int, rows: list[ex.Row], repeat: int, limit: int | None, pick: ex.Pick) -> str:
    digest = hashlib.sha256(",".join(r.name for r in rows).encode()).hexdigest()[:8]
    picked = "-spread" if pick == "spread" else ""  # "id" 는 옛 이름 그대로(같은 인자 = 같은 실험)
    return f"contest{contest_id}-r{repeat}-n{limit if limit is not None else 'all'}{picked}-{digest}"


class Command(BaseCommand):
    help = "채점 방식(한 번 호출·에이전트·우리 루프) × 모델을 같은 제출에 돌려 실험 표에만 남긴다(#1246)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--contest", type=int, default=None)
        parser.add_argument("--material", default=None, help="사본 재료 파일(저장소 밖, 기본 ~/.cache/codemit-work/experiment-material/<이름>/)")
        parser.add_argument(
            "--fill-truth", default=None,
            help="--material 과 함께: 항목별 정답 CSV(material_id,item_id,is_met — 가명 id 뿐, 원문·학생 정보 없음)를 사본에 채우고 끝낸다(모델을 부르지 않는다)",
        )
        parser.add_argument("--purge-material", default=None, help="사본 재료 폴더 <이름> 을 지운다")
        parser.add_argument("--rows", default=None, help="방식:모델,… (첫째가 기준 줄). 비면 기본 줄 일곱")
        parser.add_argument("--repeat", type=int, default=3)
        parser.add_argument("--limit-submissions", type=int, default=None)
        parser.add_argument(
            "--pick", choices=ex.PICKS, default=None,
            help="--limit-submissions 건을 고르는 법: id(id 순 앞 N 건, 기본) · spread(운영 점수 분위로 고르게 N 건)",
        )
        parser.add_argument("--name", default=None, help="실험 이름. 비면 인자에서 만든다(같은 인자 = 같은 실험)")
        parser.add_argument("--by", default=None, help="만든 사람(기록용). 비면 OS 사용자")
        parser.add_argument("--confirm", action="store_true", help="이것이 있어야 모델을 부른다")
        parser.add_argument(
            "--cost-only", action="store_true",
            help="뽑힌 재료의 기대 점수가 모두 같아도 돌린다 — 비용만 잰다(보고표가 점수 비교가 아니라고 찍는다)",
        )

    def handle(self, *args: object, **options: object) -> None:
        given = [k for k in ("contest", "material", "purge_material") if options[k] is not None]
        if len(given) != 1:
            raise CommandError("--contest · --material · --purge-material 중 하나만 준다")
        if options["purge_material"] is not None:
            self._purge(str(options["purge_material"]))
            return
        if options["fill_truth"] is not None and options["material"] is None:
            raise CommandError("--fill-truth 는 --material 과 함께 쓴다")
        if options["material"] is not None and options["fill_truth"] is not None:
            self._fill_truth(Path(str(options["material"])).expanduser(), Path(str(options["fill_truth"])).expanduser())
            return
        if options["material"] is not None:
            self._handle_material(Path(str(options["material"])).expanduser(), options)
            return
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
        pick_raw = options["pick"]
        pick: ex.Pick | None = "spread" if pick_raw == "spread" else ("id" if pick_raw == "id" else None)
        name = str(options["name"] or _default_name(contest_id, rows, repeat, limit, pick or "id"))
        experiment = ScoringExperiment.objects.filter(name=name).first()
        if experiment is not None and (experiment.contest_id != contest_id or experiment.rows != [r.name for r in rows]):
            raise CommandError(f"실험 {name} 은 다른 공모전·줄로 만들어졌다 — 다른 --name 을 쓴다")
        if experiment is not None and pick is not None and pick != experiment.pick:
            raise CommandError(f"실험 {name} 은 --pick {experiment.pick} 로 만들어졌다 — 고른 집합을 바꾸지 않는다")
        if pick is None:
            pick = "spread" if experiment is not None and experiment.pick == "spread" else "id"

        plan = ex.plan(contest, rows, repeat=repeat, limit=limit, experiment=experiment, pick=pick)
        grader = ex.grader_problem() if ex.needs_grader(rows) else None
        picked = ex.materials(contest, plan.submissions)
        same = ex.same_score(picked)
        self._preview(name, plan, repeat, resumed=experiment is not None)
        self._materials(contest, picked, same, spread=pick == "spread" and limit is not None)
        if ex.needs_grader(rows):
            self.stdout.write(grader or f"실행기 {ex.grader_address()} 에 닿는다.")
        if not options["confirm"]:
            self.stdout.write("--confirm 이 없어 모델을 부르지 않았다.")
            return
        if not plan.cells:
            self.stdout.write("남은 칸이 없다.")
            return
        if grader is not None and ex.needs_grader([row for _s, row, _n in plan.cells]):
            raise CommandError(f"{grader}. 한 칸도 만들지 않았다.")
        cost_only = bool(options["cost_only"])
        if same is not None and not cost_only:
            raise CommandError(
                f"뽑힌 제출 {len(picked)}건의 기준 점수가 모두 {same} — 방식을 가를 수 없다. 점수가 갈리는 재료를 고르거나, "
                "비용만 잴 것이면 --cost-only 를 준다. 한 칸도 만들지 않았다."
            )
        if experiment is not None and cost_only and not experiment.cost_only:
            experiment.cost_only = True
            experiment.save(update_fields=["cost_only"])
        if experiment is not None and (experiment.repeat, experiment.limit_submissions) != (repeat, limit):
            # 같은 실험을 넓혀 이어 간다(먼저 2건 × 1회로 단가를 재고 전체로, 대장 #4345) — 끝난 칸은 다시 돌지 않는다.
            experiment.repeat, experiment.limit_submissions = repeat, limit
            experiment.save(update_fields=["repeat", "limit_submissions"])
        if experiment is None:
            experiment = ScoringExperiment.objects.create(
                name=name, contest=contest, created_by=str(options["by"] or getpass.getuser()),
                rows=[r.name for r in rows], repeat=repeat, limit_submissions=limit, pick=pick,
                daily_limit_usd=plan.daily_limit_usd, cost_only=cost_only,
            )
        self._run(experiment, plan)

    def _purge(self, name: str) -> None:
        try:
            gone = em.purge(name)
        except em.MaterialError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"재료 {name} 을 지웠다." if gone else f"재료 {name} 이 없다({em.DEFAULT_ROOT}).")

    def _fill_truth(self, path: Path, csv_path: Path) -> None:
        """사본에 항목별 정답을 채운다(#1288) — 읽고 검사한 뒤에만 쓴다(거절이면 사본은 그대로)."""

        repo_root = Path(settings.BASE_DIR).parent
        try:
            material = em.load(path, repo_root=repo_root)
            truth = em.parse_truth_csv(csv_path.read_text(encoding="utf-8"), material.items)
            filled = em.fill_truth(path, truth, repo_root=repo_root)
        except (em.MaterialError, OSError, UnicodeDecodeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"정답을 채웠다 — 제출 {len(truth)}건(사본 전체 {filled}건에 정답 있음). 모델은 부르지 않았다.")

    def _handle_material(self, path: Path, options: dict[str, object]) -> None:
        repeat = int(options["repeat"])  # type: ignore[call-overload]  # argparse 가 int 로 줬다
        limit_raw = options["limit_submissions"]
        limit = int(limit_raw) if limit_raw is not None else None  # type: ignore[call-overload]  # argparse int
        if repeat < 1 or (limit is not None and limit < 1):
            raise CommandError("--repeat 와 --limit-submissions 는 1 이상이다")
        try:
            material = em.load(path, repo_root=Path(settings.BASE_DIR).parent)
            rows = ex.parse_rows(options["rows"], material=True)  # type: ignore[arg-type]  # argparse str|None
        except (em.MaterialError, ex.ExperimentError) as exc:
            raise CommandError(str(exc)) from exc
        pick: ex.Pick = "spread" if options["pick"] == "spread" else "id"
        manifest = material.manifest
        digest = hashlib.sha256(",".join(r.name for r in rows).encode()).hexdigest()[:8]
        name = str(
            options["name"]
            or f"material-{manifest.name}-r{repeat}-n{limit if limit is not None else 'all'}{'-spread' if pick == 'spread' else ''}-{digest}"
        )
        experiment = ScoringExperiment.objects.filter(name=name).first()
        if experiment is not None and (experiment.material != manifest.name or experiment.rows != [r.name for r in rows]):
            raise CommandError(f"실험 {name} 은 다른 재료·줄로 만들어졌다 — 다른 --name 을 쓴다")
        subjects = ex.material_subjects(material.items, limit, pick)
        plan = ex.plan(None, rows, repeat=repeat, limit=limit, experiment=experiment, pick=pick, subjects=subjects)
        picked = ex.material_materials(subjects)
        same = ex.same_score(picked)
        no_key = ex.rows_without_key(rows)
        stale = em.stale_warning(manifest, Clock.now())
        if stale:
            self.stdout.write(stale)
        self.stdout.write(f"재료 {manifest.name} · {manifest.count}건 · 가져온 날 {timezone.localtime(manifest.exported_at):%Y-%m-%d}")
        self._preview(name, plan, repeat, resumed=experiment is not None, no_key={r.name for r in no_key})
        self._materials(None, picked, same, spread=False)
        grader = ex.grader_problem() if ex.needs_grader(rows) else None
        if ex.needs_grader(rows):
            self.stdout.write(grader or f"실행기 {ex.grader_address()} 에 닿는다.")
        if not options["confirm"]:
            self.stdout.write("--confirm 이 없어 모델을 부르지 않았다.")
            return
        if no_key:
            raise CommandError(
                f"키 없음 줄 {', '.join(r.name for r in no_key)} — 운영 설정의 벤더 키(개발 환경 운영자 앱)를 넣거나 그 줄을 "
                "--rows 에서 뺀다. 한 칸도 만들지 않았다."
            )
        if not plan.cells:
            self.stdout.write("남은 칸이 없다.")
            return
        if grader is not None and ex.needs_grader([row for _s, row, _n in plan.cells]):
            raise CommandError(f"{grader}. 한 칸도 만들지 않았다.")
        cost_only = bool(options["cost_only"])
        if same is not None and not cost_only:
            raise CommandError(
                f"뽑힌 제출 {len(picked)}건의 기준 점수가 모두 {same} — 방식을 가를 수 없다. 점수가 갈리는 재료를 고르거나, "
                "비용만 잴 것이면 --cost-only 를 준다. 한 칸도 만들지 않았다."
            )
        if experiment is None:
            experiment = ScoringExperiment.objects.create(
                name=name, contest=None, material=manifest.name, material_exported_at=manifest.exported_at,
                material_required_ids=sorted({c.id for i in material.items for c in i.checklist if c.grade == "required"}),
                created_by=str(options["by"] or getpass.getuser()), rows=[r.name for r in rows], repeat=repeat,
                limit_submissions=limit, pick=pick, daily_limit_usd=plan.daily_limit_usd, cost_only=cost_only,
            )
        else:
            experiment.repeat, experiment.limit_submissions = repeat, limit
            experiment.cost_only = experiment.cost_only or cost_only
            experiment.save(update_fields=["repeat", "limit_submissions", "cost_only"])
        ex.record_production(experiment, subjects)
        ex.record_truth(experiment, subjects)
        inputs = {s.pk: ex.material_inputs(s.item) for s in subjects}
        with ex.real_vendor():
            self._run(experiment, plan, inputs)

    def _preview(self, name: str, plan: ex.Plan, repeat: int, *, resumed: bool, no_key: set[str] | None = None) -> None:
        w = self.stdout.write
        w(f"실험 {name}{' (이어서)' if resumed else ''}")
        w(f"제출 {len(plan.submissions)}건 × 회차 {repeat} — 남은 호출 {len(plan.cells)}칸")
        w("줄 | 남은 칸 | 끝난 칸 | 예상 비용(USD) | 칸당 최대")
        for rp in plan.rows:
            mark = " | 키 없음" if no_key and rp.row.name in no_key else ""
            w(f"{rp.row.name} | {rp.pending} | {rp.done} | {rp.low_usd:.2f}~{rp.high_usd:.2f} | {rp.per_run_high_usd:.4f}{mark}")
        low = sum((rp.low_usd for rp in plan.rows), Decimal(0))
        high = sum((rp.high_usd for rp in plan.rows), Decimal(0))
        w(f"합계 예상 {low:.2f}~{high:.2f} USD")
        w(f"실험 하루 상한 {plan.daily_limit_usd} USD · 오늘 쓴 돈 {plan.spent_today_usd:.4f} · 남은 돈 {plan.remaining_usd:.4f}")
        if plan.daily_limit_usd <= 0:
            w("실험 하루 상한이 0(꺼짐)이다 — 운영자 앱 운영 설정의 AGENT_EXPERIMENT_DAILY_LIMIT_USD 를 정해야 돈다.")

    def _materials(self, contest: Contest | None, picked: list[ex.Material], same: Decimal | None, *, spread: bool) -> None:
        w = self.stdout.write
        w("제출 | 운영 점수 | 미충족 필수 | 미충족 선택·가산")
        for m in picked:
            w(f"{m.label or m.submission_id} | {m.score} | {m.unmet_required} | {m.unmet_optional}")
        if same is not None:
            w(f"뽑힌 제출 {len(picked)}건의 기준 점수가 모두 {same} — 방식을 가를 수 없다(--confirm 은 --cost-only 와만 돈다).")
        if spread and contest is not None and ex.same_score(ex.materials(contest, ex.eligible_submissions(contest, None))) is not None:
            w("--pick spread: 공모전의 채점된 제출 점수가 모두 같아 점수 분위로 고를 것이 없다 — id 순과 같다.")

    def _run(
        self, experiment: ScoringExperiment, plan: ex.Plan, preloaded: dict[int, ex._Inputs] | None = None
    ) -> None:
        per_run_high = {rp.row: rp.per_run_high_usd for rp in plan.rows}
        inputs: dict[int, ex._Inputs | Exception] = dict(preloaded or {})
        done = 0  # 남긴 칸
        infra = 0  # 결과로 남기지 않은 칸
        streak = 0  # 연속 인프라 실패
        for index, (submission, row, round_no) in enumerate(plan.cells, start=1):
            remaining = plan.daily_limit_usd - ex.spent_today_experiment_usd()
            if remaining < per_run_high[row]:
                left = len(plan.cells) - done
                self.stdout.write(
                    f"하루 상한에 닿아 멈췄다 — 남은 돈 {max(remaining, Decimal(0)):.4f} < 칸당 최대 {per_run_high[row]:.4f}"
                    f"(에이전트·우리 루프는 칸 예산). "
                    f"남은 칸 {left}개는 같은 명령으로 이어 돈다."
                )
                return
            if submission.pk not in inputs:
                assert not isinstance(submission, ex.MaterialSubject)  # 사본 재료는 미리 지어 넘긴다
                inputs[submission.pk] = self._load(submission)
            run = ex.run_cell(experiment, submission, row, round_no, inputs[submission.pk])
            who = submission.material_id if isinstance(submission, ex.MaterialSubject) else submission.pk
            head = f"[{index}/{len(plan.cells)}] 제출 {who} {row.name} 회차 {round_no}"
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
