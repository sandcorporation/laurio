# Laurio

발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 앱·서비스를 만들어 제출하고,
기한 내에 선정된 하나에게 상금이 지급되는 공개 공모전 플랫폼.

## Language

### 공모전

**Contest**:
발주자가 상금을 걸고 요구사항을 공개해 개발자들이 경쟁하는 하나의 이벤트. 요구사항·체크리스트·상금·기한을 모두 담는 최소 단위이며, 유찰 후 다시 열 때는 복제된 새 Contest가 원본을 참조한다.
_Avoid_: 의뢰, Request, Project, Job, Brief, Round

**Category**:
Contest가 속한 산업·장르(엔터테인먼트, 교육, 게임, 라이프스타일 등). DeliverableType과는 다른 축이다.
_Avoid_: 분야, Genre, Industry

**DeliverableType**:
만들어야 할 산출물의 종류(랜딩·원페이지, 관리자 페이지, 웹 서비스, 모바일 앱, 데스크톱 프로그램). 각각 최소 제안 상금을 가지며 복수 선택 시 합산된다.
_Avoid_: 요구형태를 Category로 부르는 것, Platform, ProjectType

**Requirement**:
Contest의 심사 체크리스트를 이루는 검증 가능한 한 항목. 필수 또는 선택 등급을 가진다. 개발자의 자가 체크, 발주자의 심사, AI 채점이 모두 이 항목을 기준으로 삼는다.
_Avoid_: 체크리스트 항목, Criterion, Spec, AcceptanceCriteria

### 당사자

**Sponsor**:
Contest를 개최하고 Prize를 예치하며 Award 권한을 갖는 당사자.
_Avoid_: 의뢰자, 발주처, Client, Buyer, Orderer, Requester

**Developer**:
Contest에 Submission을 내는 당사자. 한 사람이 어떤 Contest에서는 Sponsor이고 다른 Contest에서는 Developer일 수 있다.
_Avoid_: 참가자, Entrant, Contestant, Contractor, Freelancer

**Operator**:
Laurio를 운영하며 Appeal에 Ruling을 내리는 당사자. Sponsor·Developer와 서로소다 — 소셜 계정을 가진 계정은 Operator가 될 수 없고, Operator는 소셜 계정을 붙일 수 없다. 이 구분이 「돈을 움직인 사람이 누구인가」를 애매하지 않게 만든다.
_Avoid_: 관리자, 스태프, Admin, Staff, Moderator

**PlatformPolicy**:
플랫폼이 정한 요율과 기간 — 수수료, 원천징수, 개최비, 연장비, 심사기간, 배분 대기, 배분 컷라인. 환경이 아니라 사업이 정하는 값이라 staging 과 production 에서 같아야 하고, 바뀌면 누가 언제 바꿨는지가 남는다(ADR-0023). 값을 쓴 Payout·Distribution 은 그때의 요율을 자기 안에 기억한다.
_Avoid_: 설정, config, 환경변수(그 셋은 환경마다 달라도 되는 것을 가리킨다)

**PolicyChange**:
PlatformPolicy 를 바꾼 사건 하나 — 누가, 언제, 무엇을 무엇으로. 요율을 바꾸는 것은 돈에 관한 판단이므로 심판·열람과 같이 신원이 붙는다(ADR-0019, ADR-0023).
_Avoid_: 설정 변경 로그, 히스토리

**SourceReading**:
Operator가 이의를 심판하며 제출 소스를 펼쳐 본 사건. 기본은 접혀 있고 명시적으로 펼 때만 남는다 — 그래야 기록이 잡음이 아니라 신호가 된다. 소스를 감춘다는 약속이 운영자 앞에서만 조용히 사라지지 않게 하는 장치다.
_Avoid_: 조회 로그, 접근 기록, 감사 로그(감사 대상 전체를 가리키는 넓은 말), Access log

### 제출과 선정

**Submission**:
한 Developer가 한 Contest에 낸 결과물 일체(시연 영상, 데모, 테스트 계정, Requirement 자가 응답).
_Avoid_: 제출물, 출품작, Entry, Work, Proposal

**Score**:
마감 직후 한 번만 산출되어 불변으로 고정되는, Submission의 필수 Requirement 달성률. Distribution 대상 판정의 유일한 근거다.
_Avoid_: 평가, 점수, Grade, Rating, Evaluation

**Appeal**:
Developer가 자신의 Score에 이의를 제기하는 것. Score는 불변이므로 재채점 요구가 아니라 사람의 판단을 구하는 것이다.
_Avoid_: 이의신청, 재심, 항소, Dispute, Complaint, Rescore

**Ruling**:
Operator가 Appeal을 인용하거나 기각하는 행위. 인용해도 Score는 그대로 두고 원장에 정정 분개를 새로 더한다. Ruling에는 그것을 내린 Operator가 언제나 함께 남는다 — 존재하는데 신원이 없는 Ruling은 있을 수 없다.
_Avoid_: 판정, 처리, 결정, Decision, Resolution, Judgment

**Award**:
Sponsor가 하나의 Submission을 우승작으로 확정하는 행위. 이 시점에 지식재산권이 Sponsor에게 이전된다.
_Avoid_: 낙찰, 채택, 당선, Selection, Win, Pick

**Handover**:
Award 이후 Developer가 소스코드와 빌드 자산을 Sponsor에게 넘기는 행위. 실제 스토어 배포는 여기에 포함되지 않는다.
_Avoid_: 납품, 전달, 이관, Delivery, Transfer

### 돈

**Prize**:
Sponsor가 Contest 개최 시 예치하는 금액. Payout 또는 환불로만 빠져나간다.
_Avoid_: 보상, 대금, Reward, Payment, Fee

