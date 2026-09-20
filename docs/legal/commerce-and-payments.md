# 사업자 요건과 돈의 흐름 — 전자상거래법 · 전자금융거래법 · 여신전문금융업법

> 법률 자문이 아니다. 근거와 확인 상태는 각 절에 적었다. 색인은 [README.md](README.md).

## Codemit 는 통신판매중개자다

Sponsor 가 Contest 를 열고 Developer 가 Submission 을 내며, 상금은 Sponsor 에게서
Developer 에게로 간다. Codemit 는 그 사이에 서는 **통신판매중개자**이고, 그래서
전자상거래법이 요구하는 것이 셋이다([REQUEST.md](../../REQUEST.md) 「필요한 사업자
요건」):

- **사업자등록**
- **통신판매업 신고** — 구매안전서비스 확인증이 필요하다 (아래 「열린 항목」 2)
- **통신판매중개자 표시·고지 의무** — 중개자임과 책임 범위를 화면에 밝혀야 한다.
  화면도 약관도 아직 없다 ([contracts-and-ip.md](contracts-and-ip.md) 「약관·고지
  항목」)

알림톡을 주채널로 쓰는 것([ADR-0009](../adr/0009-alimtalk-primary-and-distribution-proceeds-on-nondelivery.md))도
사업자등록·카카오 채널 개설·템플릿 사전심사를 선행 조건으로 건다.

## 상금은 Codemit 가 보관하지 않는다

「플랫폼에 상금을 비치한다」는 것은 법적으로 **남의 돈을 보관하는 행위**라
결제대금예치업(전자금융업) 등록이 필요하고, 자본금 10억·전산 전문인력 5인·물적설비가
요구된다. 2024년 전자금융거래법 개정으로 플랫폼의 정산대금 별도관리·예치 의무도
강화됐다. 그래서 **자체 예치·정산 설계를 하지 않는다** — 결제와 지급을 PG·지급대행사에
위임하고, Codemit 는 그 흐름을 원장으로 기록한다.

| 단계 | 누가 돈을 쥐는가 | 코드 |
| --- | --- | --- |
| Sponsor 결제 (상금 + 개최비) | 토스페이먼츠 | `backend/payments/adapters_toss.py` |
| Award·Distribution 까지 | 토스 정산 계좌 — Codemit 원장에는 「발주자 예치금 → 개발자 미지급금」으로 기록 | `backend/ledger/models.py` `Account`, [ADR-0004](../adr/0004-double-entry-ledger.md) |
| Developer 지급 | 토스 지급대행 (`sellerId` 로 이체) | `backend/payouts/`, [ADR-0008](../adr/0008-toss-handles-identity-laurio-handles-tax.md), [ADR-0020](../adr/0020-seller-registration-happens-after-payout-is-confirmed.md) |

원장이 복식부기이고 append-only 인 것은 회계 취향이 아니라 이 구조의 결과다 — 돈을
쥐지 않는 대신 「이번 달 들어온 돈과 나간 돈이 1원 단위로 맞는가」에 언제든 답할 수
있어야 한다. 원천징수 예수금은 국세청에 낼 남의 돈이라 별도 계정이다
([tax.md](tax.md)).

**용어 주의.** [CONTEXT.md](../../CONTEXT.md) 의 **Escrow** 는 「결제된 Prize 가
Payout 또는 환불로 나가기 전까지 머무는 원장 상태」의 이름이지, PG 가 파는 법적
에스크로(구매안전서비스) 상품이 아니다. 둘을 같은 것으로 읽으면 열린 항목 2 가
보이지 않는다.

## 환불 — 참가자가 한 명이라도 있으면 Sponsor 에게 돌아가지 않는다

Prize 는 Payout 또는 환불로만 빠져나가고, 참가자가 한 명이라도 있으면 Sponsor 에게
되돌아가지 않는다(CONTEXT.md 「Escrow」). Sponsor 가 기한 내 Award 하지 않으면
컷라인을 넘긴 Submission 들에 1/N 로 배분되고(Distribution), 통지가 닿지 않아도
진행한다(ADR-0009). 참가자가 없을 때만 환불 스캔이 돈다
(`backend/payments/services.py` `run_pending_refunds`).

