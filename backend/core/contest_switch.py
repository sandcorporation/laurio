"""공모전 제품 스위치 (#271, ADR-0037).

방향이 바뀌었다 — 공모전은 나중을 위한 기능이고, 지금 사람을 모을 것은 강의실이다.
`settings.CONTEST_PRODUCT_ENABLED` 하나로 갈린다. **기본값은 켜짐**이고, staging
배포(`docker/compose.staging.yaml`)만 기본을 꺼짐으로 겹쳐 쓴다 —
`LAURIO_DEPLOYMENT_TARGET`과는 무관한 독립 값이다(나중에 prod에서 다시 켤 때 그
판단 규칙 자체를 고칠 필요가 없게).

지우는 것은 하나도 없다 — 코드도 테스트도 데이터도 그대로다. 닫는 것은 **표면**뿐이다.

**꺼졌을 때 닫히는 표면 — 다시 켜는 날 읽을 목록, 흩어지면 하나를 빠뜨린다.**

백엔드(`require_contest_product_enabled()`가 404를 낸다 — 403은 "권한이 없다"로
읽혀 존재를 알려주므로 쓰지 않는다):

- `contests.api`의 전부 — 공모전 개최·수정·재개(`create_contest`/
  `update_draft_contest`/`reopen_contest`), 심사기간 연장 결제
  (`initiate_judging_period_extension`/`confirm_judging_period_extension`), 요구사항
  AI grill 대화(`send_requirement_chat_message`/`list_requirement_chat_messages`),
  Requirement CRUD, 공모전 이미지 CRUD, 견적(`quote`), 공모전 목록·상세·홈 큐레이션·
  내가 개최한 목록·조회수 기록(`list_contests`/`get_contest`/`get_home_curation`/
  `list_my_sponsored_contests`/`record_contest_view`).
  **`list_categories`/`list_deliverable_types`는 예외다** — `/contests/` 주소
  아래 살지만 주소만으로는 어느 제품의 것인지 갈리지 않는 공용 참조 데이터라 열어
  둔다. 이 스위치가 닫는 것은 어디까지나 **공모전** 표면이지 참조 데이터 자체가
  아니다.
- `payments.api`의 공모전 결제 — `initiate_payment`/`confirm_payment`. 웹훅
  (`receive_webhook`)은 닫지 않는다 — PG가 서버 대 서버로 부르는 자리라 존재를
  숨길 대상이 아니고, 이 스위치가 꺼진 뒤로는 `initiate_payment`가 막혀 있어 새
  Payment가 REQUESTED로 생길 길이 없다.

**열어 두는 것 — 과제가 건드리지 않는 것만 닫는다는 원칙 그대로.**

- `submissions.api`의 `/contests/{contest_id}/submissions` 등 — 주소가
  `/contests/`로 시작하지만 `contests.api`가 아니라 `submissions` 앱 소유다.
- `contests.operator_api`(운영자 앱) — 사람만 보는 화면이고, 남은 공모전 데이터를
  마무리하려면 오히려 열려 있어야 한다.

**스캔 등록** — 각 앱의 `ScanSpec`이 `enabled=contest_product_enabled`를 준다
(`core.scans.ScanSpec.enabled`). 꺼지면 그 스캔은 `/api/internal/tick`·
`/api/internal/scans/{name}`·Celery beat 스케줄 어디에서도 등록된 적 없는 것처럼
사라진다(`core.scans.is_scan_active`).

- 등록에서 사라짐(돈이 실제 결제 대행사로 나가는 경로): `payment-refund-request`·
  `payment-refund-reconcile`(payments, 환불 둘) · `distribution-create`·
  `distribution-share-payout`(distributions, 배분) · `payout-awaits-you`·
  `seller-registration-recovery`(payouts, 지급 관련) · `handover-release`(handovers,
  인수인계 — Award는 Contest 전용이라 Handover도 Contest 전용이다).
- 그대로 등록됨(과제가 쓰거나 제품과 무관하다): `submission-scoring`(scoring,
  채점) · `repository-visibility`(repositories, 저장소 가시성) · 알림 스캔들
  (notifications) · `identity-dormancy-purge`·`retained-identity-purge`(accounts,
  휴면·신원 파기) · `demo-video-retention-purge`(submissions) · `contest-close`·`contest-judging-end`·Contest 이미지 최적화(contests
  — 전이는 돈을 옮기지 않고, 이미지 최적화는 참고 이미지를 다룬다).
"""

from __future__ import annotations

from django.conf import settings
from ninja.errors import HttpError


def contest_product_enabled() -> bool:
    """`core.scans.ScanSpec.enabled`가 그대로 콜백으로 넘기는 자리 — 매 호출마다
    현재 설정값을 다시 읽는다(재기동 없이 override_settings로 테스트할 수 있어야
    한다)."""

    return settings.CONTEST_PRODUCT_ENABLED


def require_contest_product_enabled() -> None:
    """공모전 표면 진입점에서 맨 먼저 부른다 — 꺼져 있으면 404(#271).

    403이 아니라 404인 이유: 403은 "권한이 없다"로 읽혀 그 리소스가 존재한다는
    사실 자체를 드러낸다. 이 표면은 존재 자체를 감춰야 한다 — 공모전 draft를 타인이
    보지 못하게 감추는 것(`contests.api.get_contest`)과 같은 원칙이다.
    """

    if not contest_product_enabled():
        raise HttpError(404, "찾을 수 없습니다.")
