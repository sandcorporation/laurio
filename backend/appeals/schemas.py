from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field

from submissions.schemas import ScoredAssetOut


class ErrorOut(Schema):
    detail: str


class AppealCreateIn(Schema):
    reason: str = Field(min_length=1, max_length=4000)


class AppealOut(Schema):
    """Developer 가 보는 자기 이의의 상태.

    심판 결과는 이제 별도 테이블에 살지만(AppealRuling, #44) 여기 필드 구성은
    그대로 둔다 — Developer 쪽 계약을 바꿀 이유가 없다. 심판 전에는 전부 비어 있고,
    `ruled_by` 는 여기에 넣지 않는다: 이의를 제기한 사람에게 심판한 개인의 이름을
    노출할 이유가 없고, 감사에 필요한 것은 운영자 표면에서 조회된다.
    """

    id: int
    submission_id: int
    reason: str
    status: str
    ruling_note: str
    correction_amount: int | None = None
    ruled_at: datetime | None = None
    created_at: datetime
    # 이 이의가 지금 어떤 Contest 의 배분을 막고 있는가 (#74 스토리 24·37·38).
    #
    # 같은 값이 **운영자 큐와 제출자 화면 양쪽**에 쓰인다 — 이 스키마가 두 곳에서
    # 쓰이기 때문이다. 운영자에게는 "이 심판이 돈을 막고 있다"는 우선순위 신호,
    # 제출자에게는 "내 이의 때문에 아직 안 움직인다 — 사라진 게 아니다"라는
    # 설명이다. 두 문장은 같은 사실의 두 얼굴이라 값도 하나여야 한다.
    is_holding_distribution: bool = False


class ScoreSnapshotOut(Schema):
    """운영자가 심판 근거로 보는 Score 스냅샷 — 점수·근거·모델버전(#21 AC, ADR-0006).

    **`prompt` 는 여기 없다 (#59, ADR-0022).** 프롬프트에는 채점에 쓰인 제출 소스가
    통째로 임베드되어 있어(`scoring._build_prompt`), 이의 상세를 조회하는 것만으로
    소스 전문이 흘러서는 안 된다. 소스를 보려면 별도의 명시적 펼침 요청이 필요하고
    그 요청은 `SourceReading` 을 남긴다(#60) — `Score` 자체는 프롬프트를 여전히
    그대로 보관한다(재현성을 위한 불변 스냅샷, ADR-0006). 이 스키마가 바뀐 것은
    **누가 볼 수 있는지** 뿐이다.
    """

    percentage: str
    model_version: str
    reasoning: list[dict]
    created_at: datetime
    # 채점에 실제로 쓰인 자산 목록 (#191) — Developer가 보는 `OwnScoreOut`과
    # 같은 사실을 운영자도 봐야 이의 심판이 같은 근거 위에서 이루어진다.
    scored_assets: list[ScoredAssetOut] = []
    # 채점 직전 저장소 도달 가능성 재확인 기록 (#219, ADR-0030) — Developer가
    # 보는 `OwnScoreOut`과 같은 사실이다. "내 저장소는 공개였는데 0%를 받았다"는
    # 이의를 운영자가 추측으로 심판하지 않게 한다.
    repository_reachability_check: list[dict] = []


class RulingOut(Schema):
    """심판 기록 — 운영자 표면에서만 보인다.

    `ruled_by_*` 가 이 스펙의 목적 그 자체다. 이 행이 존재하는데 이 필드가 비어
    있는 상태는 스키마상 만들 수 없다(AppealRuling 참고).
    """

    decision: str
    ruled_by_id: int
    ruled_by_username: str
    note: str
    ruled_at: datetime
    correction_amount: int | None = None
    correction_journal_entry_id: int | None = None


class AppealDetailOut(AppealOut):
    """운영자 전용 상세 — 이의제기 자체에 Score 스냅샷과 심판 기록을 얹는다."""

    score: ScoreSnapshotOut
    ruling: RulingOut | None = None


class AppealRulingIn(Schema):
    decision: str  # "uphold" | "reject"
    ruling_note: str = Field(default="", max_length=4000)
    # decision == "uphold"일 때만 필수다. 운영자가 근거를 검토해 직접 정하는
    # 정정 금액 — 자동으로 계산되지 않는다(재채점 경로가 없는 것과 같은 이유).
    correction_amount: int | None = Field(default=None, gt=0, le=1_000_000_000)


class SourceRevealOut(Schema):
    """소스 펼침 응답 (#60, ADR-0022).

    #59 이전에는 상세 조회의 부수 효과로 새던 바로 그 내용(`Score.prompt`)이다 —
    이제는 이 명시적 `POST` 요청에서만, `SourceReading` 을 함께 남기고서만 나온다.
    """

    prompt: str


class SourceReadingOut(Schema):
    """Developer 가 보는 자기 Submission 의 소스 열람 기록 한 건 (#61, ADR-0022).

    **누가 봤는지는 여기 없다.** 시각과 횟수만으로 "심판 과정에서 몇 번 열렸다"는
    약속을 검증할 수 있고, 운영자 신원을 참가자에게 흘리면 ADR-0018 이 서로소로
    갈라놓은 두 경계 사이에 새 문제가 생긴다.
    """

    read_at: datetime
