"""강의실 데모 시드 — 한 강사 계정에 걸어 볼 수 있는 클래스 한 벌을 심는다.

**재시드는 공짜가 아니다 — `ClassroomScore.submission` 이 PROTECT 다.** 그래서
`Class` 를 그냥 지우면 `ProtectedError` 로 막힌다. 공모전이 #254 에서 겪는 것과
같은 벽이고, 모델 주석도 "그 경로 자체가 막힌다"고 못 박고 있다.

이 명령은 그 벽을 **자기가 심은 행에 한해서만** 넘는다. 지우기 전에
`[데모]` 로 시작하는 그 강사의 Class 에 달린 `ClassroomScore` 를 QuerySet 으로
먼저 걷는다 — 모델의 append-only 가드는 인스턴스 `delete()` 에 걸려 있고
QuerySet 경로는 막지 않기 때문이다.

**이것을 일반적인 우회로 쓰지 마라.** append-only 가 지키려는 것은 사람이 낸
제출에 대한 판정의 감사 추적이다. 여기서 지우는 것은 이 시드가 방금 지어낸
행이고(실제 채점이 돈 적이 없다, `model_version` 이 그렇게 적혀 있다), 범위는
`[데모]` 접두어를 가진 그 강사의 클래스로 닫혀 있다. 실데이터의 Score 는
어떤 경로로도 이 명령에 닿지 않는다.

**채점을 실제로 돌리지 않는다.** `ClassroomScore` 행을 직접 만든다 — 데모를 심는
데 강사의 OpenAI 키를 쓰고 토큰 예산을 깎을 이유가 없고, 심는 사람이 통과·미통과를
의도대로 배치할 수 있어야 화면의 모든 갈래가 보인다. 같은 이유로 클래스에 OpenAI
키를 넣지 않는다 — 그건 그 강사의 실제 비밀이고 시드가 지어낼 것이 아니다.

**제출은 저장소 형식만 심는다.** 소스 형식은 값이 스토리지 object_key 라, 심으려면
실제 오브젝트를 함께 써야 하고 그러지 않으면 화면이 없는 파일을 가리킨다
(`seed_demo_contests` 가 fake 스토리지로 돌았을 때 겪은 것과 같은 실패다, #253).
소스 형식 문제는 **제출 없이** 심어 「아직 아무도 안 냈다」 상태를 보여준다.

**알림도 심는다**(#341). 채점을 실제로 돌리지 않으니 스캔(`classroom.scoring`)이
알림을 만들 기회가 없고, 그러면 데모 계정으로 알림 화면(#304)을 열어도 늘 비어
있다. 그래서 `ClassroomScore` 를 직접 만드는 그 자리마다 스캔이 부르는 바로 그
알림 함수를 그대로 부른다(`classroom.scoring._notify_submitter_of_score` — 참여자에게
채점 완료, `notifications.services.create_notification` — 강사에게 예산 경고). 문구·
context 모양이 스캔이 실제로 만드는 것과 달라지면 화면의 링크(#329)가 끊기므로,
새로 짓지 않고 그 함수를 재사용한다. 알림 걷기는 Score 걷기와 같은 class_ids 로
닫혀 있다 — 실사용자의 알림에는 닿지 않는다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from notifications.models import Notification, NotificationType
from notifications.services import create_notification
from submissions.models import Submission, SubmissionAsset

from classroom.models import (
    ChecklistItem,
    Class,
    ClassMember,
    ClassroomScore,
    ClassroomSubmission,
    ClassTemplate,
    ClassTemplateProblem,
    ClassTemplateProblemChecklistItem,
    Problem,
    ProblemTemplate,
    ProblemTemplateChecklistItem,
    ProblemTemplateModerationDecision,
    ProblemTemplateReport,
)
from classroom.scoring import _notify_submitter_of_score

DEMO_PREFIX = "[데모]"

#: 시드가 만드는 참여자 계정. 이 접두어로 만들어진 계정만 재시드에서 재사용한다.
_PARTICIPANT_EMAIL_PREFIX = "demo-classroom-"

_REPO = "https://github.com/octocat/Hello-World"


def _participant(index: int, display: str):
    User = get_user_model()
    email = f"{_PARTICIPANT_EMAIL_PREFIX}{index}@example.com"
    user, _ = User.objects.get_or_create(
        email=email, defaults={"username": email, "is_active": True}
    )
    return user, display


class Command(BaseCommand):
    help = (
        "강의실 데모 데이터를 한 강사 계정에 심는다(멱등). "
        "--email 로 강사를 고른다 — 카카오로 로그인해 둔 그 계정이다."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", help="강사로 쓸 계정의 이메일")
        parser.add_argument("--user-id", type=int, help="이메일 대신 사용자 id 로 고른다")
        parser.add_argument(
            "--purge-only",
            action="store_true",
            help="심지 않고 이 강사의 데모 클래스만 걷어낸다",
        )

    def handle(self, *args, **options):
        instructor = self._resolve_instructor(options)

        removed = self._purge(instructor)
        self.stdout.write(f"걷어낸 데모 클래스: {removed}개")
        if options["purge_only"]:
            return

        with transaction.atomic():
            summary = self._seed(instructor)
        self._dispatch_notifications(summary)
        self._report(instructor, summary)

    # ------------------------------------------------------------------ 강사

    def _resolve_instructor(self, options):
        User = get_user_model()
        if options.get("user_id"):
            try:
                return User.objects.get(pk=options["user_id"])
            except User.DoesNotExist as exc:
                raise CommandError(f"사용자 {options['user_id']} 가 없다.") from exc
        email = options.get("email")
        if not email:
            raise CommandError("--email 또는 --user-id 중 하나가 필요하다.")
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist as exc:
            raise CommandError(
                f"{email} 계정이 없다 — 먼저 그 계정으로 한 번 로그인해야 한다."
            ) from exc

    # ------------------------------------------------------------------ 정리

    def _purge(self, instructor) -> int:
        qs = Class.objects.filter(instructor=instructor, name__startswith=DEMO_PREFIX)
        count = qs.count()
        class_ids = list(qs.values_list("id", flat=True))

        # PROTECT 를 먼저 푼다 — 위 모듈 docstring 이 이 한 줄의 근거다.
        # 범위가 이 강사의 `[데모]` 클래스로 닫혀 있다는 것이 그 근거의 전부이므로,
        # 이 필터를 넓히지 마라.
        ClassroomScore.objects.filter(submission__problem__classroom__in=qs).delete()

        # 알림도 같은 class_ids 로 닫혀 있다 — 이 시드가 만든 것이 아니면 어느
        # notification_type 이든 context__class_id 가 이 목록에 들 수 없다(다른
        # 강사·실사용자의 알림은 다른 Class.pk 를 가리킨다). 재시드가 「겹겹이
        # 쌓이지 않는다」는 계약(CLAUDE.md)이 여기서 성립한다.
        Notification.objects.filter(
            notification_type__in=[
                NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING,
                NotificationType.CLASSROOM_SUBMISSION_SCORED,
            ],
            context__class_id__in=class_ids,
        ).delete()

        # 템플릿은 Class 를 가리키지 않는다(공개 시점 사본이다) — 따로 걷는다.
        # 신고와 심판도 템플릿을 PROTECT 로 가리키므로 같은 순서가 필요하다.
        problem_templates = ProblemTemplate.objects.filter(
            published_by=instructor, title__startswith=DEMO_PREFIX
        )
        ProblemTemplateModerationDecision.objects.filter(
            template__in=problem_templates
        ).delete()
        ProblemTemplateReport.objects.filter(template__in=problem_templates).delete()
        problem_templates.delete()
        ClassTemplate.objects.filter(
            published_by=instructor, name__startswith=DEMO_PREFIX
        ).delete()

        qs.delete()
        return count

    # ------------------------------------------------------------------ 심기

    def _seed(self, instructor) -> dict:
        now = timezone.now()
        made = {
            "classes": [],
            "templates": [],
            # 알림 발송은 여기 쌓아 뒀다가 트랜잭션이 커밋된 뒤 `_dispatch_notifications`
            # 가 돌린다 — 이 메서드 자체는 `handle()` 의 `transaction.atomic()` 안에서
            # 돈다(아래 `_dispatch_notifications` 독스트링 참고).
            "score_jobs": [],
            "budget_warning_jobs": [],
        }

        # --- 클래스 1: 진행중, 제출과 채점이 쌓여 있다 -----------------------
        web = Class.objects.create(
            instructor=instructor,
            name=f"{DEMO_PREFIX} 웹 프론트엔드 스터디",
            instructor_display_name="김강사",
            token_budget=2_000_000,
            token_usage_total=1_740_000,  # 임계(80%)를 넘긴 상태 — 경고 화면이 보인다
        )
        members = self._add_members(
            web,
            [(1, "이수민"), (2, "박지호"), (3, "최은영"), (4, "정다은")],
            expelled_index=4,
        )

        p1 = self._problem(
            web,
            "1주차 — 할 일 목록 만들기",
            "할 일을 더하고 지우고 완료 표시할 수 있는 화면을 만드세요.\n\n"
            "저장은 브라우저 안에만 해도 됩니다. 디자인은 자유입니다.",
            [Problem.SubmissionFormat.REPOSITORY],
            Problem.Status.OPEN,
            [
                ("할 일을 추가할 수 있다", True),
                ("할 일을 지울 수 있다", True),
                ("완료 표시가 새로고침 뒤에도 남는다", True),
                ("빈 목록일 때 안내 문구가 있다", False),
            ],
        )
        p2 = self._problem(
            web,
            "2주차 — 검색과 거르기",
            "1주차에 만든 목록에 검색과 「완료만 보기」를 더하세요.",
            [Problem.SubmissionFormat.REPOSITORY],
            Problem.Status.OPEN,
            [
                ("제목으로 검색할 수 있다", True),
                ("완료된 것만 걸러 볼 수 있다", True),
                ("검색어가 없을 때 전체가 보인다", True),
            ],
        )
        self._problem(
            web,
            "3주차 — 서버와 붙이기",
            "아직 쓰는 중입니다.",
            [Problem.SubmissionFormat.SOURCE],
            Problem.Status.DRAFT,
            [("API 로 목록을 받아온다", True)],
        )

        # 이수민: 1주차 두 번 만에 통과, 2주차 미통과 한 번
        self._attempts(p1, members[0], [False, True], made)
        self._attempts(p2, members[0], [False], made)
        # 박지호: 1주차 한 번에 통과
        self._attempts(p1, members[1], [True], made)
        # 최은영: 1주차 세 번 냈지만 아직 미통과
        self._attempts(p1, members[2], [False, False, False], made)
        # 정다은(내보내진 사람): 1주차 한 번 내고 통과한 기록이 남아 있다
        self._attempts(p1, members[3], [True], made)

        self._maybe_notify_budget_warning(web, made)
        made["classes"].append(web)

        # --- 클래스 2: 진행중, 아직 아무도 안 냈다 --------------------------
        py = Class.objects.create(
            instructor=instructor,
            name=f"{DEMO_PREFIX} 파이썬 기초반",
            instructor_display_name="김선생",
        )
        self._add_members(py, [(5, "한지우"), (6, "오세진")])
        self._problem(
            py,
            "숫자 맞추기 게임",
            "1 부터 100 사이의 숫자를 맞추는 게임을 만드세요. "
            "너무 큼·너무 작음을 알려주고, 몇 번 만에 맞혔는지 보여주세요.",
            [Problem.SubmissionFormat.REPOSITORY],
            Problem.Status.OPEN,
            [
                ("무작위로 답을 고른다", True),
                ("너무 큼·작음을 알려준다", True),
                ("시도 횟수를 보여준다", True),
            ],
        )
        made["classes"].append(py)

        # --- 클래스 3: 보관됨 ------------------------------------------------
        done = Class.objects.create(
            instructor=instructor,
            name=f"{DEMO_PREFIX} 2025 가을 부트캠프",
            instructor_display_name="김강사",
            archived_at=now,
        )
        done_members = self._add_members(done, [(7, "서준혁")])
        dp = self._problem(
            done,
            "최종 과제 — 개인 포트폴리오",
            "자기소개와 만든 것들을 담은 한 페이지를 만드세요.",
            [Problem.SubmissionFormat.REPOSITORY],
            Problem.Status.OPEN,
            [("자기소개가 있다", True), ("만든 것이 하나 이상 있다", True)],
        )
        self._attempts(dp, done_members[0], [True], made)
        made["classes"].append(done)

        # --- 공개된 템플릿 둘 -------------------------------------------------
        pt = ProblemTemplate.objects.create(
            published_by=instructor,
            publisher_display_name="김강사",
            title=f"{DEMO_PREFIX} 할 일 목록 만들기",
            description="첫 주차에 쓰기 좋은 문제입니다. 체크리스트까지 함께 갑니다.",
            submission_formats=[Problem.SubmissionFormat.REPOSITORY],
        )
        for order, (label, required) in enumerate(
            [("할 일을 추가할 수 있다", True), ("할 일을 지울 수 있다", True),
             ("빈 목록 안내가 있다", False)]
        ):
            ProblemTemplateChecklistItem.objects.create(
                template=pt, label=label, required=required, order=order
            )
        made["templates"].append(pt)

        ct = ClassTemplate.objects.create(
            published_by=instructor,
            publisher_display_name="김강사",
            name=f"{DEMO_PREFIX} 웹 프론트엔드 8주 과정",
        )
        for order, (title, desc, items) in enumerate(
            [
                ("1주차 — 할 일 목록", "화면 하나로 시작합니다.",
                 [("추가할 수 있다", True), ("지울 수 있다", True)]),
                ("2주차 — 검색과 거르기", "1주차 위에 얹습니다.",
                 [("검색이 된다", True)]),
                ("3주차 — 서버와 붙이기", "API 를 붙입니다.",
                 [("목록을 받아온다", True)]),
            ]
        ):
            ctp = ClassTemplateProblem.objects.create(
                template=ct,
                title=title,
                description=desc,
                submission_formats=[Problem.SubmissionFormat.REPOSITORY],
                order=order,
            )
            for i, (label, required) in enumerate(items):
                ClassTemplateProblemChecklistItem.objects.create(
                    problem=ctp, label=label, required=required, order=i
                )
        made["templates"].append(ct)

        return made

    # --------------------------------------------------------------- 도우미

    def _add_members(self, class_obj, people, expelled_index=None):
        made = []
        for index, display in people:
            user, name = _participant(index, display)
            member = ClassMember.objects.create(
                classroom=class_obj, user=user, display_name=name
            )
            if expelled_index is not None and index == expelled_index:
                member.expelled_at = timezone.now()
                member.save(update_fields=["expelled_at"])
            made.append(member)
        return made

    def _problem(self, class_obj, title, description, formats, status, items):
        problem = Problem.objects.create(
            classroom=class_obj,
            title=title,
            description=description,
            submission_formats=formats,
            status=status,
            order=class_obj.problems.count(),
        )
        for order, (label, required) in enumerate(items):
            ChecklistItem.objects.create(
                problem=problem, label=label, required=required, order=order
            )
        return problem

    def _attempts(self, problem, member, outcomes, made):
        """`outcomes` 의 각 원소가 그 시도의 통과 여부다. 알림은 바로 보내지
        않고 `made["score_jobs"]` 에 쌓는다 — `_dispatch_notifications` 독스트링
        참고."""
        items = list(problem.checklist_items.all())
        for i, passed in enumerate(outcomes, start=1):
            submission = ClassroomSubmission.objects.create(
                user=member.user,
                product=Submission.Product.CLASSROOM,
                problem=problem,
                member=member,
                attempt_number=i,
            )
            SubmissionAsset.objects.create(
                submission=submission,
                kind=SubmissionAsset.Kind.REPOSITORY,
                value=_REPO,
            )
            score = ClassroomScore.objects.create(
                submission=submission,
                model_version="gpt-4.1-mini (데모 시드가 심은 값 — 실제 채점이 아니다)",
                prompt="(데모 시드는 채점을 돌리지 않는다)",
                reasoning=[
                    {
                        "checklist_item_id": item.id,
                        "is_met": passed or not item.required,
                        "reasoning": (
                            "충족했다." if (passed or not item.required) else "아직 확인되지 않았다."
                        ),
                    }
                    for item in items
                ],
                # 문법 검사 기본 항목(#408) — 이 시드는 실제 파싱을 돌리지
                # 않으므로(채점 자체를 돌리지 않는다), 원하는 통과 여부와
                # 같은 값으로 지어낸다. `problem.syntax_check_enabled`가
                # 기본으로 켜져 있어 이 값이 없으면 `_is_score_passed`가
                # 필수 항목을 다 채웠어도 미통과로 본다 — 데모의 "통과" 시도가
                # 실제로 통과로 보이려면 이 칸도 함께 채워야 한다.
                syntax_check_result={
                    "is_met": passed,
                    "reasoning": (
                        "파이썬 표준 파서로 구문 오류가 발견되지 않았습니다."
                        if passed
                        else "(데모 시드가 미통과로 표시한 값 — 실제 문법 검사가 아니다)"
                    ),
                    "judged_by": "parser",
                    "findings": [],
                },
            )
            made["score_jobs"].append((submission, score, items))

    def _maybe_notify_budget_warning(self, class_obj: Class, made) -> None:
        """`classroom.scoring._record_token_usage` 가 예산 경고를 보내는 것과 같은
        조건이다 — 그 함수는 실제 채점 뒤 토큰을 누적하며 판정하는데, 이 시드는
        채점을 돌리지 않고 `token_usage_total` 을 미리 심으므로 여기서 한 번만
        같은 조건을 확인한다(#341). 알림 자체는 바로 보내지 않고
        `made["budget_warning_jobs"]` 에 쌓는다 — `_dispatch_notifications`
        독스트링 참고. `token_budget_warning_sent_at` 을 채우는 것은 순수한
        모델 저장이라 트랜잭션 안에서 해도 안전하다 — 미루는 것은 알림 발송
        (`create_notification`) 뿐이다."""

        if class_obj.token_budget is None:
            return
        if class_obj.token_budget_warning_sent_at is not None:
            return
        if (
            class_obj.token_usage_total * 100
            < class_obj.token_budget * class_obj.token_budget_warning_threshold_percent
        ):
            return

        class_obj.token_budget_warning_sent_at = timezone.now()
        class_obj.save(update_fields=["token_budget_warning_sent_at"])
        made["budget_warning_jobs"].append(class_obj)

    # ---------------------------------------------------------------- 알림

    def _dispatch_notifications(self, made: dict) -> None:
        """`_seed` 가 쌓아 둔 알림 job 을 실제로 만든다 — 반드시 `_seed` 를 감싼
        `transaction.atomic()` 이 끝난(커밋된) **뒤**에 불러야 한다.

        `_notify_submitter_of_score`·`create_notification` 은 실패해도 예외를
        호출자에게 흘리지 않는다(`notifications.services.notify_safely`). 그런데
        그 삼킴은 파이썬 레벨일 뿐이다 — 이 호출이 `transaction.atomic()` **안**에서
        일어나면, 실패한 SQL 이 postgres 트랜잭션 자체를 이미 깨뜨린 채로 예외만
        삼켜져, 바로 다음 쿼리가 그 트랜잭션과 전혀 무관한 이유로 죽는다(원인을
        알 수 없는 오류로 보인다 — #341 코드리뷰 지적). 실제 스캔
        (`classroom.scoring.score_classroom_submission_once`·`_finalize_platform_failure`)
        도 이 두 알림 호출 모두 `transaction.atomic()` 밖에서 부른다 — 그 관례를
        그대로 따라, `_seed` 안에서는 job 만 쌓고 여기서 트랜잭션 밖에 실제로
        내보낸다."""

        for submission, score, items in made["score_jobs"]:
            _notify_submitter_of_score(submission, score, items)
        for class_obj in made["budget_warning_jobs"]:
            create_notification(
                recipient=class_obj.instructor,
                notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING,
                context={
                    "class_id": class_obj.id,
                    "class_name": class_obj.name,
                    "token_usage_total": class_obj.token_usage_total,
                    "token_budget": class_obj.token_budget,
                },
            )

    # ---------------------------------------------------------------- 보고

    def _report(self, instructor, made):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"강사: {instructor.email} (id={instructor.pk})"))
        for c in made["classes"]:
            state = "보관됨" if c.archived_at else "진행중"
            self.stdout.write(
                f"  클래스 {c.pk} [{state}] {c.name} — 문제 {c.problems.count()}개 · "
                f"참여자 {c.members.count()}명"
            )
            self.stdout.write(f"    가입 링크: /join/{c.join_code}")
        for t in made["templates"]:
            label = getattr(t, "title", None) or t.name
            self.stdout.write(f"  템플릿 {label} — /class-templates/{t.share_code}"
                              if isinstance(t, ClassTemplate)
                              else f"  템플릿 {label} — /templates/{t.share_code}")
        self.stdout.write("")
        self.stdout.write("OpenAI 키는 심지 않았다 — 실제 채점을 돌리려면 클래스 설정에서 직접 넣는다.")
