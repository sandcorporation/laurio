# 데모 시드는 자기 표지가 붙은 행만 지운다 — append-only 우회는 표지로 범위를 고정하고, production 은 여전히 거부한다

Status: Accepted (2026-10-21 결정)

## 맥락 (#254)

`seed_demo_contests` 는 「멱등하다 — `[데모]` 접두어가 붙은 것만 지우고 다시 만든다」고
적어 두었다. 그 약속은 채점 스캔이 한 번 도는 순간 깨졌다: `Score.submission` 이 PROTECT 라
(#240) 데모 Contest 삭제가 `ProtectedError` 로 죽고, `Score` 는 append-only 라 지울 수 없으며,
그 가드를 우회하는 유일한 함수 `hard_delete_e2e_fixture_rows` 는 **배포 환경에서 스스로
거부한다**(#240 — 「지울 수 없다고 적혀 있었지만 캐스케이드가 그것을 우회했다」는 사고 뒤에
세운 구조적 방어). 즉 staging 에서는 재시드가 통째로 불가능했고, 실제로 staging 의 데모
제출 14건이 「플랫폼이 채점하지 못했다」 0% 로 굳은 채 남아 있었다(#253 이 원인을 고쳤지만
이미 만들어진 Score 는 그대로다).

쉬운 답 둘은 둘 다 틀렸다. **가드를 느슨하게 하는 것** — `hard_delete_e2e_fixture_rows` 의
배포 거부를 풀면 #240 이 막은 문이 다시 열린다; 그 함수는 아무 queryset 이나 받으므로 데모
행과 실데이터 행을 구별하지 못한다는 것이 애초의 문제였다. **멱등성을 포기하는 것** — 매번
새 Contest 를 쌓으면 홈과 목록이 데모로 넘친다.

세 번째 길 「지우지 않고 은퇴시킨다(숨긴다)」도 살폈다 — Contest 에는 숨김 상태가 없다
(`HomeStatusAxis.HIDDEN` 은 DRAFT·Assignment 가 홈 축에서 받는 값이지 전이 가능한 상태가
아니고, 상태 쓰기는 전이 레지스트리로만 한다, ADR-0034). 데모 시드 하나를 위해 공모전
생명주기에 상태를 더하는 것은 비용이 목적을 넘는다.

## 결정

- **삭제 기준은 제목 접두어가 아니라 표지다.** `Contest.is_demo_seed`(기본 False, `db_default`)
  를 두고, **쓰는 곳은 `seed_demo_contests` 하나뿐이다** — 어떤 API 스키마에도 없고 구조 시험
  (`tests/test_seed_demo_contests_reseed.py`)이 소스를 훑어 그 사실을 고정한다. 그래서
  「표지가 True 다 = 시드가 심었다」가 성립한다. 사람이 `[데모] ` 로 시작하는 실제 공모전을
  열어도 시드는 그것을 지우지 않는다.
- **append-only 우회는 표지로 범위를 고정한 함수 하나로만 한다.**
  `scoring.models.hard_delete_demo_seed_scores()` 는 **queryset 을 받지 않는다** — 삭제
  집합은 함수 안에서 `submission__contestsubmission__contest__is_demo_seed=True` 로 닫히고,
  호출부가 넓힐 길이 없다. 표지 없는 Score 는 제목·소유자가 무엇이든 그 집합에 들어오지 않는다.
- **staging 에서는 돈다, production 에서는 거부한다.** 데모 시드 자체가 production 을 거부하므로
  production 에서 이 함수가 불릴 정상 경로는 없지만, 함수 자신이 `IS_PRODUCTION_DEPLOYMENT`
  에서 `AppendOnlyError` 를 던진다 — #240 과 ADR-0033 의 교훈(독스트링은 뚫린다)을 따른다.
- **#240 은 한 줄도 느슨해지지 않는다.** `hard_delete_e2e_fixture_rows` 는 그대로 모든 배포
  환경에서 거부하고(`tests/test_ledger.py`), e2e 시드들은 그대로 그것을 쓴다.
- **지울 수 없으면 Django 예외가 아니라 의도된 거절이다.** 데모 Submission 을 PROTECT 로 잡는
  다른 행(배분 몫 `DistributionShare`, 이의 판독 `SourceReading` 등)이 있으면 시드는 **무엇이
  잡고 있는지를 말하며** `CommandError` 로 멈춘다 — 그런 행은 데모가 실물 돈·심판 경로에
  들어갔다는 뜻이라 시드가 조용히 치울 물건이 아니다. 「멱등하다」의 조건은 이것 하나다.

## 결과

- 채점이 돈 뒤에도, staging 설정에서도 재시드가 된다 — 보이는 데모 한 벌은 늘 같고, 옛 데모
  Score 는 사라지며, 새 데모 제출은 채점 스캔에 다시 잡힌다.
- 실데이터 `Score`·원장은 여전히 어떤 경로로도 하드 삭제되지 않는다 — 표지가 없기 때문이다.
  표지를 다른 곳에서 쓰기 시작하면 이 근거가 사라지므로 구조 시험이 그것을 막는다.
- 강의실 데모(`seed_demo_classroom`)는 이미 같은 결로 돌고 있었다 — 그 강사의 `[데모]` 클래스에
  달린 `ClassroomScore` 만 QuerySet 으로 먼저 걷는다. 이 ADR 은 공모전 쪽에 같은 답을 주되,
  범위를 이름 접두어가 아니라 시드만 쓰는 표지로 닫는다.
- 스토리지 오브젝트는 여전히 남는다(#253, ADR-0005 의 좁은 포트) — 이 ADR 의 범위 밖이다.
