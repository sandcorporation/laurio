"""Submission 도메인 모델 (CONTEXT.md, ADR-0014, ADR-0027).

`Submission`은 한 Developer가 한 Contest에 낸 결과물 일체다. 그 결과물은 자료
하나가 아니라 **`SubmissionAsset` 목록**이다(#190, ADR-0027) — 소스·시연 영상·
데모 URL·GitHub 저장소를 각각 여러 개 담을 수 있다. `Contest.deliverable_types`가
M2M이라 한 Contest가 "웹 서비스 + 모바일 앱 + 관리자 페이지"를 함께 요구할 수
있는데, 자료가 종류당 하나면 그런 Contest의 참가자는 자기가 만든 것의 일부만
낼 수 있었다.

전체 소스코드는 필수다 — 플랫폼의 "강제하지 않고 배지로 신호한다" 원칙에서
유일한 예외다(ADR-0014). 다중화 이후 그 뜻은 **`kind=source`인 자산이 최소
하나**다. 그 강제는 API 레이어(submissions.api)에서 하고, 여기 모델은 그 결과를
담는 그릇이다.

시연 영상·데모 URL·테스트 계정은 선택이며 완성도 지표로만 쓰인다. 각 `Requirement`
자가 응답(`RequirementResponse`)에는 `Evidence`를 연결할 수 있다 — 연결되지 않아도
제출 자체는 거부되지 않고, "미연결"로 표시될 뿐이다(#12가 채점에서 미달로 본다).
"""

from __future__ import annotations

import re

from django.db import models


class Submission(models.Model):
    contest = models.ForeignKey(
        "contests.Contest", related_name="submissions", on_delete=models.CASCADE
    )
    developer = models.ForeignKey(
        "accounts.DeveloperProfile", related_name="submissions", on_delete=models.CASCADE
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # 한 Developer가 한 Contest에 낼 수 있는 Submission은 하나뿐이다. 두 번째
            # 제출은 새 행이 아니라 기존 행의 수정(PUT)이어야 한다.
            models.UniqueConstraint(
                fields=["contest", "developer"], name="unique_submission_per_contest_developer"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Submission(contest={self.contest_id}, developer={self.developer_id})"


# `kind=repository`의 `value`가 받는 유일한 모양. 임의의 git URL을 받으면 플랫폼
# 서버가 참가자가 지정한 주소로 나가게 되어(SSRF) 내부 네트워크 탐색 경로가 생긴다
# — 저장소를 실제로 clone하는 것은 #193이지만, 그때 받아들일 수 있는 값만 지금부터
# 저장한다. GitLab·Bitbucket은 어댑터 구현을 하나 더하는 일이라 나중에 열어도 늦지
# 않다(ADR-0027).
GITHUB_REPO_URL_PATTERN = re.compile(
    r"^https://github\.com/[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}/?$"
)


class SubmissionAsset(models.Model):
    """제출작에 딸린 자료 하나 — 소스·시연 영상·데모 URL·GitHub 저장소 (#190).

    **`value` 컬럼 하나로 담는다.** 그 값이 storage object_key인지 URL인지는
    `kind`가 말한다 — 같은 모양을 `Evidence`(kind + value)가 이미 쓰고 있어
    저장소에 선례가 있다. 종류마다 컬럼을 따로 두면 어느 행에든 빈 컬럼이 하나씩
    남고, "kind에 따라 정확히 하나만 채워진다"를 CHECK 제약으로 직접 써야 한다.

    가시성은 종류가 가른다(ADR-0014, ADR-0027):

    - `SOURCE`·`REPOSITORY` — 본인 + Award 후 Sponsor
    - `DEMO_VIDEO`·`DEMO_URL` — 진행 중엔 본인·Sponsor, 마감 후 전면 공개

    `SOURCE`·`DEMO_VIDEO`는 `SubmissionTargetStateResolver`가 슬롯 단위로 이미
    판정하므로 리졸버를 손댈 것이 없다 — object_key가 `<target_ref>/<32자리 hex>`라
    한 슬롯에 여러 파일이 쌓여도 서로를 덮지 않는다(`handovers.BuildAsset`이 이미
    그렇게 쓴다). **`REPOSITORY`만 다르다** — storage를 거치지 않는 URL이라 API
    스키마가 직접 가시성을 판정해야 한다. 이 저장소에서 "본인만 보이는 URL"은
    처음이고 선례는 `test_account` 하나뿐이다.
    """

    class Kind(models.TextChoices):
        SOURCE = "source", "소스코드"
        DEMO_VIDEO = "demo_video", "시연 영상"
        DEMO_URL = "demo_url", "데모 URL"
        REPOSITORY = "repository", "GitHub 저장소"

    #: 채점 입력이 되는 종류 — 같은 LLM 컨텍스트 예산을 나눠 쓴다(#191).
    SCORING_INPUT_KINDS = (Kind.SOURCE, Kind.REPOSITORY)
    #: 값이 storage object_key인 종류(나머지는 URL이다).
    OBJECT_KEY_KINDS = (Kind.SOURCE, Kind.DEMO_VIDEO)
    #: 로그인 정보를 붙일 수 있는 종류 — 소스와 저장소에는 테스트 계정이 없다.
    TEST_ACCOUNT_KINDS = (Kind.DEMO_URL,)

    submission = models.ForeignKey(Submission, related_name="assets", on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Kind.choices)

    # SOURCE·DEMO_VIDEO면 storage.api가 발급한 object_key, DEMO_URL·REPOSITORY면 URL.
    # 길이는 둘 중 긴 쪽(URL)에 맞춘다 — object_key는 600자를 넘지 않지만, 두 세계를
    # 한 컬럼에 담기로 한 이상 상한도 하나다.
    value = models.CharField(max_length=2000)

    # 무엇을 보여주는 자료인지("모바일 앱 데모"). 데모·영상이 여럿이 되는 순간
    # Sponsor도 AI도 어느 것이 무엇인지 알 방법이 없어진다.
    label = models.CharField(max_length=200, blank=True)
    # 이 데모를 열어보는 데 필요한 로그인 정보. 데모마다 다를 수 있어 제출작이
    # 아니라 자산에 붙는다.
    test_account = models.CharField(max_length=500, blank=True)
    order = models.PositiveIntegerField(default=0)

    # `REPOSITORY`가 공개인가 — #193의 스캔이 채운다. **null은 "비공개"가 아니라
    # "아직 확인하지 않음"이다**: 제출·수정 API는 GitHub을 치지 않으므로(마감 직전에
    # 몰리는 제출이 남의 서비스 상태에 인질로 잡히면 안 된다) 제출 직후에는 항상
    # null이고, 마감 전에 스캔이 값을 채운다. 이 티켓은 컬럼만 만들고 채우지 않는다.
    is_public = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "order", "id"]
        constraints = [
            # 같은 파일·URL을 한 제출작에 두 번 담을 이유가 없다. 채점 예산을
            # 같은 소스로 두 번 먹는 것도 막는다.
            models.UniqueConstraint(
                fields=["submission", "kind", "value"], name="unique_asset_per_submission_kind"
            ),
            # 소스와 저장소에는 테스트 계정이 없다 — "이 소스를 열어보는 로그인
            # 정보"라는 것이 존재하지 않는다. 빈 값만 허용해 의미 없는 데이터가
            # 쌓이지 않게 한다.
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=["demo_url"])
                    | models.Q(test_account="")
                ),
                name="test_account_only_on_demo_url_asset",
            ),
        ]

    @property
    def is_object_key(self) -> bool:
        return self.kind in self.OBJECT_KEY_KINDS

    def __str__(self) -> str:  # pragma: no cover
        return f"SubmissionAsset(submission={self.submission_id}, kind={self.kind})"


