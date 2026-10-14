# 강의실 화면 시안 v2 (2026-10-14)

**이것은 「그때의 판단」이다** — `../classroom/README.md` 와 같은 시제다. 지금 서비스가 무엇을
하는지는 `docs/features/classroom.md` 가 말한다. 이 시안과 실제 화면이 어긋나면 실제 화면이
맞고 이 파일이 낡은 것이다.

v1(2026-09-10)은 강의실 티켓을 쪼개기 **전에** 그렸다. 그 뒤 한 달 동안 공동 강사·채점 연결·
템플릿·숨김 문제·공모전 문제가 들어오면서 실제 화면은 v1 과 꽤 멀어졌고, 특히 클래스 상세는
매일 보는 문제 목록이 배너·카드 넷에 밀려 화면 아래로 내려갔다. v2 는 **지금 있는 기능을 다
담은 채로** 화면마다 「매일 쓰는 것이 첫 화면에 들어오게」 다시 짠 것이다. 토큰·서체·모서리·
괘선은 v1 과 같다.

## 무엇이 들어 있나

`review.html` 한 장이 전부를 담는다 — 다섯 원칙, 강사·참여자 흐름 지도, 화면 열두 장, 화면마다
「지금과 무엇이 다른가」, 그리고 끝에 「프론트만으로 되는 것 / 백엔드가 먼저 열어야 하는 것」.
검토는 claude.ai 에 올린 사본으로 한다(https://claude.ai/artifact/S3R97Ebc9ER68cNJ9kFLiV).

| 파일 | 화면 |
| --- | --- |
| `Home.dc.html` | 내 클래스 — 행마다 참여자·문제·달성률 막대 |
| `ClassEmpty.dc.html` | 클래스 상세 · 방금 연 클래스 — 「시작하기」 셋 |
| `Class.dc.html` | 클래스 상세 · 문제 탭 — 통계 바, 채점 카드, 최근 제출 |
| `Roster.dc.html` | 클래스 상세 · 참여자 탭 — 명단과 격자를 합친 것 |
| `Instructors.dc.html` | 클래스 상세 · 강사 탭 — 공동 강사·초대·소유권 |
| `Settings.dc.html` | 클래스 설정 — 목차, 연결 상태 줄, 사용량 |
| `ProblemEdit.dc.html` | 문제 편집 — 1200px 두 열 |
| `Submissions.dc.html` | 제출 현황 — 통계 바, 참여자별 최신 시도 |
| `JoinGuest.dc.html` · `JoinMember.dc.html` | 가입 링크 — 로그인 전·후 |
| `Mine.dc.html` | 참여자 · 문제 목록 — 진행 막대 |
| `Submit.dc.html` | 참여자 · 문제와 제출 — 두 열, 체크리스트와 판정 합침 |

## 구현 티켓

우산 #631 이 묶는다. 장마다 티켓이 하나씩이고, 티켓 본문이 이 디렉터리의 파일과 검토
페이지의 `#s-<이름>` 앵커를 가리킨다.

| 장 | 티켓 |
| --- | --- |
| (백엔드 집계 — 클래스 행 수치·최근 제출·격자 가입일) | #632 |
| 설정의 「사용량」(예산 제거) | #629 |
| `Class`·`ClassEmpty` | #633 |
| `Roster` | #634 |
| `Instructors` | #635 |
| `Settings` | #636 |
| `ProblemEdit` | #637 |
| `Submissions` | #638 |
| `Mine` | #639 |
| `Submit` | #640 |
| `JoinGuest`·`JoinMember`·`Home` | #641 |

## 다시 그리려면

```bash
cd docs/design/classroom-v2 && python3 gen.py && python3 build_review.py
```

`_lib.py` 가 조각(버튼·배지·막대·카드·표식), `gen.py` 가 열두 장, `build_review.py` 가 검토 페이지다.
