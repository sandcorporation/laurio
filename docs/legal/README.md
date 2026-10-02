# 법률 관련 문서

이 폴더는 **지도**다. 어느 법이 이 서비스의 어디에 닿는지, 그 지점에서 무엇을 정했고
코드가 그것을 어디서 지키는지, 그리고 무엇이 아직 확인되지 않았는지를 한 곳에서
찾게 한다. 결정의 **원문은 `docs/adr/`** 에, 요율·기간 같은 **값은 코드와
`PlatformPolicy`** 에 있다 — 이 폴더는 그 둘을 베끼지 않고 가리킨다. 값이 바뀌면
코드와 ADR 을 고치고 여기서는 링크만 확인한다.

> **이 문서들은 법률 자문이 아니다.** 공개 자료를 읽고 벤더(토스페이먼츠·포트원)에
> 직접 물어 정한 것이다. 벤더에게 확인받은 항목은 그렇게 표시했고, 나머지는 변호사·
> 세무사 확인이 필요한 **가정**이다. 확인이 끝나면 해당 문서의 「열린 항목」에서
> 지우고 근거를 적는다.

## 문서

| 문서 | 다루는 법 | 닿는 곳 |
| --- | --- | --- |
| [commerce-and-payments.md](commerce-and-payments.md) | 전자상거래법 · 전자금융거래법 · 여신전문금융업법 | 사업자 요건, 상금 예치·지급 구조, 환불, 자전거래, 거래 기록 5년 보존 |
| [tax.md](tax.md) | 소득세법 | 기타소득 원천징수, 과세최저한, 지급명세서, 주민등록번호 수집, 원장의 예수금 계정 |
| [personal-data.md](personal-data.md) | 개인정보 보호법 · 정보통신망법 · CI 고시 | 수집 시점과 항목, 암호화, 탈퇴·휴면 파기, 보존 신원 분리, 열람 기록, 위탁·국외 이전, 강사가 연결한 앱으로의 전달, 통지 동의와 야간 차단 |
| [contracts-and-ip.md](contracts-and-ip.md) | 민법 · 저작권법 · 약관규제법 | 만 19세 제한, 선정작·탈락작 저작권, 소스 비공개, AI 채점 이의, **약관·고지에 들어가야 할 항목 목록** |

## 법 → 코드 빠른 표

