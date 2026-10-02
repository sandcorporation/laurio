# 마이그레이션은 배포가 먼저 돌리고, 옛 코드가 견디게 쓴다 — 못 견디는 것만 표식을 달고 내리고 올린다

Status: Accepted (2026-10-03 결정)

backend·events 는 겹쳐 바꾼다(#485). 새 컨테이너가 `/api/health` 에 답한 뒤에야 옛 것을 내린다.
그런데 새 마이그레이션이 든 배포는 예외였다. 옛 코드가 새 스키마 위에서 돌지 않게 넷을 내리고
올렸다. 그 창이 공개 앱의 재시도 예산(약 15.8초)보다 길었다. 2026-10-02 prod 에서
`classroom/0014_connected_apps` 를 배포하는 동안 `backend` 라는 이름이 16초 넘게 풀리지 않았고,
`/contests` 가 500 을 냈다(GlitchTip 75·83, #526·#527). 같은 모양의 오류가 그 전에도 세 번 났다.

**마이그레이션이 든 배포도 겹쳐 바꾼다.** 순서는 이렇다.

1. 새 이미지를 받는다.
2. `deploy.sh` 가 새 이미지의 일회성 컨테이너(`compose run --rm backend`)에서 `migrate` 를 한 번
   돌린다. 그동안 옛 컨테이너는 계속 요청을 받는다.
3. migrate 가 성공해야 `rolling_replace` 로 backend·events 를 겹쳐 바꾼다. 실패하면 아무것도
   내리지 않고 배포를 실패로 끝낸다.

배포 compose 의 backend 기동 command 에서는 migrate 를 뺐다. 이제 migrate 는 일회성 컨테이너 한
곳에서만 돈다. 그래서 겹친 두 backend 가 동시에 migrate 를 돌릴 일이 없다. 일회성 컨테이너는
backend 와 같은 환경을 받으므로 연결 풀러(트랜잭션 모드)를 거친다. 예전 기동 command 도 같은 경로로
migrate 를 돌렸다. Django 의 migrate 는 세션 상태에 기대지 않는다.

## 그 대가 — 마이그레이션은 뒤로 호환되어야 한다

2와 3 사이, 그리고 겹친 몇 초 동안 **옛 코드가 새 스키마 위에서 돈다.** 그래서 스키마 변경은
expand → contract 두 배포로 나눈다.

- **한 배포에 해도 되는 것**: 테이블 추가, `null=True` 나 `db_default` 가 있는 컬럼 추가, 인덱스·
  제약 추가, 데이터만 바꾸는 RunPython.
- **다음 배포로 미루는 것**: 컬럼·테이블 삭제, 이름 바꾸기, DB 기본값 없는 NOT NULL 컬럼 추가,
  기존 컬럼에 NOT NULL 걸기, 타입 바꾸기. 옛 코드가 그것을 읽거나 쓰기를 먼저 그만두게 한 배포를
  내보낸다. 그다음 배포에서 지우거나 조인다.

`backend/tests/test_migration_rolling_safety.py` 가 마이그레이션 파일을 AST 로 훑는다. 위험한 연산이
있는데 표식이 없으면 빨갛게 된다. 위험한 연산은 RemoveField·DeleteModel·RenameField·RenameModel·
AlterModelTable·RunSQL, `null=True`·`db_default` 가 없는 AddField, `null=True` 가 아닌 AlterField 다.
표식은 주석 한 줄이고, 이유가 비면 실패한다.

- `# ROLLING-DEPLOY-UNSAFE: <이유>` — 정말 호환되지 않는다. `deploy.sh plan` 이 배포 범위에서 이
  표식을 찾으면 예전처럼 물러선다. 넷을 **먼저 내리고**, migrate 를 돌린 뒤 올린다. 그동안
  backend 가 없다.
- `# ROLLING-DEPLOY-SAFE: <이유>` — 들여다봤고 옛 코드가 견딘다. choices 만 바뀐 AlterField나
  옛 코드가 이미 안 쓰는 컬럼을 지우는 contract 단계가 그렇다.

이 규칙 전에 쓰여 이미 적용된 파일은 시험의 `GRANDFATHERED` 가 넘긴다.

물러서는 배포는 셋이 남는다. 표식이 있을 때, 풀러를 바꿀 때(넷을 먼저 내린다), 겹칠 옛 컨테이너가
없을 때다. 직전 배포 표식이 없어 범위를 모를 때도 물러선다.

## 고려한 대안

- **공개 앱과 BFF 의 재시도 예산을 실측한 틈보다 길게 늘린다(45~60초).** 배포 중 요청이 그만큼
  매달린다. Next 워커와 소켓이 쌓이고, 사람은 긴 로딩을 본다. 틈이 다시 길어지면 같은 오류가
  돌아온다. 재시도(`a458d03`)를 이미 더했지만 틈이 그 예산을 넘었다(GlitchTip 64·74·75).
- **틈을 받아들이고 공개 SSR 이 「잠시 후 다시」 화면을 낸다.** 진짜 장애도 같은 화면 뒤로 숨는다.
  오류 수집이 줄면 장애를 늦게 안다.
- **기동 command 의 migrate 를 남겨 두고 no-op 이 되게 한다.** 일회성 컨테이너가 먼저 돌렸으니 새
  backend 의 migrate 는 할 일이 없다. 다만 내리고 올리는 배포에서 다시 옛 worker·beat·events 를
  새 스키마 위에 남기는 순서가 된다. migrate 를 돌리는 곳이 둘이면 누가 언제 스키마를 바꾸는지도
  흐려진다.

## 결과

- 마이그레이션을 쓰는 사람이 한 가지를 더 생각한다. 「이 변경을 옛 코드가 견디는가」다. 견디지
  못하면 두 배포로 나누거나 표식을 달고 몇 초~십수 초의 창을 받아들인다.
- 배포 compose 로 손수 처음 띄우는 DB 는 `docker compose run --rm backend python manage.py migrate`
  를 먼저 쳐야 한다. 기동 command 는 더 이상 스키마를 만들지 않는다. dev·CI compose 는 그대로
  기동 때 migrate 한다.
- migrate 가 겹쳐 바꾸기 길에서 실패하면 그 앞의 마이그레이션은 이미 적용됐을 수 있다. 뒤로
  호환되므로 옛 코드는 그대로 돈다.
