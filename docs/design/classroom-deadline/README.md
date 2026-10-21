# 강의실 「권장 기한·마감」 시안 (2026-10-21)

**이것은 「그때의 판단」이다** — `../classroom-v2/README.md` 와 같은 시제다. 지금 서비스가 무엇을
하는지는 `docs/features/classroom.md`(화면)·`docs/features/backend.md`(API)가 말하고, 결정의 근거는
ADR-0063 이다. 이 시안과 실제 화면이 어긋나면 실제 화면이 맞고 이 파일이 낡은 것이다.

v2(`../classroom-v2`)의 조각·데이터를 그대로 쓰고, 기한이 닿는 화면만 다시 그렸다 — 문제 편집의
「기한」 카드, 클래스 상세 문제 표의 「기한」 열, 참여자 격자의 「늦음」 점, 참여자 문제 목록의 기한과
「늦음」, 제출 화면의 마감 전·마감 지남. 토큰·서체·모서리·괘선은 v2 와 같다.

## 무엇이 들어 있나

`review.html` 한 장이 전부를 담는다 — 합의한 규칙, 화면 일곱 장, 끝에 「코드가 따라가려면」. 검토는
claude.ai 에 올린 사본으로 한다(https://claude.ai/artifact/Fd3GXsPwVZwNfCsCqKHCqk).

| 파일 | 화면 |
| --- | --- |
| `ProblemEdit.dc.html` · `ProblemEditEmpty.dc.html` | 문제 편집 — 「기한」 카드, 기한 있음·없음 |
| `Class.dc.html` | 클래스 상세 · 문제 표 — 「기한」 열 |
| `Roster.dc.html` | 클래스 상세 · 참여자 격자 — 머리에 마감, 칸에 「늦음」 점 |
| `Mine.dc.html` | 참여자 · 문제 목록 — 줄마다 기한, 「늦음」 |
| `Submit.dc.html` · `SubmitClosed.dc.html` | 참여자 · 제출 — 마감 전 · 마감 지남 |

## 구현 티켓

- #769 — 백엔드·MCP·문서·ADR(`recommended_due_at`·`due_at`, `deadline_passed`, `late`). 이 디렉터리를
  저장소에 실은 PR 이다.
- #770 — 강의실 앱 화면(위 일곱 장).

## 다시 그리려면

```bash
cd docs/design/classroom-deadline && python3 gen.py && python3 build_review.py
```

`gen.py` 가 `../classroom-v2/_lib.py` 의 조각으로 일곱 장을, `build_review.py` 가 검토 페이지를 쓴다.
