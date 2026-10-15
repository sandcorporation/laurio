"""Submission 도메인 모델 (CONTEXT.md, ADR-0014, ADR-0027, ADR-0039, #270).

`Submission`은 두 제품(공모전·강의실)이 공유하는 **부모**다 — 누가 냈는가(`user`),
언제 냈는가, 그리고 **자료·근거·자가 응답이 매달리는 자리**만 든다. 제품별 계약은
자식이 든다: 공모전은 `contests.ContestSubmission`(`contest`·`developer` FK와
`(contest, developer)` 유니크 제약), 강의실은 아직 없다(이 티켓은 두 번째 자식을
만들지 않는다 — ADR-0039).

**Django 다중 테이블 상속이다.** 이 테이블과 pk가 그대로 부모로 남는다 — 자료
(`SubmissionAsset`)·근거·자가 응답과, 이 테이블을 가리키는 다른 앱의 FK(Score·
Award·DistributionShare·Handover·Appeal)가 전부 이 테이블을 그대로 가리킨다.
**그 FK들은 손대지 않는다** — 자식(`ContestSubmission`)의 `contest`·`developer`가
필요한 곳은 `submission.contestsubmission`(Django가 자동으로 여는 역방향
접근자)을 거쳐야 한다.

`product`는 이 행이 어느 제품의 것인지 **조인 없이** 말한다 — `Contest.kind`
(공모전/과제)와는 다른 축이라 이름을 겹치지 않게 골랐다. 자식 없는 부모 행은
생성 경로를 자식에서만 열어 막는다(`ContestSubmission.objects.create(...)`가
유일한 생성 경로다) — 여기 모델 자체는 그 규율을 강제하지 않는다.

그 결과물은 자료 하나가 아니라 **`SubmissionAsset` 목록**이다(#190, ADR-0027) —
소스·시연 영상·데모 URL·GitHub 저장소를 각각 여러 개 담을 수 있다.
`Contest.deliverable_types`가 M2M이라 한 Contest가 "웹 서비스 + 모바일 앱 +
관리자 페이지"를 함께 요구할 수 있는데, 자료가 종류당 하나면 그런 Contest의
참가자는 자기가 만든 것의 일부만 낼 수 있었다.

전체 소스코드는 필수다 — 플랫폼의 "강제하지 않고 배지로 신호한다" 원칙에서
유일한 예외다(ADR-0014). 다중화 이후 그 뜻은 **`kind=source`인 자산이 최소
하나**다. 그 강제는 API 레이어(`contests.submission_api`, 공모전 전용)에서 하고,
여기 모델은 그 결과를 담는 그릇이다.

시연 영상·데모 URL·테스트 계정은 선택이며 완성도 지표로만 쓰인다. 각 `Requirement`
자가 응답(`RequirementResponse`)에는 `Evidence`를 연결할 수 있다 — 연결되지 않아도
제출 자체는 거부되지 않고, "미연결"로 표시될 뿐이다(#12가 채점에서 미달로 본다).
"""

from __future__ import annotations

import re

from django.conf import settings
from django.db import models


class Submission(models.Model):
    class Product(models.TextChoices):
        CONTEST = "contest", "공모전"
        CLASSROOM = "classroom", "강의실"

    #: 제출자. 공모전 참가자든 강의실 참여자든 계정은 언제나 `User`다 — 강의실
    #: 참여자에게는 `DeveloperProfile`이 없다(ADR-0037). 공모전 쪽의 `developer_id`
    #: (`accounts.DeveloperProfile`)가 필요한 코드는 자식(`ContestSubmission`)을
    #: 거친다.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="submissions", on_delete=models.CASCADE
    )
    #: 이 행이 어느 제품의 것인가(#270, ADR-0039) — `Contest.kind`(공모전/과제)와는
    #: 다른 축이다. 부모를 잡은 공유 코드(가시성 리졸버·다운로드 파일명·파기 스캔)가
    #: 조인이나 `RelatedObjectDoesNotExist` 예외 없이 갈래를 타는 자리다.
    product = models.CharField(max_length=20, choices=Product.choices)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Submission(id={self.pk}, product={self.product})"


# `kind=repository`의 `value`가 받는 유일한 모양. 임의의 git URL을 받으면 플랫폼
# 서버가 참가자가 지정한 주소로 나가게 되어(SSRF) 내부 네트워크 탐색 경로가 생긴다
# — 저장소를 실제로 clone하는 것은 #193이지만, 그때 받아들일 수 있는 값만 지금부터
# 저장한다. GitLab·Bitbucket은 어댑터 구현을 하나 더하는 일이라 나중에 열어도 늦지
# 않다(ADR-0027).
GITHUB_REPO_URL_PATTERN = re.compile(
    r"^https://github\.com/[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}/?$"
)