| 법적 요구 | 우리가 정한 것 | 코드 |
| --- | --- | --- |
| 결제대금예치업 등록 없이 남의 돈을 보관할 수 없다 | 결제·지급대행을 토스에 위임, Codemit 는 원장으로 기록만 ([ADR-0004](../adr/0004-double-entry-ledger.md), [ADR-0008](../adr/0008-toss-handles-identity-laurio-handles-tax.md)) | `backend/payments/adapters_toss.py`, `backend/ledger/models.py` |
| 기타소득 원천징수·지급명세서는 지급자가 진다 | 지급대행사가 대신하지 않음을 벤더에 확인, Codemit 가 뗀다 | `backend/payouts/services.py` `_compute_amounts`, `backend/policies/models.py` |
| 미성년자의 법률행위는 취소될 수 있다 | 제출·개최는 만 19세 이상만 ([ADR-0011](../adr/0011-verification-at-action-time-and-adults-only.md)) | `backend/verification/models.py` `Status.UNDERAGE` |
| 같은 법이 상금·IP 이전이 없는 곳에는 걸리지 않는다 | 강의실은 본인확인 없이 열고 낸다 — 나이는 자기신고 ([ADR-0037](../adr/0037-classroom-is-a-bounded-context-not-a-service.md), [ADR-0044](../adr/0044-assignment-is-retired-classroom-replaces-it.md)) | `classroom/api.py` 가 본인확인을 한 번도 부르지 않는다 |
| 불필요해진 개인정보는 지체 없이 파기 (개인정보 보호법 21조) | 탈퇴 = 신원 파기, 2년 무행위 = 신원만 파기 ([ADR-0025](../adr/0025-withdrawal-erases-identity-not-the-account.md)) | `backend/accounts/withdrawal.py`, `backend/accounts/dormancy.py` |
| 거래 기록은 5년 보존 (전자상거래법 시행령) | 거래가 있던 사람의 실명·생년월일만 별도 테이블에 5년 | `backend/verification/models.py` `RETAINED_IDENTITY_RETENTION_PERIOD`, `RetainedIdentity` |
| 광고성 정보는 사전 동의, 야간 전송 별도 동의 (정보통신망법) | 광고성만 옵트인, 21~08시는 거래성까지 연기 ([ADR-0010](../adr/0010-quiet-hours-defer-not-drop.md)) | `backend/notifications/models.py` `NotificationOptIn`, `is_promotional` |
| 수탁자가 아닌 곳으로 나가는 개인정보도 방침에 밝힌다 (개인정보 보호법 제30조) | 강사가 연결한 앱으로의 전달을 위탁(5절)이 아니라 제3자 제공 절(4절)의 예외로 적는다 ([ADR-0052](../adr/0052-instructors-connect-ai-apps-through-our-own-oauth-and-mcp.md)) | `frontend/app/privacy` 4절, `frontend/app/terms` 제6·7·10조 |
| 통신판매중개자 표시·고지 의무 | 약관·방침 화면은 열었다(#472) — 통신판매중개자 표시 자체는 사업자 등록이 끝나고 유료 공모전을 열 때 채운다 | `frontend/app/terms` 8절 |

## 열린 항목 종합

각 문서의 「열린 항목」을 한 줄씩 모은 것이다. 상세와 근거는 각 문서에 있다.

| # | 항목 | 문서 | 성격 |
| --- | --- | --- | --- |
| 1 | ~~약관·개인정보처리방침·통신판매중개자 고지 화면이 저장소에 없다.~~ **#472 로 닫혔다** — `frontend/app/privacy`·`frontend/app/terms`가 공개 앱·강의실 둘 다에서 로그인 없이 열린다(강의실은 자기 사본을 두지 않고 공개 앱으로 링크한다). **남은 것은 사업자 정보(상호·사업자등록번호·대표자·주소)와 통신판매중개자 표시뿐이다** — 사업자 등록(열린 항목 2)이 저장소 밖의 사람 작업으로 아직 끝나지 않아, 있지도 않은 사업자를 있는 것처럼 적을 수 없다. 두 화면의 소스에 `BUSINESS-INFO-PLACEHOLDER` 주석으로 그 자리를 표시해 두었다 — 사업자 등록이 끝나고 유료 공모전 스위치(`CODEMIT_PAID_CONTEST_PRODUCT_ENABLED`)를 켜는 작업이 그 자리와, 유료 전용 조항(환불·배분·지급·인수인계)을 함께 채운다 | contracts-and-ip, personal-data | 부분 구현 — 사업자 정보만 남음 |
| 2 | 구현된 토스 결제는 **에스크로 상품이 아니다.** REQUEST.md 는 PG 에스크로로 구매안전서비스 확인증을 충족한다고 봤다 — 통신판매업 신고 요건을 다시 봐야 한다 | commerce-and-payments | 확인 필요 |
| 3 | Sponsor 가 개인 소비자일 때 「참가자가 한 명이라도 있으면 환불 없음」과 청약철회권의 관계 | commerce-and-payments | 확인 필요 |
| 4 | 반복 참가 Developer 의 상금이 사업소득(3.3%)으로 재분류될 여지 | tax | 세무 검토 |
| 5 | 지급명세서 생성·제출 기능이 없다 — 제출 주체가 Codemit 인 것은 확인됐다 | tax | 미구현 |
| 6 | 플랫폼 수수료·개최비의 부가세·세금계산서·현금영수증 처리가 정해지지 않았다 | tax | 미정 |
| 7 | 제출 소스가 AI 채점을 위해 OpenAI 로 나간다 — 국외 이전·위탁 고지 | personal-data | 고지 필요 |
| 8 | 발주자의 「탈락작 마스킹 없는 공개」 동의를 코드가 기록하지 않는다 | contracts-and-ip | 미구현 |
| 9 | 정당하게 CI 가 바뀐 사람(주민등록번호 변경, 계정 탈취 복구)을 위한 사람의 판단 경로가 없다 | personal-data | 미구현 |
| 10 | 발신주의(발송 이력이 통지의 증거) 조항이 개인 Sponsor 에게 불공정 약관으로 다퉈질 여지 | contracts-and-ip | 확인 필요 |
| 11 | 강사가 연결한 앱으로 참여자 제출물이 바깥 운영사에 가는 것 — 위탁이 아니라고 보고 방침 4절에 적었다. 제3자 제공(제17조)·국외 이전(제28조의8) 근거가 따로 필요한지 | personal-data | 변호사 확인 필요 |
| 12 | 연결된 앱 조항을 출시 전(테스터뿐)이라 공지 기간 없이 2026-10-03 시행했다 — 제10조 ⑤ 면책이 약관규제법 제7조를 넘지 않는지 | contracts-and-ip | 확인 필요 |
| 13 | 학생이 낸 Packet Tracer `.pkt` 를 역공학 공개 코드(MIT)로 해독해 채점한다 — Cisco 약관이 이를 금하는지. 사용자 판단으로 약관 면책 조항을 두고 켠다(#498, staging 먼저) | contracts-and-ip | 위험 감수 — 변호사 확인 필요 |