class RequirementResponse(models.Model):
    """한 Requirement에 대한 Developer의 자가 응답."""

    submission = models.ForeignKey(
        Submission, related_name="requirement_responses", on_delete=models.CASCADE
    )
    requirement = models.ForeignKey(
        "contests.Requirement", related_name="responses", on_delete=models.CASCADE
    )
    is_met = models.BooleanField(default=False)
    note = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["requirement__order", "requirement_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "requirement"], name="unique_response_per_requirement"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"RequirementResponse(submission={self.submission_id}, requirement={self.requirement_id})"


class Evidence(models.Model):
    """자가 응답 하나를 뒷받침하는 근거 (CONTEXT.md의 Evidence)."""

    class Kind(models.TextChoices):
        VIDEO_TIMESTAMP = "video_timestamp", "영상 타임스탬프"
        SCREENSHOT = "screenshot", "스크린샷"
        DEMO_PATH = "demo_path", "데모 내 경로"
        SOURCE_LOCATION = "source_location", "소스 위치"

    response = models.ForeignKey(
        RequirementResponse, related_name="evidence_items", on_delete=models.CASCADE
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    value = models.CharField(max_length=500)

    # 이 근거가 가리키는 자료 (#190). 데모·영상이 여럿이 되는 순간 "데모 내 경로"나
    # "영상 타임스탬프"가 어느 대상의 것인지 알 수 없어지고, 채점 프롬프트는 그
    # 값을 그대로 LLM에 넘기므로 AI가 근거를 못 찾아 미달 판정이 는다. 자료를
    # 지우면 그것을 가리키던 근거도 함께 사라진다 — 가리킬 곳이 없는 근거는
    # 근거가 아니다. null은 "자료를 특정하지 않은 근거"이고 그대로 허용된다
    # (기존 행 전부가 그렇다).
    asset = models.ForeignKey(
        "submissions.SubmissionAsset",
        related_name="evidence_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Evidence({self.kind}={self.value!r})"
