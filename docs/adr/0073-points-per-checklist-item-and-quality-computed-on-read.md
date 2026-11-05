# 배점 — 항목마다 1~10, 완성도는 읽을 때 지금 배점으로 계산한다

Status: Accepted (2026-11-05 결정)

ADR-0072(완성도)를 보충한다. 계산식·지문·기록 칸의 뜻이 바뀌고, 나머지(대상·재사용·큐·공개 범위)는 그대로다.

## 맥락 (스펙 #903, 티켓 #904)

대표·대장 grill(2026-11-05)이 정한 것(스펙 「고정」):

- 체크리스트 항목은 **등급**(필수·선택·**가산**)과 **숨은 항목**(켜고 끄는 성질)을 따로 가진다.
- **배점은 완성도에만 쓴다** — Score·통과·달성률·Distribution·Appeal 의 뜻과 계산은 그대로다.
- 항목 점수 = (0~5 ÷ 5) × 배점. 완성도는 항목 점수 합과 만점(배점 합, 가산 포함)으로 「37.4 / 45점」처럼 보인다.
- 배점은 정수 1~10, 기본값 필수 2·선택 1·가산 1, 기존 항목도 이 값으로 채운다. **언제든** 고치고, 고치면 AI 를
  다시 부르지 않고 곧바로 다시 계산한다.

