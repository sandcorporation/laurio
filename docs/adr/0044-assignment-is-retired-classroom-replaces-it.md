# 과제를 접는다 — 그 쓰임은 클래스가 맡는다 (ADR-0028·0029·0033 대체, ADR-0034 일부 개정)

Status: Accepted (2026-09-13 결정)

## 문제

Assignment(ADR-0028)와 Class(ADR-0037)는 **같은 일**을 한다 — 상금도 결제도
본인확인도 없이 초대 하나로 사람을 모아 체크리스트로 AI 채점을 한다. 겹침은
말에서 먼저 드러났다: `CONTEXT.md`의 **문제(Problem)** 항목은 "과제"라는 말을
쓰지 말라고 적어 두고 있었고, **Class** 항목은 Assignment와 무엇이 다른지를
한 문단에 걸쳐 변명하고 있었다.

그리고 **클래스가 더 낫다.** 마감이 없어 기수를 늘려 쓸 수 있고, 참여자 명단이
있어 누가 막혔는지 보이고, 문제를 여럿 담고, 지난 기수를 복사하거나 템플릿으로
나눌 수 있다. 결정적으로 **채점 비용의 주인이 강사 자신**이라(강사의 키와 예산,
ADR-0043) Operator가 개최 자격을 일일이 심사할 이유가 없다 — Assignment에
`AssignmentPermission`(ADR-0029)이라는 사람 문이 필요했던 이유 전체가 클래스
에서는 사라진다: 결제가 서 있던 자리를 사람의 승인이 대신할 필요 자체가 없다,
비용이 이미 강사 자신의 것이기 때문이다.

그 결과 출제자는 같은 목적에 두 제품 중 무엇을 골라야 하는지 알 수 없었고,
Operator는 아무도 쓰지 않을 자격을 심사했으며, 공모전 배관 곳곳에 "이건
Assignment인가"라는 분기가 스며 공모전 하나를 고치려는 사람이 Assignment까지
이해해야 했다.

## 결정

**Assignment를 접는다.** 출제자가 하던 일은 강사가, InviteCode가 하던 일은
가입 링크가, 제출자가 하던 일은 참여자가 맡는다. 화면·API에서 Assignment가
사라진다(#359 공개 앱, #360 운영자 앱, #361 백엔드 라우터·서비스·스캔).

**모델·스키마는 이 단계에서 건드리지 않는다.** `Contest.kind`·
`ASSIGNMENT_OPEN`/`ASSIGNMENT_CLOSED`·`InviteCode`·`SponsorProfile.
can_open_assignments`는 이 저장소의 관용구대로(CLAUDE.md "호출부를 먼저,
스키마를 나중에") 다음 배포에서 뽑는다. 공유 배관(제출 API·스토리지 가시성·
시연 영상 보존·결제 게이트)의 `is_assignment` 분기도 필드가 남아 있는 동안은
함께 남는다 — 지금 지우면 그 필드를 참조하는 코드가 깨진다.

**`assignment-close` 스캔은 예외적으로 지금 등록부에서 뺀다.** Assignment
개설 API가 걷혀 `DRAFT -> ASSIGNMENT_OPEN`으로 옮길 방법 자체가 없으므로, 그
스캔을 계속 등록해 두면 영원히 빈 후보만 도는 스캔이 된다. 간선 선언
(`contests.transitions.CONTEST_TRANSITIONS["assignment-close"]`)은 그래프
자체의 self-consistency(도달 가능성·갇힌 상태 없음)를 위해 남긴다 — 두
상태값이 아직 모델에 있는 한 그 간선도 선언에 남아야 그래프가 스스로
모순이 되지 않는다(`contests.transitions.
SCAN_EDGES_INTENTIONALLY_UNREGISTERED`가 이 예외를 문서화한다).

**개최 자격의 변경 이력(`AssignmentPermissionChange`)과 출제자의 소스 열람
기록(`AssignmentSourceReading`)은 다음 모델 정리에서 함께 지운다.** 둘 다
감사 목적으로 세운 append-only 기록이지만, 가리킬 대상(Assignment 개설·소스
펼치기 API)이 이미 사라졌다 — 감사 기록은 그것이 감사하는 행위가 존재할 때만
의미가 있다. 백업 없이 지우는 결정임을 알고 진행한다(부모 스펙 #358의 사용자
결정).

**글로서리는 지우지 않고 접힌 것으로 표시한다.** `CONTEXT.md`의 **Assignment**·
**InviteCode**·**AssignmentPermission** 세 항목은 지금 백엔드 모델에 아직
남아 있는 개념을 설명하고, 나중에 이 저장소를 읽는 사람이 "왜 있었고 왜
없어졌는지"를 알아야 한다 — 지우면 그 설명이 사라진다.

## 무효가 되는 결정들

- **ADR-0028**(Contest는 상금 없는 Assignment도 담는다) — Superseded. Contest가
  둘째 종류를 나른다는 결정 자체가 무효다.
- **ADR-0029**(Assignment는 본인확인을 요구하지 않는다) — Superseded. 본인확인
  없는 개최·제출 경로 자체가 없어졌다.
- **ADR-0033**(Contest.kind는 일급 필드다 — ADR-0028 개정) — Superseded.
  `kind`가 "이 Contest가 Assignment인가"를 구조로 답하게 한 결정인데, 그
  질문 자체가 곧 뜻을 잃는다(모델 정리 뒤에는 `kind`도 함께 사라진다).
- **ADR-0034**(Contest 전이 그래프는 한 곳에 선언되고 정적으로 막힌다) —
  **Amended, 부분적으로만.** 이 ADR이 정한 원칙(전이는 `contests.transitions`
  한 곳에 선언되고 그 밖에서 `Contest.status`를 쓰면 정적으로 막힌다)은 공모전
  전이(`contest-close`·`contest-judging-end`·`award`·`publish-on-payment`)에
  대해 **여전히 유효하다**. 다만 그 여섯 간선 중 `open-assignment`·
  `assignment-close` 둘은 이 ADR로 실제로 죽었다 — 전자를 부르던 유일한 문
  (`open_assignment` 엔드포인트)이 없어졌고, 후자는 스캔 등록부에서 빠졌다.
  두 간선의 선언은 그래프 self-consistency를 위해 여전히 파일에 남지만, 그
  존재 이유(Assignment 상태 전이)는 이 ADR로 무효가 됐다.

## Consequences

- 문서(`docs/features/*.md`)에서 Assignment 서술을 걷는다 — 백엔드·공개 앱·
  운영자 앱 셋 다.
- `docs/legal/contracts-and-ip.md`의 Assignment 관련 약관 항목(2·16·17·18)은
  가리키는 기능이 사라졌지만, 그 문서 자체는 "그때 무엇을 정했는가"의 지도라
  이번 커밋에서 고치지 않는다 — 기능이 완전히 걷힌 뒤(모델 정리) 그 표를
  다시 본다.
- staging은 비우고(#358 결정) 데모를 다시 심지 않는다 — 이 ADR의 범위 밖,
  배포 작업이다.
- 이 결정이 다시 열리는 것은 클래스가 실제로 마감·결제·본인확인을 필요로 하는
  용도로 확장될 때다 — 그때는 "Assignment와 Class가 같은 일을 한다"는 이
  ADR의 전제 자체가 바뀐다.
