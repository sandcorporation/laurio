"""Classroom 도메인 모델 (CONTEXT.md 「강의실」, ADR-0037, #278/#282/#283).

강사 한 명이 열고 참여자를 모으는 학습 단위다. 상금도 결제도 본인확인도 없다 —
그래서 `Class`·`Problem`은 `contests.Contest`와 닮았어도 그 모델을 재사용하지
않는다(ADR-0037이 두 도메인의 import 자체를 양방향으로 막는다).

**`Class`는 `User`를 직접 가리킨다** — `accounts.SponsorProfile`도
`accounts.DeveloperProfile`도 쓰지 않는다. 강의실의 강사·참여자는 역할 프로필이
필요 없다(이름은 `ClassMember`가 따로 들 자리라 프로필이 할 일이 없다, CONTEXT.md).
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models

from submissions.models import Submission

from .grading_guidelines import DEFAULT_GRADING_STRICTNESS, GRADING_GUIDELINE_TEXT_MAX_LENGTH
from .scoring_models import DEFAULT_REASONING_EFFORT, DEFAULT_SCORING_MODEL, REASONING_EFFORT_CHOICES


def _generate_join_code() -> str:
    """추측 불가능한 가입 코드(#279). `secrets.token_urlsafe(16)`은 22자라
    URL 세그먼트 하나로 쓰기에 짧고, 링크 자체에는 클래스 이름 등 내용이
    전혀 실리지 않는다 — 무작위 문자열뿐이다."""

    return secrets.token_urlsafe(16)


class Class(models.Model):
    class ScoringKeyStatus(models.TextChoices):
        """채점 키가 저장 시점에 벤더에게 확인된 결과(#354, ADR-0045). 키가
        아예 없는 클래스에는 이 값이 뜻이 없다 — `has_scoring_key()`가 그
        판정을 그대로 맡는다."""

        VERIFIED = "verified", "확인함"
        UNVERIFIED = "unverified", "미검증"
        REJECTED = "rejected", "거부됨"

    #: 이 클래스를 연 강사. `accounts.SponsorProfile`이 아니라 `User`를 바로
    #: 가리킨다 — 프로필을 쓰지 않기로 한 것 자체가 ADR-0037의 합의다.
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="classrooms", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)

    #: 강사가 **이 클래스에서** 불릴 이름(#299) — `ClassMember.display_name`과
    #: 같은 이유로 계정의 표시 이름과 독립이다(회사 수업과 스터디에서 다른
    #: 이름을 쓸 수 있어야 한다). 가입 미리보기에서만 쓰인다: 참여자 명단·
    #: 제출물에서 강사가 보이는 이름은 여전히 `ClassMember.display_name`이다
    #: (강사 본인이 참여자로도 들어와 있을 때 이름이 둘로 갈리는 지점).
    #: 새로 만드는 클래스는 API가 빈 문자열을 거부해 반드시 채워지지만, 이
    #: 필드가 생기기 전에 만들어진 클래스는 마이그레이션이 값을 지어내지
    #: 않아 빈 문자열로 남는다 — 그 경우 가입 미리보기는 이 줄 자체를
    #: 생략한다.
    instructor_display_name = models.CharField(max_length=100, blank=True, default="")

    #: 채점이 실제로 쓰는 강사 본인의 OpenAI 키(#284). `core.crypto.encrypt`로
    #: 암호화된 값만 여기 남는다 — 평문은 저장하지 않는다. 빈 문자열이면
    #: 키가 없다는 뜻이다.
    openai_api_key_encrypted = models.TextField(blank=True, default="")
    #: 마스킹 표시용 마지막 네 자리. **복호화는 채점 요청을 보낼 때만
    #: 한다**는 규율(#284) 때문에, 화면에 보여줄 마스킹은 암호문을 다시 풀지
    #: 않고 저장 시점에 평문에서 떼어 둔 이 값으로만 만든다.
    openai_api_key_last4 = models.CharField(max_length=4, blank=True, default="")
    #: 이 키가 지금 어느 상태인가(#354, ADR-0045) — 저장할 때 벤더에게 실제로
    #: 확인한 결과다. 키가 없는 클래스에는 뜻이 없다(`has_scoring_key()`가
    #: "키 없음"을 따로 판정한다). `REJECTED`가 되면 채점 스캔이 이 클래스를
    #: 후보에서 뺀다(#355) — 새 키를 저장해 통과하거나 미검증으로 저장되면
    #: 이 값이 덮여 다시 후보에 든다.
    openai_api_key_status = models.CharField(
        max_length=10, choices=ScoringKeyStatus.choices, default=ScoringKeyStatus.UNVERIFIED
    )

    #: 이 클래스의 기본 채점 모델(#285, #401). 문제가 자기 값을 갖지 않으면
    #: 이 값을 쓴다 — 그 클래스의 키로 실제로 쓸 수 있는 모델만 저장된다
    #: (`classroom.scoring_model_catalog.get_scoring_model_catalog`로 검증).
    default_model = models.CharField(max_length=50, default=DEFAULT_SCORING_MODEL)

    #: 추론 강도 세 단계(#402, CONTEXT.md 「추론 강도」) — 채점 모델이 추론
    #: 모델(GPT-5 이후)일 때만 뜻이 있다. 문제가 자기 값을 갖지 않으면 이
    #: 값을 쓴다 — `default_model`과 같은 모양. 값 자체는
    #: `classroom.scoring_models.REASONING_EFFORT_CHOICES`(순수 함수 쪽)가
    #: 정한다 — `ScoringKeyStatus`처럼 모델 안에 따로 열거하지 않는다.
    default_reasoning_effort = models.CharField(
        max_length=10, choices=REASONING_EFFORT_CHOICES, default=DEFAULT_REASONING_EFFORT
    )

    #: 가입 링크의 코드(#279). 다시 뽑으면 이 값이 새 무작위 문자열로
    #: 바뀌어 이전 값은 어떤 클래스도 가리키지 않게 된다 — 그래서 별도
    #: 이력 테이블이 필요 없다, 죽은 코드는 그냥 아무 행에도 없는 값이다.
    join_code = models.CharField(max_length=32, unique=True, default=_generate_join_code)

    #: 채점 토큰 예산 상한(#295) — `None`이면 무제한이다. 강사가 정하기
    #: 전까지는 이 기능 자체가 꺼져 있는 것과 같아, 기존 클래스는 전부
    #: 지금처럼 계속 채점된다.
    token_budget = models.PositiveIntegerField(null=True, blank=True, default=None)
    #: 경고 알림을 보낼 임계, 예산 대비 백분율(#295). `token_budget`이 없으면
    #: 쓰이지 않는다.
    token_budget_warning_threshold_percent = models.PositiveIntegerField(default=80)
    #: 이 클래스의 채점이 지금까지 실제로 쓴 토큰 누적합(#295). 성공한
    #: 채점 호출이 끝날 때마다 OpenAI 응답이 보고한 만큼만 더해진다 —
    #: 실패한 호출(인증 오류 등, 토큰을 쓰지 않고 끝난 시도)은 더하지 않는다.
    token_usage_total = models.PositiveIntegerField(default=0)
    #: 경고 임계를 넘겨 강사에게 알림을 보낸 시각(#295). 강사가 `token_budget`을
    #: 바꾸면(새 예산 주기로 본다) 이 값을 지워, 다음 임계 통과에서 다시
    #: 알릴 수 있게 한다 — 그러지 않으면 한 번 경고한 뒤로는 예산을 아무리
    #: 늘려도 다시는 경고가 가지 않는다.
    token_budget_warning_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    #: 강사가 수업을 보관한 시각(#294, 뜻은 #438이 **읽기 전용**으로 넓혔다).
    #: null이면 진행중이다. 보관은 지우는 것이 아니다 — 이 값만 지우면
    #: (되돌리기) 그대로 진행중으로 돌아온다. 새 내용을 만들거나 바꾸는 문은
    #: `classroom.participation.assert_class_mutable`이 한 곳에서 막는다
    #: (가입·제출·이름 바꾸기만 예외로 각 엔드포인트가 직접 본다) — 읽기,
    #: 클래스 설정(이름·강사 이름·키·기본 모델·예산), 보관 되돌리기, 복사해서
    #: 새로 열기, 클래스 삭제, 클래스 템플릿 공개는 이 값과 무관하게 그대로
    #: 연다(CONTEXT.md 「Class」).
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Class(id={self.pk}, name={self.name!r})"

    def token_budget_exhausted(self) -> bool:
        """예산이 없으면(`token_budget is None`) 항상 거짓 — 무제한이다(#295)."""

        return self.token_budget is not None and self.token_usage_total >= self.token_budget

    def has_scoring_key(self) -> bool:
        """이 클래스에 채점에 실제로 쓸 수 있는 키가 있는가(#346) — 공백만
        있어도 없는 것으로 본다. `scoring.score_classroom_submission_once`가
        채점 시점에 확인하는 것과 **정확히 같은 기준**이어야 한다 — 화면의
        `pending_reason`·참여자별 현황 격자가 이 기준과 어긋나면, 실제로는
        채점되지 않는 시도가 "정상적으로 채점을 기다리는 중"으로 잘못
        보인다(bare truthiness는 공백 문자열도 "있다"로 본다)."""

        return bool((self.openai_api_key_encrypted or "").strip())

    def scoring_key_unusable(self) -> bool:
        """지금 이 클래스의 채점이 키 때문에 멈춰 있는가(#355) — 키가 아예
        없거나(`has_scoring_key()`가 거짓) 벤더가 거절해 "거부됨" 상태다.
        `classroom.pending_scoring`(#434)의 스캔 후보 쿼리·채점 직전 확인·
        화면의 `pending_reason`·격자 칸 상태가 모두 이 기준 하나를 따라야
        어긋나지 않는다."""

        return not self.has_scoring_key() or self.openai_api_key_status == self.ScoringKeyStatus.REJECTED


class Problem(models.Model):
    """Class 안의 문제 하나. Contest와 달리 **마감이 없다**(ADR-0039) — 이
    모델에는 마감 필드가 아예 없다. 제출 형식은 소스 또는 저장소뿐이다.

    `status`(초안/열림/숨김, #405)는 여기서 이미 구별되고, 참여자가 실제로
    무엇을 보게 거르는 표면은 `ClassMember`(#280) 위에 선다 — 열린 문제는
    목록에, 숨긴 문제는 낸 적 있는 사람에게만 읽기 전용으로 남는다
    (CONTEXT.md 「Problem」). 숨김에서 초안으로 가는 길은 없다 — 이미 낸
    사람의 기록을 강사가 거둘 수 없기 때문이다.
    """

    class SubmissionFormat(models.TextChoices):
        SOURCE = "source", "소스"
        REPOSITORY = "repository", "저장소"

    class Status(models.TextChoices):
        DRAFT = "draft", "초안"
        OPEN = "open", "열림"
        HIDDEN = "hidden", "숨김"

    class GradingStrictness(models.TextChoices):
        """채점 지침의 네 단계(#386, CONTEXT.md 「채점 지침」) — 세 단계는
        `grading_guidelines.PRESET_GRADING_GUIDELINE_TEXT`에 정해 둔 문장을,
        `CUSTOM`은 `grading_guideline_text`에 담긴 강사의 문장을 그대로
        채점 프롬프트에 싣는다."""

        STRICT = "strict", "엄격"
        NORMAL = "normal", "보통"
        LENIENT = "lenient", "관대"
        CUSTOM = "custom", "직접 입력"

    classroom = models.ForeignKey(Class, related_name="problems", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    #: 강사가 받기로 고른 형식들 — 소스·저장소의 비어 있지 않은 부분집합
    #: (#373, ADR-0042). 예전 단일 `submission_format`을 대체한다 — 빈 목록은
    #: API가 422로 거절해 여기 저장되지 않는다. 둘 다 켜진 문제에서 참여자는
    #: 시도마다 그중 하나를 골라 낸다(`ClassroomSubmissionIn.submission_format`)
    #: — 시도 하나에 자료는 하나다(Out of Scope). 마이그레이션(0003)이 옛
    #: 단일 값을 원소 하나짜리 목록으로 옮겼다 — squash 이후 첫 데이터
    #: 마이그레이션이라 되돌리기 동작도 함께 있다.
    submission_formats = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    #: 클래스 상세에서의 노출 순서. 생성 순서가 아니라 강사가 직접 재배열한다.
    order = models.PositiveIntegerField(default=0)

    #: 이 문제만의 채점 모델(#285). 빈 문자열이면 `classroom.default_model`을
    #: 따른다 — API가 그 둘을 합쳐 `effective_model`로 내려준다. 지난 채점의
    #: 근거는 이 필드가 아니라 그 채점(Score)이 그 시점에 남긴 값이 지킨다 —
    #: 여기를 바꿔도 이미 산출된 판정은 다시 계산되지 않는다.
    model = models.CharField(max_length=50, blank=True, default="")

    #: 벤더가 이 문제의 채점 모델을 그 클래스의 키로 거부한 시각(#403,
    #: CONTEXT.md 「채점 모델」 "그 시도는 채점하지 못한 것으로 남는다") —
    #: null이면 정상이다. `Class.openai_api_key_status`(키 자체의 상태)와는
    #: 다른 사유라 이 값은 Class가 아니라 Problem에 둔다: 문제마다 다른
    #: 모델을 고를 수 있어(`model` 필드), 같은 클래스의 다른 문제는 멀쩡히
    #: 채점될 수 있다. 강사가 이 문제의 모델을 바꾸거나(`model` 필드가
    #: 실린 PATCH) 클래스 기본값을 바꿔 이 문제가 그 값을 물려받으면
    #: (`classroom.api`) 다시 `None`으로 풀려 다음 시도부터 채점 후보에
    #: 든다.
    scoring_model_rejected_at = models.DateTimeField(null=True, blank=True, default=None)

    #: 이 문제만의 추론 강도(#402). 빈 문자열이면 `classroom.
    #: default_reasoning_effort`를 따른다 — `model`/`default_model`과 같은
    #: 모양. 복사(`services.copy_problem_to_class`)·템플릿은 이 값을 옮기지
    #: 않는다(CONTEXT.md 「추론 강도」 "비용 결정은 가져간 사람이 한다") —
    #: `model`과 다른 지점: `copy_problem_to_class`는 `model`은 그대로
    #: 복사하되 이 필드는 만지지 않아 새 행이 기본값("")으로 시작한다.
    reasoning_effort = models.CharField(max_length=10, blank=True, default="")

    #: 채점 지침 단계(#386, CONTEXT.md 「채점 지침」) — 체크리스트 항목을
    #: 얼마나 글자 그대로 따질지. 기본은 「보통」이다: 「hello world 를
    #: 출력하라」에 `hello world!`를 낸 사람을 틀렸다고 하면 학습이 아니라
    #: 받아쓰기가 된다. 지침을 바꿔도 이미 매긴 판정(`ClassroomScore`)은
    #: append-only라 그대로 남는다(ADR-0006) — 새로 들어오는 시도부터
    #: 새 지침을 탄다.
    grading_strictness = models.CharField(
        max_length=10,
        choices=GradingStrictness.choices,
        default=DEFAULT_GRADING_STRICTNESS,
    )
    #: `grading_strictness`가 `CUSTOM`일 때만 뜻이 있는 강사의 문장. 그 밖의
    #: 단계에서는 API가 언제나 빈 문자열로 저장한다(#386 AC) — 두 칸이
    #: 어긋난 상태(비-CUSTOM인데 문장이 남아 있는 것)를 구조로 막는다.
    grading_guideline_text = models.CharField(
        max_length=GRADING_GUIDELINE_TEXT_MAX_LENGTH, blank=True, default=""
    )

    #: 문법 검사 기본 항목 「소스에 문법 오류가 없다」의 켜짐 여부(#408,
    #: CONTEXT.md 「문법 검사」). 체크리스트 행(`ChecklistItem`)으로 저장하지
    #: 않는다 — 강사가 문구·필수 여부를 바꿀 수 없는 플랫폼 고정 항목이라
    #: 켜고 끄는 값 하나면 충분하다. 기본은 켜짐이고, 마이그레이션으로
    #: 기존 문제도 켜짐이다(#408 AC). 의사코드처럼 실행되는 코드가 아닌
    #: 문제에서는 강사가 끌 수 있다(#410).
    syntax_check_enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Problem(id={self.pk}, title={self.title!r})"

    def effective_model(self) -> str:
        """실제 채점에 쓰이는 모델(#402, CONTEXT.md 「채점 모델」, #436) — 이
        문제가 자기 값(`model`)을 갖지 않으면 클래스 기본값을 따른다.
        `classroom.api`(문제 응답)와 `classroom.scoring`(채점 호출)이 예전에
        각자 `problem.model or classroom.default_model`을 다시 적던 것을
        이 메서드 하나로 모은다 — 둘이 어긋나면 화면이 말하는 모델과 실제로
        채점에 쓰인 모델이 갈릴 수 있었다."""

        return self.model or self.classroom.default_model

    def effective_reasoning_effort(self) -> str:
        """`effective_model`과 같은 자리(#402, #436). 추론 모델이 아닌 채점
        모델에는 이 값이 뜻이 없지만, 그 판단(`is_reasoning_model_id`)은
        부르는 쪽의 몫으로 남긴다 — 이 메서드는 "이 문제가 쓸 추론 강도
        값이 무엇인가"만 답한다."""

        return self.reasoning_effort or self.classroom.default_reasoning_effort

    def is_score_passed(self, score, checklist_items=None) -> bool:
        """이 채점 하나가 이 문제에서 **통과**인가(#288, CONTEXT.md 「통과」,
        #436) — 필수 항목을 전부 충족했는가. 선택 항목은 판정에 관여하지
        않는다. 이 문제 자신의 문법 검사 설정(`syntax_check_enabled`)을
        직접 읽으므로, 부르는 쪽이 그 값을 따로 넘길 필요가 없다 — 예전에는
        `classroom.api._is_score_passed`가 그 값을 인자로 받았고,
        `classroom.scoring`의 채점 완료 알림은 순환 import를 피해 이 규칙을
        손으로 베꼈다.

        **항상 지금의 체크리스트·문제 설정 기준으로 다시 셈한다** — 저장된
        판정(`score.reasoning`/`score.syntax_check_result`)은 append-only라
        바뀌지 않지만, 필수 항목 여부는 매번 최신 `ChecklistItem.required`
        에서 새로 구한다. 강사가 채점 뒤에 체크리스트를 고치거나(#283이
        허용한다) 기본 항목을 껐다 켰다 해도(#410) 지난 판정 자체는 바뀌지
        않고 이 재계산만 새 기준을 탄다 — 이 모델 docstring의 "달성률만
        새 기준으로 다시 셈된다"가 뜻하는 바로 그 재계산이다.

        `checklist_items`를 주면(이미 불러온 목록) 다시 질의하지 않는다 —
        목록·격자처럼 문제 하나를 여러 시도·여러 참여자에 걸쳐 반복해서
        묻는 자리가 그때마다 체크리스트를 다시 불러오지 않게 하기 위해서다
        (#436 AC "문제 수만큼 질의가 늘지 않는다"). 생략하면
        `self.checklist_items.all()`을 쓴다 — 이미 `prefetch_related`로
        불러왔으면 그 캐시를 그대로 쓴다.

        미채점("pending", `score is None`)이면 항상 거짓이다 — 아직 판정이
        없다."""

        if score is None:
            return False
        items = self.checklist_items.all() if checklist_items is None else checklist_items
        required_item_ids = {item.id for item in items if item.required}
        if not required_item_ids:
            return False
        if self.syntax_check_enabled:
            syntax_result = score.syntax_check_result
            if not syntax_result or not syntax_result.get("is_met"):
                return False
        met_ids = {r["checklist_item_id"] for r in score.reasoning if r["is_met"]}
        return required_item_ids.issubset(met_ids)


class ClassMember(models.Model):
    """한 사람이 한 Class에 속한다는 사실(#280, CONTEXT.md 「ClassMember」).

    가입 링크로 들어올 때 받는 **그 클래스에서 불릴 이름**(`display_name`)을
    든다 — 계정의 표시 이름과 독립이다(회사 수업과 스터디에서 다른 이름을
    쓸 수 있어야 한다). `user`는 `accounts.DeveloperProfile`이 아니라
    `User`를 바로 가리킨다 — `Class.instructor`와 같은 이유(ADR-0037)다.

    강사 본인도 자기 클래스에 들어와 이 모델의 행이 될 수 있다 — 그때를
    구별하는 플래그는 두지 않는다: `classroom.instructor_id == user_id`로
    즉시 판별되므로 중복 상태를 만들 이유가 없다.
    """

    classroom = models.ForeignKey(Class, related_name="members", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="class_memberships", on_delete=models.CASCADE
    )
    display_name = models.CharField(max_length=100)
    joined_at = models.DateTimeField(auto_now_add=True)
    #: 강사가 내보낸 시각(#281). 행을 지우지 않는다 — 지우면 그 사람이 낸
    #: 제출물이 이름을 잃어 "누군가의 제출"이 된다(CONTEXT.md 「ClassMember」).
    #: null이면 아직(또는 다시는) 내보내지지 않았다는 뜻이다. 내보낸 사람이
    #: 새 제출을 못 내는 것은 이 값을 보는 제출 엔드포인트(#286)의 몫이다 —
    #: 이 티켓은 그 신호를 남기는 데까지다.
    expelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["joined_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "user"], name="unique_classroom_member"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ClassMember(classroom_id={self.classroom_id}, user_id={self.user_id})"


class ClassroomSubmission(Submission):
    """`submissions.Submission`의 강의실 자식(#286, ADR-0039) — 부모와 테이블·pk를
    나눠 갖는 다중 테이블 상속이다(`contests.ContestSubmission`과 같은 모양).
    자료(`assets`)는 부모 pk로 그대로 붙는다 — 근거 연결·자가 응답은 이 제품에
    없다(CONTEXT.md 「Problem」).

    **`ContestSubmission`과 달리 유니크 제약이 없다.** Problem에는 마감이
    없고 한 사람이 몇 번이든 다시 내며, 낼 때마다 새 행이 쌓인다 — 두 번째
    제출이 기존 행의 수정이 되는 공모전과 갈리는 지점이다(ADR-0039). 그래서
    `(problem, member)`가 반복돼도 막지 않고, 대신 `attempt_number`가 그
    쌓임에 순서를 매긴다.

    **생성은 언제나 이 클래스를 통해서다** — `contests.ContestSubmission`과
    같은 이유로, `classroom.submission_api`가 유일한 HTTP 생성 경로다.
    """

    problem = models.ForeignKey(Problem, related_name="submissions", on_delete=models.CASCADE)
    member = models.ForeignKey(ClassMember, related_name="submissions", on_delete=models.CASCADE)
    #: 이 참여자가 이 Problem에 낸 몇 번째 시도인가(1부터). CONTEXT.md
    #: 「Problem」의 "제출할 때마다 새 시도가 쌓인다"를 화면과 채점이 셀 수
    #: 있게 값으로 남긴다.
    attempt_number = models.PositiveIntegerField()

    class Meta:
        ordering = ["-attempt_number"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ClassroomSubmission(problem={self.problem_id}, member={self.member_id}, attempt={self.attempt_number})"


class ChecklistItem(models.Model):
    """채점이 보는 항목 하나(#283). `required=True`를 전부 충족하면 **통과**다
    — 문제마다 합격선을 따로 두지 않는다(CONTEXT.md 「통과」). 필수 항목이
    하나도 없으면 통과가 정의되지 않으므로, 그런 문제는 열 수 없다(API에서
    강제한다).

    이미 통과한 사람이 있어도 강사가 언제든 고친다 — 돈이 걸려 있지 않아
    "나중에 낸 사람이 유리해진다"가 성립하지 않는다. 지난 점수는 그대로
    남고 달성률만 새 기준으로 다시 셈된다(CONTEXT.md 「달성률」) — 그 셈은
    Score가 생기는 채점 티켓의 몫이고, 여기서는 그 사실을 화면이 미리
    말해 줄 수 있도록 `Problem.status`만 정확히 유지한다.
    """

    problem = models.ForeignKey(Problem, related_name="checklist_items", on_delete=models.CASCADE)
    label = models.CharField(max_length=200)
    required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ChecklistItem(id={self.pk}, label={self.label!r})"


class ClassroomScore(models.Model):
    """`ClassroomSubmission` 하나에 대한 채점 스냅샷(#287) — `scoring.Score`와
    같은 규율을 따르되(ADR-0006 「제출물당 하나, 재채점 없음」) **다른 테이블이다**.
    `scoring`은 공모전 가족이라 강의실이 그 모델을 가리킬 수 없다(ADR-0037) —
    스키마가 닮았어도 앱 경계가 공유를 막는다(ADR-0039).

    `scoring.Score`가 상속하는 `ledger.AppendOnlyModel`도 같은 이유로 쓸 수
    없다(`ledger`도 공모전 가족이다) — 그래서 `save()`를 직접 막는다. `ledger`의
    QuerySet 단위 `update()`/`delete()` 차단까지는 두지 않는다.

    **채점 결과가 지워지는 경로는 정확히 하나, ADR-0050이 연다.** 강사가 자기
    문제를 지우면서 그 문제 × 강사 자신의 시도에 달린 채점만 `classroom.api.
    delete_problem`이 QuerySet `delete()`로 먼저 걷는다 — `submission`이
    `on_delete=PROTECT`라 그러지 않으면 `Class`→`Problem`→`ClassroomSubmission`
    캐스케이드가 `ProtectedError`로 막힌다. 그 필터(「그 문제 × 강사 자신」)가
    이 우회의 근거 전부이므로 넓히지 않는다 — 참여자의 시도에 달린 채점은 어떤
    경로로도 지워지지 않는다. 남는 위험은 이 모델 자신의 실수뿐이라 인스턴스
    단위 가드로 충분하다.
    """

    # related_name이 "score"가 아니라 "classroom_score"다 — `ClassroomSubmission`이
    # `submissions.Submission`을 다중 테이블 상속하고, 그 부모를 `scoring.Score`도
    # `related_name="score"`로 가리켜(공모전 자식 쪽) 이름이 그대로면 Django가
    # 역참조 이름 충돌(fields.E304/E305)로 부팅을 거부한다 — 두 Score가 같은
    # 부모 테이블 계층을 가리키는 것이 원인이라, 다른 값을 주는 것 말고는 피할
    # 방법이 없다.
    submission = models.OneToOneField(
        ClassroomSubmission, related_name="classroom_score", on_delete=models.PROTECT
    )
    #: 실제로 쓰인 LLM 모델 식별자. 채점이 실패 상한에 도달해 플랫폼이 자동으로
    #: 미달 처리했을 때는 `submissions.scoring_basis.PLATFORM_FAILURE_MODEL_VERSION`
    #: 이 들어간다(#287, ADR-0031과 같은 규율) — 강의실에는 마감이 없어 그
    #: 기준(#222의 「마감 후 6시간」)이 성립하지 않으므로 실패 **횟수**만 본다
    #: (`classroom.scoring.SCORING_FAILURE_LIMIT`).
    model_version = models.CharField(max_length=200)
    #: LLM에 실제로 보낸 프롬프트 전문 — 체크리스트와 소스를 포함한다.
    prompt = models.TextField()
    #: 체크리스트 항목별 판정 근거.
    #: [{"checklist_item_id": int, "is_met": bool, "reasoning": str}, ...]
    reasoning = models.JSONField()
    #: 문법 검사 기본 항목의 판정 스냅샷(#408) — 강사 항목(`reasoning`)과
    #: 구별되는 별도 칸이다: 체크리스트 행이 아니고, 판정 주체(파서/AI)가
    #: 강사 항목에는 없는 개념이라 같은 리스트에 섞지 않는다. 채점 시점에
    #: `problem.syntax_check_enabled`가 꺼져 있었으면 `None`이다. 켜져
    #: 있었으면 `{"is_met": bool, "reasoning": str, "judged_by":
    #: "parser"|"ai", "findings": [{"path": str, "line": int|None,
    #: "message": str}, ...]}` 모양이다(`classroom.syntax_check.build_verdict`).
    #: append-only라 이 값도 한 번 저장되면 바뀌지 않는다(ADR-0006).
    syntax_check_result = models.JSONField(null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "ClassroomScore"
        verbose_name_plural = "ClassroomScore"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "ClassroomScore는 append-only다(ADR-0006과 같은 규율) — 이미 저장된 "
                "행은 다시 저장할 수 없다."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("ClassroomScore는 append-only다 — 삭제할 수 없다.")

    def __str__(self) -> str:  # pragma: no cover
        return f"ClassroomScore(submission={self.submission_id})"


class ProblemTemplate(models.Model):
    """문제 하나를 공개한 시점의 **사본**(#316, #312 Implementation Decisions
    「템플릿 공유」). 사본의 필드(title·description·...)는 `Problem`을 가리키지
    않는다 — 원본을 고치거나 지워도 그 값은 바뀌지 않는다는 약속이 FK 부재로
    구조에 박혀 있다(판·갱신 알림·원본 연결은 Out of Scope).

    **`source_problem`은 예외다**(#333) — 원본을 가리키되 **약한** 참조다:
    원본이 지워지면 `SET_NULL`로 이 칸만 비워지고 행 자체는 그대로다. 화면에
    노출되지 않고 오직 "같은 원본에 살아 있는(내리지 않은) 템플릿이 이미
    있는가"를 백엔드가 판단하는 데만 쓰인다(`Meta.constraints`). 이 필드가
    생기기 전에 만들어진 템플릿은 계속 null로 남는다 — 마이그레이션이
    백필하지 않는다.

    **`model`을 담지 않는다.** 필드 자체가 없다 — 가져간 사람이 남이 고른
    비싼 모델의 청구서를 자기 키로 받는 사고를 구조로 막는다(#316 AC).

    `publisher_display_name`은 계정 표시 이름이 아니라 공개할 때 직접 적는
    값이다 — 의도하지 않은 이름이 나가거나 탈퇴로 사라지는 것을 막는다.
    """

    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="problem_templates", on_delete=models.CASCADE
    )
    #: 공개 시점의 원본(#333). 화면 문 하나만이 아니라 이 칸의 unique 제약이
    #: 「같은 문제를 두 번 공개해도 새 템플릿이 안 생긴다」를 구조로 지킨다.
    source_problem = models.ForeignKey(
        Problem, related_name="templates", null=True, blank=True, on_delete=models.SET_NULL
    )
    publisher_display_name = models.CharField(max_length=100)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    #: `Problem.submission_formats`와 같은 이유·같은 모양(#373/#374) — 공개
    #: 시점에 원본이 허용하던 형식 목록을 그대로 사본에 담는다.
    submission_formats = models.JSONField(default=list)
    #: `Problem.grading_strictness`/`grading_guideline_text`와 같은 이유·같은
    #: 모양(#389) — 지침은 "무엇을 통과로 볼지"의 일부라 채점 모델과 달리
    #: 공개 시점에 원본이 가진 값을 그대로 사본에 담는다.
    grading_strictness = models.CharField(
        max_length=10,
        choices=Problem.GradingStrictness.choices,
        default=DEFAULT_GRADING_STRICTNESS,
    )
    grading_guideline_text = models.CharField(
        max_length=GRADING_GUIDELINE_TEXT_MAX_LENGTH, blank=True, default=""
    )
    #: `Problem.syntax_check_enabled`와 같은 이유·같은 모양(#410) — 문법 검사도
    #: 채점 지침처럼 "무엇을 통과로 볼지"의 일부라 공개 시점 값을 그대로 담는다.
    syntax_check_enabled = models.BooleanField(default=True)

    #: 추측 불가능한 공유 코드 — 가입 링크와 같은 모양, 같은 생성기다(#316
    #: Implementation Decisions "가입 링크와 같은 모양").
    share_code = models.CharField(max_length=32, unique=True, default=_generate_join_code)

    created_at = models.DateTimeField(auto_now_add=True)
    #: 올린 사람의 자진 내림 또는 운영자의 판단으로 내려간 시각(#316/#320).
    #: null이면 공개 중이다. 지우지 않고 이 값만 켜는 이유는 감사 기록(누가
    #: 신고했고 운영자가 무엇을 판단했는지)이 대상 행을 잃지 않아야 하기
    #: 때문이다 — `Class.archived_at`과 같은 관용구.
    taken_down_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            #: 원본 하나에 살아 있는(내리지 않은) 템플릿은 동시에 하나뿐이다
            #: (#333 AC). `source_problem`이 null인 행(원본을 모르는 옛
            #: 템플릿, 또는 원본이 지워져 비워진 행)은 이 제약 밖이다 — 여러
            #: 개가 null이어도 걸리지 않는다.
            models.UniqueConstraint(
                fields=["source_problem"],
                condition=models.Q(taken_down_at__isnull=True, source_problem__isnull=False),
                name="unique_live_problem_template_per_source",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ProblemTemplate(id={self.pk}, title={self.title!r})"


class ProblemTemplateChecklistItem(models.Model):
    """공개 시점 체크리스트 사본 한 줄 — `ChecklistItem`과 같은 모양이지만
    독립 테이블이다(`ProblemTemplate`이 `Problem`을 가리키지 않는 것과 같은
    이유)."""

    template = models.ForeignKey(
        ProblemTemplate, related_name="checklist_items", on_delete=models.CASCADE
    )
    label = models.CharField(max_length=200)
    required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ProblemTemplateChecklistItem(id={self.pk}, label={self.label!r})"


class ProblemTemplateReport(models.Model):
    """부적절한 템플릿 신고 하나(#320). 자기 템플릿은 신고 대상이 아니다 —
    그건 올린 사람이 직접 내리면 된다(API가 강제한다).

    **같은 사람이 같은 템플릿을 여러 번 신고해도 한 건으로 센다**(AC) — 그
    보장은 unique 제약이 진다, API는 두 번째 신고를 조용히 기존 행으로
    합친다(`get_or_create`).
    """

    template = models.ForeignKey(ProblemTemplate, related_name="reports", on_delete=models.CASCADE)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="problem_template_reports", on_delete=models.CASCADE
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "reporter"], name="unique_problem_template_report"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ProblemTemplateReport(template={self.template_id}, reporter={self.reporter_id})"


class ProblemTemplateModerationDecision(models.Model):
    """신고된 템플릿에 대한 운영자의 판단(#320) — `appeals.AppealRuling`과
    같은 이유로 신고와 분리된 감사 기록이다. 「내림」과 「기각」 둘 다 이
    테이블에 남는다 — 기각도 판단이고, 판단이면 누가·언제·왜가 남아야
    한다(AC).

    두 FK 모두 PROTECT다 — `AppealRuling`과 같은 이유로, 대상이나 판단자
    계정을 지우는 것만으로 「누가 왜 내렸는가」가 사라지면 안 된다.
    """

    class Decision(models.TextChoices):
        TAKEDOWN = "takedown", "내림"
        DISMISS = "dismiss", "기각"

    template = models.ForeignKey(
        ProblemTemplate, related_name="moderation_decisions", on_delete=models.PROTECT
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="problem_template_moderation_decisions",
        on_delete=models.PROTECT,
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    note = models.TextField()
    decided_at = models.DateTimeField()

    class Meta:
        ordering = ["-decided_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ProblemTemplateModerationDecision(template={self.template_id}, decision={self.decision})"


class ClassTemplate(models.Model):
    """클래스 하나를 공개한 시점의 **사본**(#319, #312 Implementation Decisions
    「템플릿 공유」) — `ProblemTemplate`과 같은 이유로 사본의 필드는 `Class`를
    가리키지 않는다. 문제 사이의 순서도 커리큘럼의 일부라
    `ClassTemplateProblem.order`로 함께 담는다.

    **`source_class`는 예외다**(#333) — `ProblemTemplate.source_problem`과
    같은 이유·같은 모양의 약한 참조다: 원본이 지워지면 `SET_NULL`로 비워지고
    행은 남는다. 「같은 클래스에 살아 있는 템플릿이 이미 있으면 두 번째 공개가
    새로 만들지 않는다」를 이 칸의 unique 제약이 구조로 지킨다.

    **채점 모델을 담지 않는다** — `ProblemTemplate`과 같은 이유로 필드 자체가
    없다(가져간 사람이 남이 고른 모델의 청구서를 자기 키로 받는 사고를 구조로
    막는다). 참여자·제출물·판정·가입 코드·OpenAI 키도 이 모델이 애초에 모르는
    것들이다.
    """

    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="class_templates", on_delete=models.CASCADE
    )
    source_class = models.ForeignKey(
        Class, related_name="templates", null=True, blank=True, on_delete=models.SET_NULL
    )
    publisher_display_name = models.CharField(max_length=100)
    #: 공개 시점 클래스 이름의 사본 — 가져가는 사람이 자기 클래스 이름을
    #: 새로 정하므로(AC), 이 값은 미리보기에만 쓰인다.
    name = models.CharField(max_length=200)

    #: 추측 불가능한 공유 코드 — `ProblemTemplate.share_code`와 같은 모양,
    #: 같은 생성기다.
    share_code = models.CharField(max_length=32, unique=True, default=_generate_join_code)

    created_at = models.DateTimeField(auto_now_add=True)
    #: `ProblemTemplate.taken_down_at`과 같은 관용구 — 올린 사람의 자진 내림
    #: 또는 운영자의 판단으로 내려간 시각. null이면 공개 중이다.
    taken_down_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            #: `ProblemTemplate.Meta.constraints`와 같은 이유·같은 모양.
            models.UniqueConstraint(
                fields=["source_class"],
                condition=models.Q(taken_down_at__isnull=True, source_class__isnull=False),
                name="unique_live_class_template_per_source",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ClassTemplate(id={self.pk}, name={self.name!r})"


class ClassTemplateProblem(models.Model):
    """공개 시점 클래스 안 문제 하나의 사본 — `Problem`을 가리키지 않는다
    (`ClassTemplate`이 `Class`를 가리키지 않는 것과 같은 이유). `order`가
    클래스 안에서의 순서를 그대로 지킨다."""

    template = models.ForeignKey(
        ClassTemplate, related_name="problems", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    #: `Problem.submission_formats`와 같은 이유·같은 모양(#373/#374).
    submission_formats = models.JSONField(default=list)
    #: `Problem.grading_strictness`/`grading_guideline_text`와 같은 이유·같은
    #: 모양(#389).
    grading_strictness = models.CharField(
        max_length=10,
        choices=Problem.GradingStrictness.choices,
        default=DEFAULT_GRADING_STRICTNESS,
    )
    grading_guideline_text = models.CharField(
        max_length=GRADING_GUIDELINE_TEXT_MAX_LENGTH, blank=True, default=""
    )
    #: `Problem.syntax_check_enabled`와 같은 이유·같은 모양(#410).
    syntax_check_enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ClassTemplateProblem(id={self.pk}, title={self.title!r})"


class ClassTemplateProblemChecklistItem(models.Model):
    """`ClassTemplateProblem` 하나의 체크리스트 사본 한 줄 —
    `ProblemTemplateChecklistItem`과 같은 모양이지만 독립 테이블이다."""

    problem = models.ForeignKey(
        ClassTemplateProblem, related_name="checklist_items", on_delete=models.CASCADE
    )
    label = models.CharField(max_length=200)
    required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ClassTemplateProblemChecklistItem(id={self.pk}, label={self.label!r})"


class ClassroomScoringAttempt(models.Model):
    """실패한 채점 시도의 이력(#287) — `scoring.ScoringAttempt`와 같은 역할,
    같은 이유로 다른 테이블이다. Score와 달리 append-only가 아니다 — 판정이
    아니라 "언제, 왜 실패했는지"에 대한 운영 로그다.
    """

    # related_name이 "scoring_attempts"가 아니라 "classroom_scoring_attempts"다 —
    # 위 `ClassroomScore.submission`과 같은 이유(공모전 자식의 `scoring.
    # ScoringAttempt`가 이미 그 이름을 쓰고, 둘 다 결국 `submissions.Submission`
    # 계층을 가리킨다).
    submission = models.ForeignKey(
        ClassroomSubmission, related_name="classroom_scoring_attempts", on_delete=models.CASCADE
    )
    attempted_at = models.DateTimeField(auto_now_add=True)
    error = models.TextField()
    #: 다시 시도해도 같은 결과가 나올 실패인가(`core.llm_scoring.
    #: LLMAdapterPermanentError`와 같은 뜻). True면 유예 없이 바로 실패 상한에
    #: 도달한 것으로 본다(ADR-0031과 같은 규율).
    permanent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = "강의실 채점 실패 이력"
        verbose_name_plural = "강의실 채점 실패 이력"

    def __str__(self) -> str:  # pragma: no cover
        return f"ClassroomScoringAttempt(submission={self.submission_id}, at={self.attempted_at})"
