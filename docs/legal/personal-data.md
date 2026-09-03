# 개인정보 — 개인정보 보호법 · 정보통신망법 · CI 고시

> 법률 자문이 아니다. 색인은 [README.md](README.md). 용어(Verification·Withdrawal·
> RetainedIdentity·IdentityReading·Notification)는 [CONTEXT.md](../../CONTEXT.md) 의
> 정의를 따른다.

## 무엇을 언제 받는가 — 행위 시점에만

가입과 열람에는 소셜 로그인만 요구하고, 개인정보는 **그것이 필요한 행위의 시점**에만
받는다. 구경만 하는 사람의 정보를 들고 있지 않기 위해서다.

| 시점 | 항목 | 누가 받는가 | 왜 | 코드 |
| --- | --- | --- | --- | --- |
| 가입 | 소셜 로그인 식별자 | Laurio | Authentication — 실명과 무관 | `backend/accounts/social.py`, [ADR-0013](../adr/0013-social-login-only.md) |
| Submission 제출 · Contest 개최 | 실명·생년월일·CI·DI·전화번호 | 포트원 본인확인 → Laurio 저장 | 만 19세 확인, 자전거래 차단, 통지 | `backend/verification/models.py` `Verification`, [ADR-0011](../adr/0011-verification-at-action-time-and-adults-only.md) |
| Payout 확정 | 주민등록번호 | Laurio | 지급명세서 ([tax.md](tax.md)) | `backend/payouts/models.py` `TaxIdentity` |
| Payout 확정 후 Seller 등록 | 이름·이메일·전화번호·계좌, 본인인증·KYC | **토스가 직접** — Laurio 는 `sellerId` 만 | 지급대행사 자신의 의무 | [ADR-0020](../adr/0020-seller-registration-happens-after-payout-is-confirmed.md) |

CI 를 주지 않는 본인확인 수단(카카오 통합인증)은 본인확인으로 인정하지 않는다 —
빈 CI 가 같은 해시로 뭉쳐 남남을 동일인으로 오차단한 사고가 있었다
([ADR-0024](../adr/0024-verification-methods-must-provide-ci.md)). 그래서 수상한
Developer 는 본인인증을 **두 번** 한다(포트원 → CI, 토스 → 셀러 온보딩). 합칠 수 없고
화면이 미리 말해야 한다(ADR-0020).

**한 계정의 신원은 다른 사람의 것으로 바뀌지 않는다.** 이미 CI 가 있는 계정에 다른
CI 로 본인확인이 들어오면 거부한다 — 성인으로 확인받아 개최한 사람이 재확인으로
미성년이 되어 자전거래 차단이 꺼지는 경로를 막는다(ADR-0025).

## 저장 — 암호화와 분리

실명·생년월일·CI·DI 는 Fernet 으로 암호화해 저장하고 CI 는 비교용 HMAC 해시를 따로
둔다(`backend/verification/crypto.py`). 주민등록번호는 같은 헬퍼로 암호화하되
**Verification 과 다른 테이블**에 둔다 — 용도(신원 확인 vs 세무 신고)가 다르다.

## 파기 — 개인정보 보호법 21조

목적이 달성돼 불필요해진 개인정보는 지체 없이(시행령상 5일 이내) 파기해야 한다.
이 저장소는 한동안 신원을 지우는 코드가 한 줄도 없었고, 그것을
[ADR-0025](../adr/0025-withdrawal-erases-identity-not-the-account.md) 가 고쳤다.

| 사건 | 무엇이 지워지는가 | 무엇이 남는가 | 코드 |
| --- | --- | --- | --- |
| **탈퇴** (Withdrawal) | CI·DI·전화번호·표시 이름·소개 즉시. 계정은 비활성화 | Contest·Submission·원장·Payout. 거래가 있었으면 실명·생년월일이 RetainedIdentity 로 | `backend/accounts/withdrawal.py` |
| **2년 무행위** | 신원만 (위와 같은 항목). 계정·로그인·Submission 은 그대로, 다음 행위 때 재확인 | 위와 같음 | `backend/accounts/dormancy.py` `DORMANCY_PERIOD` |
| **보존 만료** (5년) | RetainedIdentity 행 | — | `core.tasks.call_accounts_purge_expired_identities` (Celery beat 스캔) |

세 가지 판단이 이 표 뒤에 있다:

- **탈퇴는 계정 삭제가 아니라 신원 파기다.** 삭제 연쇄를 따라가면 참조 보호가 삭제를
  통째로 막거나, 다른 사람의 참가작과 Award 기록까지 함께 사라진다. 그래서 지우는
  것은 행이 아니라 값이다. 진행 중인 거래가 있으면 탈퇴할 수 없고, 유예 기간 없이
  즉시 지우므로 되돌릴 수 없다.
- **CI 와 실명의 운명이 갈린다.** CI·DI 는 동일인 판별용이라 목적이 탈퇴로 끝나
  즉시 파기한다. 실명·생년월일은 계약·대금결제 기록의 일부라 거래가 있었던 사람에
  한해 5년 남긴다(전자상거래법 시행령, [commerce-and-payments.md](commerce-and-payments.md)).
  위시켓은 「부정이용 방지」로 탈퇴 후 24개월간 CI·DI 를 남기지만 **우리는 따르지
  않는다** — 참가자 제재 개념이 없어 재가입으로 우회할 것이 없고, 그러면 목적 없는
  보유다. 제재 개념이 생기면 이 결정을 다시 연다.
