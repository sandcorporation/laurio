# 기능 명세 — 지금 이 서비스가 무엇을 하는가

**이 디렉터리는 현재형이다.** `CLAUDE.md`·`CONTEXT.md` 와 같은 시제이고, ADR·이슈·스펙과는
다르다. 저 셋은 「그때의 판단」이고 여기는 「지금의 동작」이다.

| | 무엇을 말하는가 |
| --- | --- |
| [`backend.md`](backend.md) | 서버가 무엇을 받고, 무엇을 스스로 하고, 무엇을 기록하는가 |
| [`frontend.md`](frontend.md) | 공개 앱의 화면과 그 화면이 사람에게 시키는 일 |
| [`operator.md`](operator.md) | 운영자 앱의 화면과 사람이 판단하는 행위 |
| [`classroom.md`](classroom.md) | 강의실 앱의 화면과 그 화면이 사람에게 시키는 일 |

**세 앱 문서는 화면 하나에 절 하나다.** 그 화면이 무엇을 보여주고, 사람이 무엇을 할 수
있고, 무엇을 요구하며, **무엇을 일부러 하지 않는지**를 적는다. 마지막 것이 가장 자주
잊히는데, 「없는 이유」를 안 적으면 다음 사람이 그것을 결함으로 보고 만들어 넣는다.

**여기에 없는 것은 일부러 없다.** 왜 그렇게 정했는지는 `docs/adr/`, 도메인 낱말의 뜻은
`CONTEXT.md`, 저장소를 어떻게 굴리는지는 `CLAUDE.md` 다. 같은 사실을 두 곳에 적으면
언젠가 갈라지고, 갈라진 쪽을 읽은 사람이 틀린다.

**요청·응답 필드는 적지 않는다.** OpenAPI 스키마가 이미 그것이고, 두 벌이 되면 반드시
갈라진다. 이 문서가 답하는 것은 「무엇을 할 수 있는가」이지 「어떤 JSON 이 오가는가」가
아니다.

## 갱신 규율 — 이 문서가 낡으면 대신 참을 말해 줄 문서가 없다

**티켓을 닫을 때, 그 티켓이 이 문서의 어떤 문장을 거짓으로 만들었는지 확인하고 같은
커밋에서 고친다.** `CLAUDE.md`·`CONTEXT.md` 에 이미 걸려 있는 의무와 같은 것이고, 이제
셋이다.

무엇이 바뀌면 어디를 고쳐야 하는지:

| 바뀐 것 | 고칠 곳 |
| --- | --- |
| API 엔드포인트가 늘거나 줄었다 | `backend.md` 의 해당 표면 |
| 스캔이 늘거나 줄었다, 주기가 바뀌었다 | `backend.md` 「스스로 도는 일」 |
| 화면이 생기거나 사라졌다 | `frontend.md` / `operator.md` / `classroom.md` — 그 화면의 절을 더하거나 지운다 |
| 화면이 하는 일이 바뀌었다 | 같은 세 문서의 **그 화면 절** |
| 상태 값·전이 조건이 바뀌었다 | `backend.md` 「Contest 의 상태」의 표 **와** mermaid 다이어그램(`cd backend && uv run python manage.py print_contest_transition_diagram` 으로 재생성 — `tests/test_contest_transition_graph.py` 가 갈리면 CI 에서 잡는다) |
| 정책 기본값이 바뀌었다 | `backend.md` 「정책 값」 |
| 어댑터가 늘거나 바인딩이 바뀌었다 | `backend.md` 「바깥 세계」 |
| 알림 종류가 늘었다 | `backend.md` 「알림」 |

**수치와 목록이 가장 잘 썩는다.** 엔드포인트 개수, 스캔 개수, 정책 기본값, 화면 목록 —
그것을 바꾸는 티켓이면 그 표를 같이 고친다.

**세는 것은 손으로 하지 않는다.** 아래 명령이 지금의 사실을 그대로 뱉는다:

```bash
# 엔드포인트 전부 (스택 없이 돈다)
cd backend && uv run python manage.py export_openapi_schema | \
  python3 -c "import json,sys; s=json.load(sys.stdin); print(sum(len([m for m in o if m in ('get','post','put','patch','delete')]) for o in s['paths'].values()))"

# 스캔 등록부
cd backend && CODEMIT_DB_PORT=55432 uv run python manage.py shell -c \
  "from core.scans import SCAN_REGISTRY; print(len(SCAN_REGISTRY)); print(*SCAN_REGISTRY, sep='\n')"

# 화면
find frontend/app operator/app classroom/app -name page.tsx | sed 's|/page.tsx||'

# Contest 전이 그래프 다이어그램 (docs/features/backend.md 「Contest 의 상태」 절)
cd backend && uv run python manage.py print_contest_transition_diagram
```

## 마지막 실측

**2026-09-21**, 공개된 공모전을 마감 전까지 고칠 수 있게 한 #473 을 합친 시점 기준.
아래 수치는 위 명령으로 **합친 뒤에** 다시 뽑았다. 이번에도 체인들에게 이 블록을 건드리지
말라고 하고 통합 지점에서 한 번만 쟀다 — 그 전 통합에서 두 체인이 각자 자기 작업 트리에서
잰 값(오퍼레이션 174·경로 150 과 174·151)이 어느 쪽도 합집합의 값이 아니었다.
병렬로 도는 체인이 있는 한 이 블록은 **통합 지점에서만** 참이다.

- 공개·운영자·내부·강의실 API 오퍼레이션 **179개** (경로 155개)
- 등록된 스캔 **27개** (조회수 옮기기 10분·검색 전체 재색인 하루·DB 연결 사용률을 빼면 전부 60초 주기)
- 공개 앱 화면 **23개**, 운영자 앱 화면 **13개**, 강의실 앱 화면 **18개**
- ADR **50개**
- 백엔드 테스트 **2482건** 통과·1건 skip