이 규칙은 플랫폼의 핵심 약속이지만 **약관에 적혀야 성립한다** — 열린 항목 3 도
같이 본다.

## 자전거래와 카드 현금화

Sponsor 가 지인을 참가시켜 선정하고 상금을 회수하는 자전거래는 본인확인의 CI 로
동일인이면 **제출 단계에서 차단**한다(`backend/contests/submission_participation.py`,
#472 확인 — 예전 문서는 `backend/submissions/api.py`를 가리켰는데 그 파일에는
라우터가 없다, [ADR-0011](../adr/0011-verification-at-action-time-and-adults-only.md)).
이 약속은 본인확인 수단이 실제로 CI 를 줄 때만 성립하므로 CI 없는 수단은 본인확인으로
인정하지 않는다([ADR-0024](../adr/0024-verification-methods-must-provide-ci.md)).

**이 차단은 지금 무료 공모전에는 서지 않는다(#472 확인).**
`_require_verification_unless_free`(`backend/contests/submission_api.py`)가
무료 공모전이면 본인확인 자체를 건너뛰고, 그 결과 CI 가 없어 동일인 판정도
함께 건너뛴다(ADR-0048) — 지금 유료 공모전 스위치가 꺼져 있으므로 이 문단이
막는 경로는 아직 아무 공모전에도 없다. 자전거래·카드 현금화 금지는 그동안
약관상의 의무로만 선다([contracts-and-ip.md](contracts-and-ip.md) 15행).

REQUEST.md 「부정행위」가 남긴 경고: 수수료는 이득 목적의 자전거래는 막지만 **카드
현금화에서는 억제력이 아니라 서비스 가격**이고, 그때 플랫폼에 남는 것은 손실이
아니라 **여신전문금융업법 책임**이다. CI 차단이 그 경로의 유일한 방어다.

## 거래 기록은 5년 남는다

전자상거래법 시행령의 「대금결제 및 재화등의 공급에 관한 기록」 보존 기간(5년)을
따른다. Contest·Submission·원장·Payout 은 계약 상대방의 기록이라 한 사람의
탈퇴로 사라지지 않고, 거래가 있었던 사람의 실명·생년월일만 별도 테이블에 5년 남긴다
(`backend/verification/models.py` `RETAINED_IDENTITY_RETENTION_PERIOD`,
[ADR-0025](../adr/0025-withdrawal-erases-identity-not-the-account.md)). 무엇을
남기고 무엇을 지우는지는 [personal-data.md](personal-data.md) 에 있다.

## 열린 항목

2. **구현된 결제는 에스크로가 아니다.** REQUEST.md 는 「PG 에스크로·지급대행 상품을
   연동하면 구매안전서비스 확인증도 함께 해결된다」고 봤는데, 실제
   `adapters_toss.py` 는 토스 일반 결제(승인·취소·조회)만 쓰고 에스크로 옵션을 켜지
   않는다. 통신판매업 신고에 필요한 확인증을 무엇으로 충족할지 다시 정해야 한다 —
   토스 에스크로 옵션을 켜는 것, 별도 보증보험, 또는 이 서비스 구조에서 확인증이
   필요한지 자체를 확인하는 것 중 하나다.
3. **개인 소비자인 Sponsor 의 청약철회권.** 「참가자가 한 명이라도 있으면 환불
   없음」은 Sponsor 가 사업자면 계약 조건이지만, 개인이 Contest 를 열 수 있는 이상
   전자상거래법 17조 청약철회와의 관계를 확인해야 한다. 참가자가 생기는 순간을
   「재화의 공급이 개시된 때」로 볼 수 있는지가 핵심이다.

약관 화면은 이제 있지만(#472) 통신판매중개자 고지는 사업자 등록이 끝나야 채울 수
있다 — [contracts-and-ip.md](contracts-and-ip.md)의 열린 항목 1, 그리고
[README.md](README.md)의 열린 항목 1이 같은 자리를 가리킨다.
