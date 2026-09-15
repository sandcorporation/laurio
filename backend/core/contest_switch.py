"""공모전 제품 스위치 — 「공모전」과 「유료 공모전」 둘 (#271/#413, ADR-0037/ADR-0048).

방향이 한 번 바뀌었다가(ADR-0037, 공모전을 통째로 껐다) 다시 열렸다 — 다만 **돈을
다루지 않는 무료 공모전**만이다(ADR-0048, CONTEXT.md 「무료 공모전」). 그래서 스위치가
둘이다:

- **공모전** (`settings.CONTEST_PRODUCT_ENABLED`) — 목록·상세·홈 큐레이션·조회수·
  제출·채점·수상 등 무료 공모전도 필요로 하는 표면 전체. 이게 꺼지면 유료도 함께
  꺼진다(공모전 표면이 없는데 그 안의 유료 경로만 열려 있을 수 없다).
- **유료 공모전** (`settings.PAID_CONTEST_PRODUCT_ENABLED`) — 견적·결제·본인확인이
  필요한 유료 개최(신규·재개최)·유료 심사기간 연장과, 환불·배분·지급·인수인계처럼
  돈이 실제로 옮겨가는 스캔. **공모전 스위치가 켜져 있어야만** 의미가 있다 —
  `paid_contest_product_enabled()`가 두 값을 AND로 묶는 이유다.

**기본값은 둘 다 켜짐**이다. `CODEMIT_DEPLOYMENT_TARGET`과는 무관한 독립 값들이고,
staging·prod 배포(`docker/compose.staging.yaml`/`docker/compose.prod.yaml`)만 유료
스위치의 기본을 꺼짐으로 겹쳐 쓴다(공모전 스위치는 이제 그대로 켜짐이다) — dev·CI는
둘 다 건드리지 않으므로 여전히 켜진 채다.

지우는 것은 하나도 없다 — 코드도 테스트도 데이터도 그대로다. 닫는 것은 **표면**뿐이다.

**공모전 스위치가 꺼졌을 때 닫히는 표면 — 다시 켜는 날 읽을 목록, 흩어지면 하나를
빠뜨린다.**

백엔드(`require_contest_product_enabled()`가 404를 낸다 — 403은 "권한이 없다"로
읽혀 존재를 알려주므로 쓰지 않는다):

- `contests.api`의 전부 — 공모전 목록·상세·홈 큐레이션·내가 개최한 목록·조회수
  기록(`list_contests`/`get_contest`/`get_home_curation`/`list_my_sponsored_
  contests`/`record_contest_view`), Contest 수정(`update_draft_contest`), 요구사항
  AI grill 대화, Requirement CRUD, 공모전 이미지 CRUD. 그리고 **유료 스위치가 닫는
  것 전부**(아래) — 공모전 스위치가 꺼지면 유료 경로도 당연히 함께 닫힌다.
  **`list_categories`/`list_deliverable_types`는 예외다** — `/contests/` 주소
  아래 살지만 주소만으로는 어느 제품의 것인지 갈리지 않는 공용 참조 데이터라 열어
  둔다.

**열어 두는 것 — 과제가 건드리지 않는 것만 닫는다는 원칙 그대로.**

- `submissions.api`의 `/contests/{contest_id}/submissions` 등 — 주소가
  `/contests/`로 시작하지만 `contests.api`가 아니라 `submissions` 앱 소유다.
- `contests.operator_api`(운영자 앱) — 사람만 보는 화면이고, 남은 공모전 데이터를
  마무리하려면 오히려 열려 있어야 한다.

**유료 스위치가 (공모전은 켜진 채) 꺼졌을 때 추가로 닫히는 표면.**

백엔드(`require_paid_contest_product_enabled()`가 404를 낸다 — 위와 같은 이유):

- `contests.api`의 견적(`quote`), 본인확인이 필요한 유료 개최·재개최
  (`create_contest`/`reopen_contest` — 무료 개최는 아직 없으므로 지금은 이 둘이
  유일한 개최 경로다, #415가 무료 개최를 더할 때까지), 유료 심사기간 연장
  (`initiate_judging_period_extension`/`confirm_judging_period_extension`).
- `payments.api`의 공모전 결제 — `initiate_payment`/`confirm_payment`. 웹훅
  (`receive_webhook`)은 닫지 않는다 — PG가 서버 대 서버로 부르는 자리라 존재를
  숨길 대상이 아니고, 유료 스위치가 꺼진 뒤로는 `initiate_payment`가 막혀 있어 새
  Payment가 REQUESTED로 생길 길이 없다.

**스캔 등록** — 각 앱의 `ScanSpec`이 `enabled=paid_contest_product_enabled`를 준다
(`core.scans.ScanSpec.enabled`). 꺼지면 그 스캔은 `/api/internal/tick`·
`/api/internal/scans/{name}`·Celery beat 스케줄 어디에서도 등록된 적 없는 것처럼
사라진다(`core.scans.is_scan_active`).

- 등록에서 사라짐(돈이 실제 결제 대행사로 나가는 경로 — 유료 스위치가 꺼지면):
  `payment-refund-request`·`payment-refund-reconcile`(payments, 환불 둘) ·
  `distribution-create`·`distribution-share-payout`(distributions, 배분) ·
  `payout-awaits-you`·`seller-registration-recovery`(payouts, 지급 관련) ·
  `handover-release`(handovers, 인수인계 — Award는 유료·무료 공모전 모두에 생기지만
  Handover·Escrow 해제는 유료 전용이다).
- 그대로 등록됨(과제가 쓰거나 제품과 무관하거나, 무료 공모전도 필요로 한다):
  `submission-scoring`(scoring, 채점) · `repository-visibility`(repositories,
  저장소 가시성) · 알림 스캔들(notifications) · `identity-dormancy-purge`·
  `retained-identity-purge`(accounts, 휴면·신원 파기) · `demo-video-retention-
  purge`(submissions) · `contest-close`·`contest-judging-end`·Contest 이미지
  최적화(contests — 전이는 돈을 옮기지 않고, 무료 공모전도 마감·심사종료·수상을
  거친다) — 이 넷은 **공모전 스위치**만 본다(`enabled=contest_product_enabled`인
  채 그대로다).
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


def paid_contest_product_enabled() -> bool:
    """유료 공모전 스위치 — 공모전 스위치 자체가 꺼지면 함께 꺼진 것으로 본다(#413).

    `settings.PAID_CONTEST_PRODUCT_ENABLED` 하나만 보면, 공모전 스위치가 꺼진 채
    유료 스위치만 (기본값대로) 켜져 있는 어긋난 조합에서 유료 경로가 열려 있는
    것처럼 보일 수 있다 — 유료는 공모전의 부분집합이라 상위 스위치를 무시하고
    유료만 볼 수 없다.
    """

    return settings.CONTEST_PRODUCT_ENABLED and settings.PAID_CONTEST_PRODUCT_ENABLED


def require_paid_contest_product_enabled() -> None:
    """유료 공모전 표면 진입점에서 맨 먼저 부른다 — 꺼져 있으면 404(#413).

    `require_contest_product_enabled()`와 같은 이유로 403이 아니라 404다.
    """

    if not paid_contest_product_enabled():
        raise HttpError(404, "찾을 수 없습니다.")