- **휴면 2년은 자율로 정한 값이다.** 개인정보 유효기간제(휴면 1년 의무)는 2023년
  9월 폐지됐다. Contest 한 사이클(마감 21일 + 심사 7일 + 배분 대기 14일)을 여러 번
  건너뛴 길이로 골랐다.

## 보존과 파기가 충돌하는 곳 — RetainedIdentity

법이 파기 의무와 보존 의무의 충돌에 대해 정해 둔 답은 「다른 개인정보와 분리하여
저장·관리」다. CI 고시(방송통신위원회고시 제2025-4호)가 논리적 분리를 명시적으로
인정하므로 별도 DB 가 아니라 **별도 테이블**로 한다. 그 테이블에는 CI·DI 칼럼
자체가 없다 — 자리가 없어야 나중에 채워 넣지 않는다. 살아 있는 신원과 같은 자리에
두지 않는 이유는 「지운 것」과 「보존해야 해서 남긴 것」이 구별돼야 하기 때문이다.

## 누가 보는가 — 열람은 사건으로 남는다

감춘다는 약속이 운영자 앞에서만 조용히 사라지면 그 약속은 없던 것과 같다
([ADR-0022](../adr/0022-operator-may-read-source-but-every-reading-is-recorded.md)).
그래서 Operator 가 보존된 실명을 펼치면 `IdentityReading`, 제출 소스를 펼치면
`SourceReading` 이 남는다 — 기본은 접혀 있고 명시적으로 펼 때만 값이 내려오며,
누가·언제·어느 행을 봤는지가 쌓인다(중복 제거하지 않는다 — 「한 번」과 「열 번」이
구별돼야 기록에 값이 있다). 두 모델 다 PROTECT 라 Operator 계정을 지우는 것으로
기록이 사라지지 않는다.

이 기록에는 **읽는 사람이 있어야 한다.** 최소한 Developer 가 자기 소스가 언제
열람됐는지 볼 수 있어야 기록이 약속을 지키는 장치가 된다 — 그러지 않으면 우리
자신을 위한 알리바이다. 고지 항목이기도 하다([contracts-and-ip.md](contracts-and-ip.md)).

## 위탁과 제3자 제공

개인정보처리방침이 열거해야 할 상대들이다. 방침 문서 자체는 아직 없다(열린 항목 1).

| 상대 | 무엇이 나가는가 | 성격 |
| --- | --- | --- |
| 포트원 (KG이니시스 통합인증) | 본인확인 요청 — 실명·생년월일·CI·DI 가 **들어온다** | 위탁 |
| 토스페이먼츠 | 결제 정보, Seller 등록 시 이름·이메일·전화번호 | 위탁 (지급대행은 토스 자신의 의무이기도 하다) |
| 카카오 (알림톡) · SMS 사업자 | 전화번호, 통지 본문 | 위탁 |
| 소셜 로그인 제공자 | 로그인 식별자 | 제공받음 |
| 오브젝트 스토리지 (S3/OCI) | 제출 파일·소스 | 위탁 |
| **OpenAI** | **제출 소스코드와 자가 응답** — AI 채점 프롬프트에 선별된 소스 파일이 통째로 들어간다 | 위탁 + **국외 이전** — 열린 항목 7 |

## 통지 — 정보통신망법

Notification 은 거래성과 광고성으로 나뉘고 **광고성만 사전 동의**를 요구한다
(`backend/notifications/models.py` — 유형마다 `is_transactional`/`is_promotional`,
`NotificationOptIn`, 옵트인 없으면 `BLOCKED_NO_OPT_IN`). 지금 광고성은
`NEW_CONTEST_IN_CATEGORY` 하나다.

야간(21~08시)에는 법이 요구하는 것보다 더 막는다 — 정보통신망법은 광고성 정보의
야간 전송에만 별도 동의를 요구하지만, 거래성 통지까지 **전면 연기**한다(폐기가
아니라 다음 날 08시 발송, [ADR-0010](../adr/0010-quiet-hours-defer-not-drop.md)).
민감 시간대 민원을 없애기 위한 의도적 초과 준수다. 반드시 닿아야 하는 통지
(Distribution 최종 경고)는 애초에 낮 시각 고정 발송으로 잡는다.

도달 여부와 무관하게 발송 이력이 통지의 증거다(ADR-0009) — 채널별 발송 시각·결과·
실패 사유를 전부 보존하고 Sponsor 화면에도 노출한다. 이 발신주의가 약관에서
다퉈질 여지는 [contracts-and-ip.md](contracts-and-ip.md) 열린 항목 10 이다.

## 열린 항목

1. **개인정보처리방침이 없다.** 위 표의 수집 항목·시점·보존 기간·위탁 상대를
   열거하는 문서가 저장소에도 화면에도 없다.
7. **소스가 OpenAI 로 나간다.** 개인정보 측면(소스에 개인정보가 섞여 있을 수 있다)과
   저작물·영업비밀 측면 양쪽에서 Developer 에게 고지돼야 하고, 국외 이전 항목으로
   방침에 들어가야 한다. ADR-0022 는 LLM 이 쓴 판정 근거(`reasoning`)에 소스 조각이
   딸려 나오는 경계까지 측정해 두었다 — 고지에 그 구분이 들어가야 한다.
9. **정당하게 CI 가 바뀌는 사람이 잠긴다.** 주민등록번호 변경(유출 피해, 성별정정)과
   계정 탈취 후 진짜 주인의 복구는 CI 가 바뀌어 「다른 사람」으로 거부된다. 사람의
   판단 경로(고객센터)가 생길 때까지 거부가 기본이고, 그때까지 이들은 새 계정을
   만드는 수밖에 없다(ADR-0025).
