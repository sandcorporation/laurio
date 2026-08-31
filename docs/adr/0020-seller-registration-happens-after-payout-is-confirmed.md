# Seller 등록은 Payout이 확정된 뒤에만 시작한다

ADR-0008은 계좌·본인확인·KYC를 토스 지급대행에 위임하고 Laurio는 `sellerId`만
보관한다고 적었지만, 그 등록을 **언제** 하는지는 정하지 않았다. 코드에는
`Seller`라는 개념 자체가 없었다 — `sellerId`도, 등록 상태도, 미등록 시의 지급
경로도 없었다. 제출 시점이나 가입 시점에 미리 등록하면 압도적 다수인
미수상자까지 전부 지급대행사에 신원 정보를 넘기게 되고 제출 문턱도 함께
올라간다 — `Verification`을 가입이 아니라 행위 시점(Submission 제출·Contest
개최)으로 미룬 것(ADR-0011)과 같은 이유로, Seller 등록도 Payout이 확정된
뒤로 미룬다. 구경하거나 떨어진 Developer가 지급대행사에 신원 정보를 넘길
이유가 없다.

등록은 두 단계다: 본인인증을 마치면 부분 승인 상태가 되어 주간 한도
(기본 1천만원) 안에서 지급받을 수 있고, 그 이상은 심사가 필요하다. 짧은
기간에 여러 Contest에서 수상한 Developer가 한도를 넘겼다는 이유로 지급을
완전히 막으면, 성공한 사람을 성공했다는 이유로 벌하는 셈이 된다 — 그래서 한도
초과는 실패가 아니라 심사 대기로 다룬다. 등록이 거절되는 경우도 마찬가지로
`Payout`을 실패로 되돌리지 않는다.

## Consequences

`Payout.Status`에 `CONFIRMED_SELLER_PENDING`("지급 확정 · Seller 대기")이
정식 상태로 하나 더 생긴다. ADR-0008이 만든 `CONFIRMED_IDENTITY_PENDING`
("지급 확정 · 신원 대기")과는 **다른 것**을 기다린다 — 하나는 Laurio의 세무
(주민등록번호)를, 하나는 지급대행사의 수취인 등록을 기다린다. 뭉치면 Operator가
어느 쪽을 처리해야 하는지 알 수 없으므로 두 상태를 분리해 조회 가능하게 둔다
(`GET /operator/payouts?blocked_on=identity|seller`).

`sellerId`는 `Developer`에 남는다(`Seller` 모델, `accounts.DeveloperProfile`과
1:1) — 두 번째 Payout부터는 이미 부분 승인된 Seller가 있으면 재등록하지 않는다
(`payouts.services.ensure_seller_registered`). 등록이 거절되거나 심사가
길어져도, Payout이 확정되는 시점에 이미 원장에 개발자 미지급금으로 남은
금액은 그대로 남는다(ADR-0004) — Seller 상태가 그 금액을 움직이거나
지우지 않는다.

Developer는 자신의 Payout이 두 대기 중 무엇을 기다리고 있으며 다음에 무엇을
해야 하는지를 화면에서 볼 수 있다(`PayoutOut.seller_status`/`next_action`) —
침묵은 상금이 사라진 것으로 읽히기 때문이다.

실물 토스 지급대행 셀러 등록 연동은 이 ADR의 범위 밖이다(#57) — 여기서는
`SellerAdapter` 계약과 `FakeSellerAdapter`(부분 승인·한도 초과·심사 필요·거절
네 시나리오를 `simulate`로 흉내낸다, `FakePGAdapter`와 같은 관용구)만 정한다.
그래서 이 결정은 staging 없이도 평소 HTTP 시임에서 전부 검증된다.