**Escrow**:
결제된 Prize가 Payout 또는 환불로 빠져나가기 전까지 머무는 상태. 참가자가 한 명이라도 있으면 Sponsor에게 되돌아가지 않는다.
_Avoid_: 예치금을 Deposit으로 부르는 것, Holding

**Payout**:
Prize가 원장을 거쳐 Developer에게 실제로 나가는 것. 플랫폼 수수료와 원천징수가 공제된 뒤의 실지급을 포함한 전 과정을 가리킨다.
_Avoid_: 정산, 이체, 송금, Settlement, Transfer, Disbursement

**Seller**:
Developer가 Payout을 받기 위해 지급대행사(토스)에 등록되는 수취인 신원. Payout이 확정된 뒤에만 등록이 시작된다 — Verification이 가입이 아니라 행위 시점으로 미뤄진 것과 같은 원칙이다. 등록으로 받는 sellerId는 Developer에 남아 두 번째 Payout부터는 재등록하지 않는다. 본인인증을 마치면 부분 승인 상태로 주간 한도 안에서 지급받고, 한도를 넘으면 심사 대기가 된다 — 둘 다 실패가 아니다.
_Avoid_: 셀러(한글 음역을 개념 이름처럼 쓰는 것), 정산 계좌, Merchant, Payee

**Distribution**:
Sponsor가 기한 내 Award하지 않아, Score 컷라인을 통과한 Submission들에게 Prize를 1/N로 나누는 것.
_Avoid_: 유찰 배분, 자동 지급, Refund, Split

### 신원과 통지

**Authentication**:
어떤 요청이 어느 계정의 것인지 확인하는 것. 소셜 로그인만으로 이루어지며 실명과는 무관하다.
_Avoid_: 인증(Verification과 뭉뚱그리는 것), 로그인 상태를 본인확인으로 부르는 것

**Verification**:
휴대폰 본인확인으로 실명·생년월일·CI를 확보한 상태. Submission 제출과 Contest 개최를 여는 관문이며, 가입과 열람에는 요구되지 않는다. **한 계정의 신원은 한 번 정해지면 다른 사람의 것으로 바뀌지 않는다** — 이미 CI 가 있는 계정에 다른 CI 로 본인확인이 들어오면 거부한다. 이 불변식이 없으면 성인으로 확인받아 개최한 사람이 재확인 한 번으로 미성년이 되어, 그 Contest 의 자전거래 차단이 조용히 꺼진다.
_Avoid_: 인증(Authentication과 뭉뚱그리는 것), 실명인증, KYC(토스 셀러 심사를 가리키는 별개 용어)

**Withdrawal**:
Developer 나 Sponsor 가 자기 신원을 파기하고 계정을 닫는 것. **진행 중인 거래가 하나라도 있으면 할 수 없다** — 신원이 사라지면 그 거래가 주인을 잃기 때문이다. CI·DI·전화번호는 즉시 사라지고, 공개 프로필은 닫히며 이름과 소개도 함께 지워진다. 실명과 생년월일은 **거래가 있었던 사람에 한해** RetainedIdentity 로 옮겨 남는다. Verification 은 지워지지 않고 그 사실만 남긴 상태로 내려간다 — 미성년 판정이 CI/DI 를 비우면서 행을 남기는 것과 같은 모양이라, 「신원이 없는 계정」과 「한 번도 확인하지 않은 계정」이 구별된다. **거래 기록은 남는다**: Contest·Submission·원장·Payout 은 계약 상대방의 기록이자 법이 보존을 요구하는 것이라 한 사람의 탈퇴로 사라지지 않는다. 남은 참가작은 이름 없이 보인다.
_Avoid_: 회원탈퇴(계정 삭제로 읽힌다), 계정 삭제, 파기(무엇을 파기하는지가 빠진다), 출금(Payout 과 뭉뚱그리는 것)

**RetainedIdentity**:
탈퇴했지만 거래가 있었던 사람의 실명과 생년월일을, 그 거래를 증명하기 위해 법이 요구하는 기간 동안 따로 보관한 것. **살아 있는 신원과 같은 자리에 두지 않는다** — 섞여 있으면 「지운 것」과 「보존해야 해서 남긴 것」이 구별되지 않고, 분리 저장은 법이 파기 의무와 보존 의무의 충돌에 대해 정해 둔 답이기도 하다. CI·DI·전화번호는 여기 들어오지 않는다 — 그것들은 계약의 기록이 아니라 동일인 판별과 통지를 위한 것이라 목적이 탈퇴로 끝난다.
_Avoid_: 보관 신원, 아카이브, 백업(지워야 할 것을 못 지운 상태로 읽힌다)

**IdentityReading**:
Operator 가 RetainedIdentity 를 펼쳐 본 사건. 기본은 접혀 있고 명시적으로 펼 때만 남는다 — SourceReading 과 같은 이유다. 지운 줄 알았던 이름이 운영자 앞에서만 조용히 열려 있지 않게 하는 장치다.
_Avoid_: 조회 로그, 열람 이력

**Notification**:
Laurio가 당사자에게 보내는 통지. 거래성과 광고성으로 나뉘며 광고성만 사전 동의를 요구한다. 도달 여부와 무관하게 발송 이력이 통지의 증거가 된다.
_Avoid_: 알림톡(특정 채널명을 통지 전체의 이름으로 쓰는 것), 메시지, 푸시

**Evidence**:
각 Requirement 자가 응답을 뒷받침하도록 Developer가 지정한 근거. 시연 영상의 타임스탬프, 스크린샷, 데모 내 경로, 소스 위치 중 하나다. 증거가 없는 주장은 Score 산출에서 미달로 처리된다.
_Avoid_: 근거자료, 첨부, Proof, Attachment
