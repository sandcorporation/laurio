"""두 제품이 공유하는 제출물 스키마 — 자료·근거·자가 응답 (#270, ADR-0039).

제품별로 갈리는 응답 모양(`SubmissionOut`·`MyParticipationOut`·비교·지표 등)은
`contests.submission_schemas`로 옮겨갔다 — 이 파일에는 부모(`Submission`)가
공유하는 자료(`SubmissionAsset`)·근거(`Evidence`)·자가 응답
(`RequirementResponse`)의 입출력 모양만 남는다.
"""

from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field


class EvidenceIn(Schema):
    kind: str
    value: str = Field(max_length=500)
    # 이 근거가 가리키는 자료의 id (#190). 같은 요청의 `assets`에 담겨 새로
    # 만들어지는 자료는 아직 id가 없으므로 가리킬 수 없다 — 자료를 먼저 저장한
    # 다음 요청에서 연결한다. 없으면 지금까지와 같은 "대상을 특정하지 않은 근거"다.
    asset_id: int | None = None


class EvidenceOut(Schema):
    kind: str
    value: str
    asset_id: int | None = None


class RequirementResponseIn(Schema):
    requirement_id: int
    is_met: bool = False
    # RequirementResponse.note와 같은 길이(#10 리뷰 지적) — 스키마가 막지 않으면
    # DB CHECK(varchar(1000))이 대신 걸려 422 대신 500(DataError)이 난다.
    note: str = Field(default="", max_length=1000)
    evidence: list[EvidenceIn] = []


class RequirementResponseOut(Schema):
    requirement_id: int
    is_met: bool
    note: str
    evidence: list[EvidenceOut]
    # Evidence가 하나도 연결되지 않은 자가 응답인지 (ADR-0014 — 미연결은 거부가
    # 아니라 표시만 한다. 점수화는 #12 소관).
    is_linked: bool


class SubmissionAssetIn(Schema):
    """제출 페이로드가 담는 자료 하나 (#190).

    `id`가 있으면 **기존 자료를 유지**하고(그 자리에 새 행을 만들지 않는다),
    없으면 새로 만든다. 페이로드에 없는 기존 자료는 지워진다. 이 API에서
    부분 갱신 의미론을 갖는 것은 자료뿐이다 — `requirement_responses`는
    지금까지처럼 통째로 재생성된다(편집 UI가 매번 체크리스트 전체를 보낸다).

    id를 실어 보내지 않으면 저장할 때마다 같은 파일이 새 행이 되어 "언제
    올렸는가"가 전부 마지막 수정 시각으로 뭉갠다.
    """

    id: int | None = None
    kind: str
    # 아래 max_length는 submissions.models.SubmissionAsset의 같은 필드와 길이를
    # 맞춘다(#10 리뷰 지적) — 스키마가 막지 않으면 DB CHECK가 대신 걸려 422 대신
    # 500(DataError)이 난다.
    value: str = Field(max_length=2000)
    label: str = Field(default="", max_length=200)
    test_account: str = Field(default="", max_length=500)
    order: int = Field(default=0, ge=0)
    # 업로드 발급(`POST /storage/uploads`)에 실었던 content-type을 그대로
    # 되돌려 보낸다(#241) — storage 앱은 그 값을 버리므로(target_ref가 불투명한
    # 문자열이라 자산 모델을 모른다), 다시 저장할 자리가 여기뿐이다. SOURCE·
    # DEMO_VIDEO가 아닌 종류(URL)에는 의미가 없어 저장 시 무시된다
    # (`contests.submission_api._clean_assets_in`). 응답 헤더에 그대로 실리지
    # 않는다 — 확장자를 고르는 조회 키일 뿐이다
    # (`storage.filenames.build_download_filename`).
    content_type: str = Field(default="", max_length=255)


