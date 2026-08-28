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

### 제출과 선정

**Submission**:
한 Developer가 한 Contest에 낸 결과물 일체(시연 영상, 데모, 테스트 계정, Requirement 자가 응답).
_Avoid_: 제출물, 출품작, Entry, Work, Proposal

**Score**:
마감 직후 한 번만 산출되어 불변으로 고정되는, Submission의 필수 Requirement 달성률. Distribution 대상 판정의 유일한 근거다.
_Avoid_: 평가, 점수, Grade, Rating, Evaluation

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

**Distribution**:
Sponsor가 기한 내 Award하지 않아, Score 컷라인을 통과한 Submission들에게 Prize를 1/N로 나누는 것.
_Avoid_: 유찰 배분, 자동 지급, Refund, Split

### 신원과 통지

**Authentication**:
어떤 요청이 어느 계정의 것인지 확인하는 것. 소셜 로그인만으로 이루어지며 실명과는 무관하다.
_Avoid_: 인증(Verification과 뭉뚱그리는 것), 로그인 상태를 본인확인으로 부르는 것

**Verification**:
휴대폰 본인확인으로 실명·생년월일·CI를 확보한 상태. Submission 제출과 Contest 개최를 여는 관문이며, 가입과 열람에는 요구되지 않는다.
_Avoid_: 인증(Authentication과 뭉뚱그리는 것), 실명인증, KYC(토스 셀러 심사를 가리키는 별개 용어)

**Notification**:
Laurio가 당사자에게 보내는 통지. 거래성과 광고성으로 나뉘며 광고성만 사전 동의를 요구한다. 도달 여부와 무관하게 발송 이력이 통지의 증거가 된다.
_Avoid_: 알림톡(특정 채널명을 통지 전체의 이름으로 쓰는 것), 메시지, 푸시

**Evidence**:
각 Requirement 자가 응답을 뒷받침하도록 Developer가 지정한 근거. 시연 영상의 타임스탬프, 스크린샷, 데모 내 경로, 소스 위치 중 하나다. 증거가 없는 주장은 Score 산출에서 미달로 처리된다.
_Avoid_: 근거자료, 첨부, Proof, Attachment