def normalize_github_repo_url(url: str) -> str:
    """끝의 `/`·`.git` 을 뗀다 — 같은 저장소를 가리키는 모양을 한 가지로 저장한다. 제출 화면이
    보내기 전에 같은 정리를 하지만(`@codemit/bff-client/repository-url`), 화면을 거치지 않은
    요청도 같은 값으로 남게 서버도 한다. GitHub 은 `.git` 으로 끝나는 저장소 이름을 허용하지
    않아 떼어도 다른 저장소가 되지 않는다(#537). 형식 검사는 `GITHUB_REPO_URL_PATTERN` 이 한다."""

    value = url.strip().rstrip("/")
    if value.lower().endswith(".git") and not value.endswith("/.git"):
        value = value[: -len(".git")]
    return value.rstrip("/")


#: `test_account`를 붙일 수 있는 종류. `SubmissionAsset.Meta.constraints`가 읽어야
#: 하는데 `Meta`는 클래스 본문 안에서 평가되어 `SubmissionAsset` 이름이 아직 없으므로
#: 모듈 수준에 둔다 — 같은 사실을 제약과 클래스 속성이 따로 적는 것을 막는다.
TEST_ACCOUNT_ASSET_KINDS = ("demo_url",)


class SubmissionAsset(models.Model):
    """제출작에 딸린 자료 하나 — 소스·시연 영상·스크린샷·데모 URL·GitHub 저장소 (#190, #264).

    **`value` 컬럼 하나로 담는다.** 그 값이 storage object_key인지 URL인지는
    `kind`가 말한다 — 같은 모양을 `Evidence`(kind + value)가 이미 쓰고 있어
    저장소에 선례가 있다. 종류마다 컬럼을 따로 두면 어느 행에든 빈 컬럼이 하나씩
    남고, "kind에 따라 정확히 하나만 채워진다"를 CHECK 제약으로 직접 써야 한다.

    가시성은 종류가 가른다(ADR-0014, ADR-0027, ADR-0036):

    - `SOURCE`·`REPOSITORY` — 본인 + Award 후 Sponsor
    - `DEMO_VIDEO`·`SCREENSHOT`·`DEMO_URL` — 진행 중엔 본인·Sponsor, 마감 후 전면 공개

    `SOURCE`·`DEMO_VIDEO`·`SCREENSHOT`는 `SubmissionTargetStateResolver`가 슬롯 단위로
    이미 판정하므로 리졸버를 손댈 것이 없다 — object_key가 `<target_ref>/<32자리 hex>`라
    한 슬롯에 여러 파일이 쌓여도 서로를 덮지 않는다(`handovers.BuildAsset`이 이미
    그렇게 쓴다). **`REPOSITORY`만 다르다** — storage를 거치지 않는 URL이라 API
    스키마가 직접 가시성을 판정해야 한다. 이 저장소에서 "본인만 보이는 URL"은
    처음이고 선례는 `test_account` 하나뿐이다.

    **`SCREENSHOT`은 버킷도 마감도 `DEMO_VIDEO`와 같지만 채점 입력은 아니다**
    (ADR-0036) — `SCORING_INPUT_KINDS`에 없다. AI 채점은 텍스트 프롬프트만 읽고
    이미지를 보지 않으므로(`scoring.services._build_prompt`), 스크린샷 파일 자체를
    프롬프트에 실어 봐야 채점기가 그것을 해석하지 못한다. 다만 이 자료를 가리키는
    `Evidence`의 라벨은 다른 자료와 똑같이 프롬프트에 실린다(#191) — "이 요구사항의
    근거가 스크린샷이다"라는 사실 자체는 여전히 AI에게 전달된다.
    """

    class Kind(models.TextChoices):
        SOURCE = "source", "소스코드"
        DEMO_VIDEO = "demo_video", "시연 영상"
        SCREENSHOT = "screenshot", "스크린샷"
        DEMO_URL = "demo_url", "데모 URL"
        REPOSITORY = "repository", "GitHub 저장소"

    #: 채점 입력이 되는 종류 — 같은 LLM 컨텍스트 예산을 나눠 쓴다(#191). `SCREENSHOT`은
    #: 위 클래스 docstring이 적은 이유로 여기 없다.
    SCORING_INPUT_KINDS = (Kind.SOURCE, Kind.REPOSITORY)
    #: 값이 storage object_key인 종류(나머지는 URL이다).
    OBJECT_KEY_KINDS = (Kind.SOURCE, Kind.DEMO_VIDEO, Kind.SCREENSHOT)
    #: 로그인 정보를 붙일 수 있는 종류 — 소스와 저장소에는 테스트 계정이 없다.
    TEST_ACCOUNT_KINDS = TEST_ACCOUNT_ASSET_KINDS

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

    # 업로드 발급 시(`storage.api.request_upload`) 클라이언트가 넘긴 content-type
    # (#241). `OBJECT_KEY_KINDS`(SOURCE·DEMO_VIDEO)에만 의미가 있다 — URL 종류는
    # storage를 거치지 않아 이 값이 필요 없다. 다운로드 파일명의 확장자를 이
    # 값으로 유도한다(`storage.filenames.build_download_filename`) — 그러지 않으면
    # 브라우저가 URL의 마지막 조각(object_key, 확장자 없는 32자리 hex)을 파일명으로
    # 대신 쓴다. 빈 문자열은 "모른다"이고(이 필드가 생기기 전 기존 행이 전부 이렇다),
    # 다운로드를 막지 않는다 — 확장자만 없는 이름이 붙는다.
    content_type = models.CharField(max_length=255, blank=True, default="")

    # `REPOSITORY`가 공개인가 — #193의 스캔이 채운다. **null은 "비공개"가 아니라
    # "아직 확인하지 않음"이다**: 제출·수정 API는 GitHub을 치지 않으므로(마감 직전에
    # 몰리는 제출이 남의 서비스 상태에 인질로 잡히면 안 된다) 제출 직후에는 항상
    # null이고, 마감 전에 스캔이 값을 채운다.
    is_public = models.BooleanField(null=True, blank=True)
    # `is_public`을 마지막으로 확인한 시각(#193) — 스캔이 "null이거나 오래된
    # 항목"을 다시 본다(ADR-0027). null이거나 오래됐다는 것만으로는 "한 번도
    # 안 봤다"와 "봤는데 오래됐다"를 `is_public`(null 하나)만으로 구별할 수
    # 없어서 따로 둔다.
    is_public_checked_at = models.DateTimeField(null=True, blank=True)
    # 마지막 저장소 조회 응답의 ETag(#490) — 다음 확인이 `If-None-Match` 로 보내고,
    # 304 를 받으면 GitHub 이 그 호출을 시간당 한도에 세지 않는다. 자산에 두는 이유는
    # 이 값이 `is_public`·`is_public_checked_at` 과 한 묶음의 「마지막 확인」이기
    # 때문이다 — 캐시에 두면 비워질 때마다 전부 다시 세고, 어댑터가 지난 답을 기억하는
    # 상태를 갖게 된다. 비공개(404)·확인 전에는 null이다.
    is_public_etag = models.CharField(max_length=255, null=True, blank=True)

    # 이 자료를 누가 넣었는가 (#220, ADR-0030). 거의 모두 Developer가 넣지만
    # 전부는 아니다 — 소스 없이 저장소만 낸 제출이 채점 시점에 그 저장소를
    # clone한 zip을 그대로 kind=SOURCE 자료로 남긴다("박제"). Award 후 그
    # 저장소가 닫혀도 Sponsor에게 넘길 것이 있게 하기 위해서다(ADR-0014의
    # Handover가 열어줄 것이 없어지는 사고를 막는다). **참가자는 이 자료를
    # 지우거나 고칠 수 없다** — 실제로는 제출 수정 자체가 마감 전에만 가능하고
    # (`submissions.api`) 이 자료는 마감 후 채점 시점에만 생기므로, API 경로가
    # 그 시점에 이미 모든 수정을 거부해 구조적으로 도달하지 못한다. 그래도
    # `_merge_assets`가 한 번 더 방어한다 — 이 불변식이 나중에(예: 마감 후
    # 수정을 여는 기능이 생기면) 느슨해져도 조용히 깨지지 않게 한다.
    created_by_platform = models.BooleanField(default=False)

    # 이 자료의 **파일**이 보존 기간을 넘겨 파기된 시각(ADR-0035) — 행 자체는
    # 지우지 않는다. null이면 아직 파일이 있다. `DEMO_VIDEO`에만 채워진다 —
    # 소스는 파기 대상이 아니고(인수·이의 심판이 여는 대상이라 문제가 없는
    # 곳을 건드리지 않는다), URL 종류(`DEMO_URL`·`REPOSITORY`)는 storage를
    # 거치지 않아 지울 파일 자체가 없다. `submissions.retention` 의 스캔만
    # 이 컬럼을 채운다. 값이 차도 `Evidence.asset` 은 그대로 살아, 그 영상을
    # 가리키던 근거가 함께 사라지지 않는다 — `Evidence.asset` 이 가리키는 것은
    # 이 행이고, 이 행은 파일이 사라져도 존재한다.
    destroyed_at = models.DateTimeField(null=True, blank=True)

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
                    models.Q(kind__in=list(TEST_ACCOUNT_ASSET_KINDS))
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

    class Meta:
        # **순서를 명시한다** (#195 리뷰). 이 모델에는 `Meta` 자체가 없었고, 그래서
        # `response.evidence_items.all()` 이 정렬 없는 SELECT 였다 — 순서가 우연히
        # 삽입 순이었을 뿐이다. `_replace_requirement_responses` 가 저장할 때마다
        # 이전 행을 전부 지우고 다시 만들므로 힙 재사용으로 순서가 뒤집힐 수 있고,
        # 그러면 참가자가 적어 둔 근거가 화면에서 자리를 바꾼다. 형제인
        # `RequirementResponse`·`SubmissionAsset` 은 둘 다 `ordering` 을 갖는다.
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Evidence({self.kind}={self.value!r})"