class AssetSummaryOut(Schema):
    """`test_account`가 **없는** 자료 (#190).

    공개 프로필과 심사 비교 화면이 쓴다. 두 스키마 모두 다중화 이전에도
    `test_account` 필드가 없었다 — 마감 후 공개되는 것은 데모·영상·스크린샷이지
    그것을 들여다볼 로그인 정보까지가 아니고(ADR-0014의 "데모·영상" 칸, #10 리뷰
    지적), 비교 화면은 애초에 그 필드를 내지 않았다. `SubmissionAssetOut`을 그대로
    쓰면 다중화가 그 두 자리에 로그인 정보를 조용히 새로 흘려보내게 된다.
    """

    id: int
    kind: str
    value: str
    label: str
    order: int
    # 화면 안에서 바로 열 수 있는 presigned URL (#265). `DEMO_VIDEO`·`SCREENSHOT`
    # (object_key를 갖는 종류)에만 값이 있다 — `DEMO_URL`은 `value` 자체가 이미
    # 외부 URL이라 서명이 필요 없어 항상 null이다. 이 필드가 나가는 두 응답
    # (공개 프로필·심사 비교) 모두 이미 마감 후로 확정된 자리라(`contests.
    # submission_api._public_asset_summaries`), 여기서 URL을 내려도 마감 전
    # 비공개 원칙을 어기지 않는다.
    download_url: str | None = None
    # 보존 기간이 지나 **파일만** 파기된 자료인가 (#262, ADR-0035). 자료 행·라벨·
    # 근거는 그대로 남으므로 이 요약도 그대로 나가지만, 서명할 오브젝트가 없어
    # `download_url`이 null이다. 화면은 이 값을 보고 「보존 기간이 지났다」를
    # 말한다 — 없는 파일을 가리키는 `<video>`를 그리면 사용자에게는 플랫폼이
    # 깨진 것으로 보인다. 다운로드 엔드포인트의 `expired`와 같은 사실이다
    # (`storage.api.DownloadResponse`).
    expired: bool = False


class SubmissionAssetOut(Schema):
    id: int
    kind: str
    #: `repository` 는 **낸 URL 그대로**(저장소·`/tree/<브랜치>`·`/commit/<sha>`, #777) — 다시
    #: 보내면 서버가 같은 규칙으로 나눈다.
    value: str
    label: str
    test_account: str
    order: int
    # `repository`가 공개인가 — null은 "비공개"가 아니라 "아직 확인하지 않음"이다
    # (#190/#193). 다른 종류에서는 항상 null이다.
    is_public: bool | None = None
    # `repository` 의 고정 커밋(#777) — 커밋 URL 이면 낸 SHA(첫 스캔이 40자로 확정), 브랜치
    # URL 이면 첫 스캔이 박은 SHA. 저장소 URL 제출·다른 종류는 null.
    commit_sha: str | None = None
    # 낸 브랜치·커밋을 GitHub 에서 찾았는가(#777) — `is_public` 과 같은 세 값. False 는
    # 비공개와 같은 줄의 배지(「브랜치를 찾을 수 없음 — 채점에 반영되지 않습니다」)다.
    # 저장소 URL 제출·다른 종류는 항상 null.
    repository_ref_found: bool | None = None
    # 이 자료를 참가자가 아니라 플랫폼이 만들었는가 (#220, ADR-0030) — 저장소만
    # 낸 제출의 채점 박제가 남긴 소스 자료만 True다. 화면이 "이 자료는 지우거나
    # 고칠 수 없다"를 보일 근거가 된다.
    created_by_platform: bool = False
    # 시연 영상 파일의 보관 시점 (#262, ADR-0035) — 그 시각이 지나면 스토리지
    # 오브젝트가 지워진다. `kind`가 `demo_video`가 아니거나, 아직 그 시각이
    # 정해지지 않았으면(심사기간이 아직 시작되지 않은 진행 중 공모전) null이다.
    demo_video_retention_deadline: datetime | None = None
    # 그 파일이 이미 파기됐는가 — True면 위 시점은 지나간 과거를 말한다.
    demo_video_destroyed: bool = False


class CompletionOut(Schema):
    """시연 영상·데모 URL·테스트 계정·Evidence 연결 상태를 요약한 채움률 지표.

    강제 항목은 아무 것도 없다 — 소스만 필수다. 이 지표는 신호일 뿐이다.

    **`has_*` 세 boolean은 "하나라도 있는가"로 그대로 남는다**(#190). 자료가
    여럿이 될 수 있게 된 뒤에도 이 셋을 개수로 갈아치우지 않은 이유는, 배지를
    그리는 자리에서 필요한 것이 여전히 있다/없다이고 그 자리마다 `count > 0`을
    다시 쓰게 만들 이유가 없기 때문이다. 개수는 옆에 따로 낸다 — 영상 다섯 편을
    낸 제출과 한 편을 낸 제출이 Sponsor에게 같은 배지로 보이면 다중화를 해 놓고
    그 신호를 버리는 셈이다.
    """

    has_demo_video: bool
    has_demo_url: bool
    has_test_account: bool
    # #190 — 종류별 자료 수.
    source_count: int = 0
    demo_video_count: int = 0
    demo_url_count: int = 0
    repository_count: int = 0
    total_requirement_count: int
    linked_requirement_count: int
    unlinked_requirement_count: int
