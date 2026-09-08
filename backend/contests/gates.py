"""종류(`Contest.kind`)에 의존하는 게이트가 사는 **한 자리** (#232, ADR-0033).

`Contest.Status.*` Classification 은 **status 만의 순수 함수**다(`core/classification.py`).
그 계약이 21개 스캔과 14개 분류를 떠받치고 있어 값싸고 정확하지만, 대신 답할 수 없는
질문이 하나 있다 — **「이 행이 공모전인가 과제인가」**. `DRAFT` 를 둘이 공유하므로
(ADR-0028) 아직 열리지 않은 과제는 어떤 status 분류로도 공모전과 구별되지 않는다.

그 구멍이 실제로 두 번 열렸다. #207 에서는 편집 표면(`PATCH /api/contests/{id}`)이,
#232 에서는 **결제**(`POST /api/payments`)가 그랬다 — 둘 다 `status` 만 보고 통과시켰다.
#207 을 닫을 때 결제 쪽에는 본인확인 재검사를 심층 방어로 뒀는데, 그것은 **인증만**
보므로 인증을 마친 사람에게는 문이 그대로 열려 있었다: 자기 과제에 결제를 걸면
`Payment.on_paid()` 가 DRAFT → PUBLISHED 로 옮겨 `kind` 는 과제인데 공개 목록에 뜨는
모순된 행이 됐다(상금 0원짜리가 개최비만 내고 발행된다).

**그래서 그런 질문을 이 모듈 하나에 모은다.** 새 엔드포인트를 더하는 사람이 무엇을
기억할 필요가 없어야 한다 — `Contest.Status.PAYABLE` 을 직접 부르는 자리는
`tests/test_contest_kind_gates.py` 가 막고, 그 테스트가 여기로 안내한다.

**ADR-0033 이 합성 Classification(`(status, kind)` 쌍마다 답하는 표)을 검토하고
기각했다** — 지금 계약에 기댄 코드가 너무 많고, `kind` 가 실제로 갈라야 하는 분류는
소수라서다. 이 모듈이 그 소수를 담는 자리다.
"""

from __future__ import annotations

from contests.models import Contest


def payable(contest: Contest) -> bool:
    """이 Contest 에 대해 Prize + 개최 등록비 결제를 시작할 수 있는가.

    과제에는 상금도 개최비도 없다(ADR-0028/0029) — 결제라는 개념 자체가 없으므로
    status 를 보기 전에 종류에서 걸린다. 반대 방향은 `Contest.Status.PAYABLE` 이
    그대로 답한다(이미 결제가 끝나 공개된 Contest 인가).
    """

    if contest.is_assignment:
        return False
    return Contest.Status.PAYABLE(contest.status)