이 ADR 은 그 가운데 첫 티켓(#904)이 정한 구현이다. 가산의 사람 점수(#905)·숨은 항목(#906)·약관(#907)은 뒤 티켓이다.

## 결정

### 기록에는 0~5 만 믿고, 합은 읽을 때 계산한다

`core.quality_review.quality_total(items, points)` 가 기록의 항목(0~5)을 **지금 체크리스트의 배점**으로 합한다 —
`raw` = 정수 Σ(0~5 × 배점), 표시 합 = raw ÷ 5, 만점 = Σ배점. 지금 체크리스트에 있는데 기록에 없는 항목(가산)은 0점이고
만점에는 든다. 기록에 있는데 지금 체크리스트에 없는 항목은 세지 않는다(클래스는 지문이 같은 기록만 「지금의 기록」이라
생기지 않고, 공모전은 마감 뒤 항목을 더하고 지울 수 없다).

- **등수**는 `raw`(정수)로 매긴다(`competition_ranks`). 반올림한 표시값으로 세우지 않는다 — ADR-0072 와 같은 이유.
- 응답(`quality_view`)은 `total`·`max_total`·`raw_total` 과 항목마다 `points`·`item_points` 를 싣는다. 클래스 참여자
  본인 응답(`MyQualityOut`)은 `total` 이 이미 「k등 / N명」의 N 이라 합을 `score_total` 로 싣는다.
- **기존 데이터의 순위는 그대로다.** 필수 2·선택 1 로 채우면 Σ(0~5 × 배점)이 옛 가중 점수 Σ(가중치 × 0~5)와 같다
  (`test_default_points_keep_the_old_weighted_score_so_ranks_do_not_move`, 클래스·공모전 회귀 시험).

### 저장 합계 칸은 남기고 「역사값」으로 둔다

`ClassroomQualityReview`·`SubmissionQualityReview` 의 `weighted_score`·`max_weighted_score`·`completeness` 는 **지우지
않는다.** 새 코드는 이 칸을 읽지 않고, 쓸 때의 배점으로 한 번 찍어 둔다(`historical_columns` — 뜻은 옛것과 같다: 정수
합, 5 × 만점, 0~100). 남긴 이유는 둘이다.

- **겹쳐 바꾸기**(ADR-0053): migrate 뒤 몇 초 동안 옛 코드가 같은 DB 를 읽고 이 칸으로 순위를 세운다. NOT NULL 칸이라
  새 코드가 비우면 옛 코드가 깨지고, 지우려면 다음 배포의 contract 가 필요하다.
- 기록은 append-only 다(ADR-0072) — 그때 무엇이 보였는지 남기는 값으로 해롭지 않다.

응답에 같은 이름의 칸(`completeness`·`weighted_score`·`max_weighted_score`)도 **지금 배점으로 다시 센 값**으로 남겼다 —
배포 중 옛 화면이 새 백엔드를 읽어도 숫자가 깨지지 않게 하는 호환 칸이다. 새 화면은 읽지 않는다.

### 체크리스트 지문 = AI 가 매기는 항목의 id·라벨

`checklist_fingerprint` 는 AI 대상 항목(**가산 제외**)의 (id, 라벨)만 해시한다. 배점·필수/선택은 AI 의 0~5 를 바꾸지 않으니
넣지 않는다 — 그래서 배점이나 필수/선택을 고쳐도 다시 채점하지 않는다. 같은 이유로 **완성도 프롬프트에서 등급
표기(「(필수)」)를 뺐다**(판정 프롬프트는 그대로다). 가산과 가산 아님 사이를 오가면 AI 대상 집합이 바뀌어 지문이
바뀐다.

지문 정의가 바뀌면 이미 쌓인 기록을 「지금의 기록」으로 찾지 못해 강사가 다시 돈을 내야 한다. 그래서
`classroom.0037` 이 기록마다 항목 스냅샷(id·라벨)으로 새 지문을 다시 센다(append-only 행이지만 `save()` 를 거치지 않는
update). 겹쳐 바꾸는 몇 초 동안 옛 코드는 옛 지문으로 찾다가 못 찾는다 — 그 사이 「완성도 채점」을 누르면 다시 매길
수 있다(그 창은 몇 초다). 공모전 기록(`SubmissionQualityReview`)은 제출당 하나라 지문으로 찾지 않아 다시 세지 않았다.

### 공모전 `Requirement`

- `Grade.BONUS = "bonus"`(가산) 값과 `points`(PositiveSmallInteger, `db_default=1`, DB CHECK 1~10)를 더했다.
  `contests.0012` 가 기존 행을 필수 2·선택 1 로 채운다. 만들 때 배점을 주지 않으면 `save()` 가 등급별 기본값을 넣는다
  (`bulk_create` 는 부르는 쪽이 넣는다).
- **배점 편집은 따로 된 엔드포인트** `PATCH /contests/{id}/requirements/{rid}/points` 로 했다. 수정 API 의 상태 제한을
  배점만 풀면 한 함수에 「마감 뒤 이 칸만」 분기가 생기고, ContestChange·알림을 남기는 길과 남기지 않는 길이 섞인다.
  따로 두면 문(소유자면 어느 상태든)·기록(남기지 않음)이 한눈에 보인다. 무료 공모전이면 들여온 공모전 문제가 따라가도록
  공유층에 알린다(`contest_source_changed`).
- 배점이 바뀌어도 Score·Distribution·Appeal 의 근거(채점 스냅샷)는 바뀌지 않는다 — 배점은 완성도에만 쓴다.

### 클래스 체크리스트 세 모델 — `required` → `grade`

`ChecklistItem`·`ProblemTemplateChecklistItem`·`ClassTemplateProblemChecklistItem` 이 같은 추상 모델
(`GradedChecklistFields`)에서 `grade`(required·optional·bonus)와 `points`(1~10)를 받는다. **진실은 `grade` 하나다.**

- `required` 는 칸이 아니라 **속성**이다 — 읽으면 `grade == "required"`, 쓰면 `grade` 를 정한다. 그래서
  `ChecklistItem(required=False)` 같은 옛 모양의 생성·시드·시험이 그대로 돈다. ORM 필터(`filter(required=True)`)는 칸이
  아니라 못 쓴다 — `grade` 로 바꿨다.
- 통과(`Problem.is_score_passed`)는 `grade == required` 만 센다. 선택·가산은 들어가지 않는다.
- **겹쳐 바꾸기**: `classroom.0037` 은 `grade`(`db_default="required"`)·`points`(`db_default=1`)를 더하고 옛 값에서
  채운 뒤(True → 필수·2, False → 선택·1), `required` 를 **상태에서만** 지운다. DB 칸은 남기고 DB 기본값(true)만 달아 새
  코드의 INSERT 가 그 칸을 빼먹어도 되게 했다(classroom.0029 와 같은 모양). 그 몇 초 동안 새 코드가 만든 선택 항목은
  옛 코드에게 필수로, 옛 코드가 만든 항목은 필수·배점 1 로 보인다 — 몇 초 창의 대가로 받아들였다. 실제 DROP 은 다음
  배포의 contract 마이그레이션 몫이다.
- **API**: 출력은 `grade`·`points` 를 더하고 `required` 는 계산값으로 남긴다. 입력은 `grade` 를 받고, `grade` 없이
  `required` 만 오면 지금처럼 읽는다(True → 필수, False → 선택). `points` 가 없으면 등급별 기본값. MCP 도 같은 모양으로
  출력에 `grade`·`points` 를, 입력에 `points` 를 싣는다(MCP 의 등급 입력은 지금처럼 `required`).
- 복사·게시·들여오기(문제 ↔ 문제 템플릿 ↔ 클래스 템플릿)와 공모전 동기화(`_apply_source`)가 `grade`·`points` 를 함께
  옮긴다. 들여온 공모전 문제는 공모전의 등급·배점을 그대로 따르고 강사는 고칠 수 없다(지금 규칙과 같다).

### 가산은 받을 자리만 만들고 아직 열지 않는다

모델·DB 는 가산 값을 받고, 완성도 계산은 가산을 「매기기 전 0점, 만점에는 든다」로 다룬다. AI 입력
(`requirement_inputs`·`checklist_inputs`)과 지문에서도 이미 가산을 거른다. 하지만 **API·MCP·화면 입력은 아직 필수·선택만
받는다**(가산은 422). 가산을 받으면 판정(Score 프롬프트·요건별 판정 표시)에서 빼는 일과 사람 점수가 함께 있어야
운영에 안전하다 — 그것은 #905 가 함께 연다.

## 고려한 대안

- **합계를 저장하고 배점을 고치면 다시 쓴다.** append-only 기록을 고쳐 써야 하거나 새 행을 쌓아야 하고, 배점이 바뀐 순간
  모든 기록이 어긋난다. 읽을 때 계산하면 기록은 0~5 만 믿으면 된다.
- **저장 합계 칸을 이번에 지운다.** 겹쳐 바꾸는 동안 옛 코드가 읽는 NOT NULL 칸이라 이 배포에서는 못 지운다.
- **`required` 와 `grade` 를 나란히 둔다.** 둘이 어긋나는 상태가 생긴다 — 스펙이 막았다.
- **지문에 배점을 넣는다.** 배점을 고칠 때마다 다시 채점해 돈이 든다 — 배점은 AI 의 0~5 를 바꾸지 않는다.
