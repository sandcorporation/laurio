# -*- coding: utf-8 -*-
# 강의실 시안 v2 — 화면 열한 장. `python3 gen.py` 가 이 디렉터리에 HTML 을 다시 쓴다.
from _lib import *

SCREENS = {}

def screen(name, inner, h=960, w=1200):
    SCREENS[name] = (inner, h, w)

# ───────────────────────────── 공통 조각 ─────────────────────────────
CLASS_NAME = "프론트엔드 입문 3기"

def class_head(sub, status="live"):
    tag = badge("진행중", "ver") if status == "live" else badge("보관됨")
    return pagehead("내 클래스 › " + CLASS_NAME, CLASS_NAME, sub,
                    actions=f'{btn("클래스 설정", small=True)}',
                    extra=tag)

def class_stats(members="24", problems="8", rate="61%", rc=VER):
    return statbar([("참여자", members, None), ("문제", problems, None), ("평균 달성률", rate, rc)])

def join_strip(url="classroom.codemit.kr/join/fe3-8kq2mx"):
    return (f'<div style="border:1px solid {RULE};background:{SURFACE};display:flex;align-items:center;gap:16px;padding:10px 16px;">'
            f'<div style="font-size:11px;letter-spacing:0.06em;color:{DIM};white-space:nowrap;">가입 링크</div>'
            f'<div style="font-family:{MONO};font-size:13px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{url}</div>'
                        f'{btn("복사", small=True)}{btn("다시 뽑기", small=True, ghost=True)}</div>')

def class_tabs(active):
    return tabs(["문제", "참여자", "강사"], active)

def scoring_card(state="ok"):
    """오른쪽 「채점」 카드 — 지금 흩어진 배너 넷(키 없음·거부·크레딧·서버)이 이 카드의 상태 한 줄이 된다."""
    if state == "ok":
        head = f'{badge("연결됨", "ver")} <span style="font-size:12.5px;color:{MUTED};">OpenAI 키 · ••••7f2a</span>'
        rows = [("기본 모델", "gpt-5-mini"), ("채점", "412회")]
        budget = (f'<div style="display:flex;justify-content:space-between;font-size:12.5px;"><span style="color:{MUTED};">사용량</span>'
                  f'<span style="font-family:{MONO};">1.56M 토큰 · 약 9,400원</span></div>')
    else:
        head = badge("연결 없음", "att")
        rows = []
        budget = btn("채점 연결 넣기", primary=True, small=True)
    r = "".join(f'<div style="display:flex;justify-content:space-between;font-size:12.5px;"><span style="color:{MUTED};">{k}</span><span style="font-family:{MONO};">{v}</span></div>' for k, v in rows)
    return card(cardhead("채점", right=btn("설정", small=True, ghost=True)) +
                f'<div style="padding:14px 16px;display:flex;flex-direction:column;gap:12px;">'
                f'<div style="display:flex;align-items:center;gap:8px;">{head}</div>{r}{budget}</div>')

def recent_card():
    recent = [("서지우", "JavaScript 배열 다루기", "passed", "3분 전"),
              ("한도현", "Flexbox 로 카드 목록", "failed", "9분 전"),
              ("최민재", "CSS 선택자와 박스 모델", "scoring", "방금"),
              ("오세아", "JavaScript 배열 다루기", "failed", "18분 전")]
    items = ""
    for n, p, k, w in recent:
        label = {"passed": ("통과", VER), "failed": ("미통과", MUTED), "scoring": ("채점 중", DIM)}[k]
        items += (f'<div style="padding:10px 16px;border-top:1px solid {RULE};display:flex;gap:10px;align-items:center;">{mark(k)}'
                  f'<div style="flex:1;min-width:0;"><div style="font-size:13px;">{n} <span style="color:{DIM};">·</span> <span style="color:{MUTED};">{p}</span></div></div>'
                  f'<div style="text-align:right;white-space:nowrap;"><span style="font-size:12px;color:{label[1]};">{label[0]}</span>'
                  f'<div style="font-size:11px;color:{FAINT};">{w}</div></div></div>')
    return card(cardhead("최근 제출") + items)

# ───────────────────────────── 1. 내 클래스 ─────────────────────────────
LIVE = [("프론트엔드 입문 3기", 24, 8, 61, "3분 전", None),
        ("파이썬 기초 · 사내 2기", 17, 12, 84, "1시간 전", "공동 강사"),
        ("백엔드 스터디 (야간)", 9, 5, 38, "어제", None)]
ARCHIVED = [("프론트엔드 입문 2기", 22, 8, 73, "3개월 전"), ("프론트엔드 입문 1기", 16, 6, 68, "8개월 전")]

def class_row(name, m, p, pct, when, role=None, archived=False):
    c = FAINT if archived else INK
    col = FAINT if archived else ratecolor(pct)
    tag = f' {badge(role)}' if role else ""
    action = (f'{btn("지난 기록 보기", small=True)}{btn("복사해서 새 기수 열기", small=True)}' if archived
              else f'{btn("열기", small=True)}')
    return (f'<div style="border-bottom:1px solid {RULE};padding:14px 18px;display:flex;align-items:center;gap:24px;">'
            f'<div style="flex:1;min-width:0;"><div style="font-size:15px;font-weight:500;color:{c};">{name}{tag}</div>'
            f'<div style="font-size:12px;color:{DIM};margin-top:3px;">참여자 {m}명 · 문제 {p}개 · 마지막 제출 {when}</div></div>'
            f'<div style="display:flex;align-items:center;gap:10px;width:220px;">{bar(pct, 120, col)}'
            f'<span style="font-family:{MONO};font-size:13px;font-weight:600;color:{col};">{pct}%</span>'
            f'<span style="font-size:11px;color:{FAINT};">달성률</span></div>'
            f'<div style="display:flex;gap:6px;">{action}</div></div>')

joined_row = (f'<div style="border-bottom:1px solid {RULE};padding:14px 18px;display:flex;align-items:center;gap:24px;">'
              f'<div style="flex:1;min-width:0;"><div style="font-size:15px;font-weight:500;">알고리즘 스터디 · 토요반</div>'
              f'<div style="font-size:12px;color:{DIM};margin-top:3px;">강사 박지훈 · 문제 6개</div></div>'
              f'<div style="display:flex;align-items:center;gap:10px;width:220px;">{bar(50, 120, INK)}'
              f'<span style="font-family:{MONO};font-size:13px;font-weight:600;">3/6</span><span style="font-size:11px;color:{FAINT};">통과</span></div>'
              f'<div>{btn("문제 풀기", small=True)}</div></div>')

HOME = body(
    pagehead("클래스", "내 클래스", None,
             actions=f'{btn("템플릿 둘러보기")}{btn("새 클래스 열기", primary=True)}')
    + f'<div style="display:flex;flex-direction:column;gap:10px;"><div style="font-size:15px;font-weight:600;">내가 가르치는 클래스 <span style="font-size:12.5px;color:{DIM};font-weight:400;">3</span></div>'
      + card("".join(class_row(*c) for c in LIVE)) + '</div>'
    + f'<div style="display:flex;flex-direction:column;gap:10px;"><div style="font-size:15px;font-weight:600;">참여 중인 클래스 <span style="font-size:12.5px;color:{DIM};font-weight:400;">1</span></div>'
      + card(joined_row) + '</div>'
    + f'<div style="display:flex;flex-direction:column;gap:10px;"><div style="font-size:15px;font-weight:600;">보관 </div>'
      + card("".join(class_row(*c, archived=True) for c in ARCHIVED)) + '</div>')
screen("Home", HOME, h=900)

# ───────────────────────────── 2. 클래스 상세 · 문제 ─────────────────────────────
PROBLEMS = [("HTML 문서 구조 잡기", 3, 92, "22/24", "3분 전", "open"),
            ("CSS 선택자와 박스 모델", 4, 79, "19/24", "21분 전", "open"),
            ("Flexbox 로 카드 목록 만들기", 4, 67, "16/24", "1시간 전", "open"),
            ("JavaScript 배열 다루기", 5, 54, "13/24", "2시간 전", "open"),
            ("fetch 로 목록 그리기", 5, 46, "11/24", "어제", "open"),
            ("상태를 컴포넌트로 나누기", 4, 25, "6/24", "어제", "hidden"),
            ("폼 검증과 접근성", 6, 12, "3/24", "3일 전", "open"),
            ("배포와 환경변수", 3, None, "—", "—", "draft")]

def problem_table():
    th = lambda t, a="left", w="": f'<th style="text-align:{a};font-size:11px;letter-spacing:0.06em;color:{DIM};font-weight:400;padding:10px 12px;border-bottom:1px solid {RULE};{w}">{t}</th>'
    head = "<tr>" + th("", "left", "width:28px") + th("문제") + th("필수", "right") + th("달성률") + th("통과", "right") + th("최근 제출", "right") + th("", "right") + "</tr>"
    rows = ""
    for i, (name, req, pct, passed, when, st) in enumerate(PROBLEMS, 1):
        tag = {"open": "", "hidden": " " + badge("숨김", "att"), "draft": " " + badge("초안")}[st]
        if pct is None:
            rate = f'<span style="font-size:12.5px;color:{FAINT};">아직 아무도 내지 않음</span>'
        else:
            col = ratecolor(pct)
            rate = f'<div style="display:flex;align-items:center;gap:10px;">{bar(pct, 110, col)}<span style="font-family:{MONO};font-size:13px;color:{col};font-weight:600;">{pct}%</span></div>'
        dimmed = f"color:{DIM};" if st == "draft" else ""
        cells = [
            f'<td style="padding:11px 12px;font-family:{MONO};font-size:12px;color:{FAINT};">{i}</td>',
            f'<td style="padding:11px 12px;font-size:14px;{dimmed}">{name}{tag}</td>',
            f'<td style="padding:11px 12px;text-align:right;font-family:{MONO};font-size:13px;color:{MUTED};">{req}</td>',
            f'<td style="padding:11px 12px;">{rate}</td>',
            f'<td style="padding:11px 12px;text-align:right;font-family:{MONO};font-size:13px;color:{MUTED};">{passed}</td>',
            f'<td style="padding:11px 12px;text-align:right;font-size:12.5px;color:{DIM};white-space:nowrap;">{when}</td>',
            f'<td style="padding:11px 12px;text-align:right;white-space:nowrap;">{btn("편집", small=True, ghost=True)}{btn("제출 현황", small=True, ghost=True)}{kebab()}</td>',
        ]
        rows += f'<tr style="border-bottom:1px solid {RULE};">{"".join(cells)}</tr>'
    return (f'<div style="border:1px solid {RULE};border-top:none;background:{SURFACE};">'
            f'<table style="width:100%;border-collapse:collapse;">{head}{rows}</table>'
            f'<div style="padding:12px 14px;display:flex;align-items:center;gap:10px;">{btn("새 문제", primary=True, small=True)}{btn("템플릿에서 가져오기", small=True)}</div></div>')

CLASS = body(
    f'<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;">{class_head(None)}{class_stats()}</div>'
    + join_strip() + class_tabs("문제")
    + f'<div style="display:flex;gap:20px;align-items:flex-start;margin-top:-20px;">'
      f'<div style="flex:1;min-width:0;">{problem_table()}</div>'
      f'<div style="width:320px;flex-shrink:0;display:flex;flex-direction:column;gap:16px;padding-top:20px;">{scoring_card()}{recent_card()}</div></div>')
screen("Class", CLASS, h=1000)

# ───────────────────────────── 3. 새 클래스 직후 ─────────────────────────────
def step(n, title, desc, done=False, action=None, current=False):
    dot = (f'<div style="width:22px;height:22px;background:{VER};color:{PAPER};display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0;">✓</div>' if done
           else f'<div style="width:22px;height:22px;border:1px solid {INK if current else RULE};color:{INK if current else DIM};display:flex;align-items:center;justify-content:center;font-family:{MONO};font-size:12px;flex-shrink:0;">{n}</div>')
    a = f'<div>{btn(action, primary=current, small=True)}</div>' if action and not done else ""
    tcol = DIM if done else INK
    return (f'<div style="display:flex;gap:14px;align-items:flex-start;padding:14px 16px;border-top:1px solid {RULE};">{dot}'
            f'<div style="flex:1;"><div style="font-size:14px;font-weight:500;color:{tcol};">{title}</div>{f'<div style="font-size:12.5px;color:{MUTED};margin-top:3px;">{desc}</div>' if desc else ""}</div>{a}</div>')

START = card(cardhead("시작하기")
             + step(1, "채점 연결 넣기", "OpenAI 키 · ••••7f2a", done=True)
             + step(2, "첫 문제 만들기", "", action="새 문제", current=True)
             + step(3, "가입 링크 공유하기", "", action="복사"))

CLASS_EMPTY = body(
    f'<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;">{class_head(None)}{class_stats("0", "0", "—", DIM)}</div>'
    + join_strip() + class_tabs("문제")
    + f'<div style="display:flex;gap:20px;align-items:flex-start;margin-top:-20px;">'
      f'<div style="flex:1;min-width:0;">' + f'<div style="border:1px solid {RULE};border-top:none;background:{SURFACE};padding:48px 16px;text-align:center;color:{DIM};font-size:13.5px;">아직 만든 문제가 없습니다.<div style="margin-top:14px;display:flex;justify-content:center;gap:8px;">{btn("새 문제", primary=True, small=True)}{btn("템플릿에서 가져오기", small=True)}{btn("다른 클래스에서 복사", small=True)}</div></div>' + '</div>'
      f'<div style="width:320px;flex-shrink:0;display:flex;flex-direction:column;gap:16px;padding-top:20px;">{START}</div></div>')
screen("ClassEmpty", CLASS_EMPTY, h=760)

# ───────────────────────────── 4. 클래스 상세 · 참여자 ─────────────────────────────
MEMBERS = [("서지우", [3,3,3,2,1,1,0,0], "9/1", "3분 전"), ("한도현", [3,3,2,2,1,0,0,0], "9/1", "9분 전"),
           ("최민재", [3,3,3,3,2,1,1,0], "9/1", "12분 전"), ("오세아", [3,3,3,1,1,0,0,0], "9/2", "18분 전"),
           ("배수연", [3,3,3,3,3,2,1,0], "9/2", "1시간 전"), ("문지호", [3,2,1,0,0,0,0,0], "9/2", "어제"),
           ("서아린", [3,3,3,3,2,1,0,0], "9/3", "어제"), ("남기훈", [2,1,0,0,0,0,0,0], "9/3", "3일 전"),
           ("조은비", [3,3,3,2,2,1,0,0], "9/3", "어제"), ("윤태경", [3,3,2,1,1,0,0,0], "9/4", "2일 전"),
           ("강시우", [3,3,3,3,3,3,2,0], "9/4", "1시간 전"), ("임도윤", [3,3,3,3,2,1,1,0], "9/5", "어제"),
           ("김하늘", [4,0,0,0,0,0,0,0], "9/14", "방금"), ("김선우", [3,3,0,0,0,0,0,0], "9/1", "—", "instructor"),
           ("박도현", [3,3,3,1,1,0,0,0], "9/6", "5일 전", "expelled")]
SHORT = ["HTML 구조", "CSS 박스", "Flexbox", "JS 배열", "fetch", "컴포넌트", "폼 검증", "배포"]
KIND = {3: "passed", 2: "failed", 1: "scoring", 4: "blocked", 0: "none"}

def roster():
    th = lambda t, a="center", extra="": f'<th style="text-align:{a};padding:10px 10px;font-size:11px;color:{DIM};font-weight:400;border-bottom:1px solid {RULE};white-space:nowrap;{extra}">{t}</th>'
    head = "<tr>" + th("참여자", "left", f"position:sticky;left:0;background:{SURFACE};letter-spacing:0.06em;padding-left:16px;") + "".join(th(s) for s in SHORT) + th("통과", "right") + th("최근 제출", "right") + th("", "right") + "</tr>"
    rows = ""
    for m in MEMBERS:
        name, vals, joined, last = m[:4]
        flag = m[4] if len(m) > 4 else None
        n = sum(1 for v in vals if v == 3)
        if flag == "instructor":
            label = f'{name} <span style="font-size:11px;color:{DIM};margin-left:6px;">강사 본인</span>'
        elif flag == "expelled":
            label = f'<span style="color:{DIM};text-decoration:line-through;">{name}</span> <span style="font-size:11px;color:{ATT};margin-left:6px;">내보냄</span>'
        else:
            label = name
        action = kebab() if flag != "expelled" else ""
        rows += (f'<tr style="border-bottom:1px solid {RULE};">'
                 f'<td style="padding:7px 10px 7px 16px;font-size:13px;white-space:nowrap;position:sticky;left:0;background:{SURFACE};">{label}'
                 f'<span style="font-size:11px;color:{FAINT};margin-left:8px;">{joined} 가입</span></td>'
                 + "".join(f'<td style="padding:7px 10px;text-align:center;">{mark(KIND[v])}</td>' for v in vals)
                 + f'<td style="padding:7px 10px;text-align:right;font-family:{MONO};font-size:12.5px;color:{MUTED};">{n}/8</td>'
                 f'<td style="padding:7px 10px;text-align:right;font-size:12px;color:{DIM};white-space:nowrap;">{last}</td>'
                 f'<td style="padding:7px 16px 7px 10px;text-align:right;">{action}</td></tr>')
    counted = [m for m in MEMBERS if len(m) == 4]
    rates = [round(100 * sum(1 for m in counted if m[1][i] == 3) / len(counted)) for i in range(8)]
    foot = (f'<tr style="background:{PAPER};"><td style="padding:10px 16px;font-size:11px;color:{DIM};letter-spacing:0.06em;position:sticky;left:0;background:{PAPER};">달성률</td>'
            + "".join(f'<td style="padding:10px;text-align:center;font-family:{MONO};font-size:13px;font-weight:600;color:{ratecolor(p)};">{p}%</td>' for p in rates)
            + '<td></td><td></td><td></td></tr>')
    legend = "".join(f'<span style="display:inline-flex;align-items:center;gap:6px;">{mark(k, 12)} {l}</span>'
                     for k, l in [("passed", "통과"), ("failed", "시도했으나 미통과"), ("scoring", "채점 중"), ("blocked", "설정 필요"), ("none", "미제출")])
    return (f'<div style="border:1px solid {RULE};border-top:none;background:{SURFACE};">'
            f'<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">{head}{rows}{foot}</table></div>'
            f'<div style="display:flex;align-items:center;gap:20px;padding:10px 16px;border-top:1px solid {RULE};font-size:12px;color:{MUTED};">{legend}</div></div>')

ROSTER = body(
    f'<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;">{class_head(None)}{class_stats()}</div>'
    + join_strip() + class_tabs("참여자") + f'<div style="margin-top:-20px;">{roster()}</div>')
screen("Roster", ROSTER, h=940)

# ───────────────────────────── 5. 클래스 상세 · 강사 ─────────────────────────────
def instructor_row(name, role, extra="", actions=""):
    return (f'<div style="display:flex;align-items:center;gap:12px;padding:12px 16px;border-top:1px solid {RULE};">'
            f'<div style="font-size:14px;">{name}</div>{role}<span style="font-size:12px;color:{DIM};">{extra}</span>'
            f'<div style="margin-left:auto;display:flex;gap:6px;">{actions}</div></div>')

INSTRUCTORS = body(
    f'<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;">{class_head(None)}{class_stats()}</div>'
    + join_strip() + class_tabs("강사")
    + f'<div style="margin-top:-20px;display:flex;gap:20px;align-items:flex-start;">'
      f'<div style="flex:1;min-width:0;">'
      + f'<div style="border:1px solid {RULE};border-top:none;background:{SURFACE};">'
        f'<div style="padding:12px 16px;font-size:15px;font-weight:600;">이 클래스의 강사 <span style="font-size:12.5px;color:{DIM};font-weight:400;margin-left:10px;">3명</span></div>'
        + instructor_row("김선우", badge("소유자"), "나")
        + instructor_row("박조교", badge("공동 강사"), "9/3 수락", f'{btn("소유권 넘기기", small=True, ghost=True)}{btn("내보내기", small=True, ghost=True)}')
        + instructor_row("이민지", badge("공동 강사") + " " + badge("소유권 이전 대기", "att"), "10/20 까지 답을 기다립니다", btn("요청 취소", small=True, ghost=True))
        + '</div>'
      + f'<div style="margin-top:20px;">' + card(cardhead("공동 강사 초대", right=btn("초대 링크 만들기", primary=True, small=True))
          + f'<div style="display:flex;align-items:center;gap:12px;padding:11px 16px;"><span style="font-family:{MONO};font-size:12.5px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">classroom.codemit.kr/invite/9f2k…a81c</span>'
            f'<span style="font-size:12px;color:{DIM};">내가 10/12 만듦 · 10/19 까지</span>{btn("복사", small=True)}{btn("취소", small=True, ghost=True)}</div>') + '</div>'
      + '</div>'
      f'<div style="width:320px;flex-shrink:0;padding-top:20px;display:flex;flex-direction:column;gap:16px;">'
      + card(cardhead("이 클래스 떠나기") + f'<div style="padding:12px 16px;">{btn("떠나기", small=True, danger=True)}</div>')
      + '</div></div>')
screen("Instructors", INSTRUCTORS, h=760)

# ───────────────────────────── 6. 클래스 설정 ─────────────────────────────
def settings_nav(active):
    items = ["채점 연결", "기본 모델", "사용량", "이름", "템플릿으로 공개", "보관과 삭제"]
    out = ""
    for it in items:
        if it == active:
            out += f'<div style="padding:7px 12px;border-left:2px solid {INK};font-size:13px;font-weight:500;">{it}</div>'
        else:
            out += f'<div style="padding:7px 12px;border-left:2px solid transparent;font-size:13px;color:{MUTED};">{it}</div>'
    return f'<div style="width:180px;flex-shrink:0;position:sticky;top:24px;display:flex;flex-direction:column;gap:2px;">{out}</div>'

def model_row(name, ctx, cost, chosen, hint_text):
    return (f'<div style="display:flex;align-items:center;gap:12px;padding:11px 16px;border-top:1px solid {RULE};">'
            + check("", chosen, radio=True).replace('padding:6px 0;', 'padding:0;')
            + f'<div style="flex:1;"><div style="font-family:{MONO};font-size:13.5px;">{name}</div>{f'<div style="font-size:11.5px;color:{DIM};margin-top:2px;">{hint_text}</div>' if hint_text else ""}</div>'
            f'<div style="text-align:right;width:110px;"><div style="font-family:{MONO};font-size:12.5px;color:{MUTED};">{ctx}</div><div style="font-size:11px;color:{FAINT};">컨텍스트</div></div>'
            f'<div style="text-align:right;width:120px;font-size:12.5px;color:{MUTED};white-space:nowrap;">{cost}</div></div>')

SETTINGS = body(
    pagehead("내 클래스 › " + CLASS_NAME, "클래스 설정", None, actions=btn("클래스로 돌아가기", small=True))
    + f'<div style="display:flex;gap:28px;align-items:flex-start;">{settings_nav("사용량")}'
      f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:18px;">'
      + card(cardhead("채점 연결")
             + f'<div style="padding:14px 16px;display:flex;flex-direction:column;gap:12px;">'
               f'<div style="display:flex;align-items:center;gap:10px;">{badge("연결됨", "ver")}<span style="font-size:13px;">OpenAI 키 · <span style="font-family:{MONO};">sk-proj-••••7f2a</span></span><span style="font-size:12px;color:{DIM};">10/02 확인</span><span style="margin-left:auto;">{btn("바꾸기", small=True)}</span></div>'
               f'<div style="display:flex;gap:6px;">{btn("OpenAI 키", primary=True, small=True)}{btn("호환 서버", small=True)}</div></div>')
      + card(cardhead("기본 모델")
             + model_row("gpt-5-mini", "400K", "시도 1건 약 6원", True, "클래스 기본값")
             + model_row("gpt-5", "400K", "약 30원", False, "")
             + model_row("gpt-5-nano", "128K", "약 2원", False, "")
             + f'<div style="padding:10px 16px;border-top:1px solid {RULE};font-size:12px;color:{DIM};">모델 4개 더 보기</div>')
      + card(cardhead("사용량")
             + f'<div style="padding:14px 16px;display:flex;flex-direction:column;gap:12px;">'
               f'<div style="display:flex;align-items:baseline;gap:14px;"><span style="font-family:{MONO};font-size:26px;font-weight:600;">1,560,000</span><span style="font-size:13px;color:{MUTED};">토큰</span><span style="font-family:{MONO};font-size:15px;margin-left:auto;">약 9,400원</span></div>'
               f'<div style="display:flex;gap:28px;font-size:12.5px;">'
               f'<span><span style="color:{MUTED};">채점</span> <span style="font-family:{MONO};">412회</span></span>'
               f'<span><span style="color:{MUTED};">1회 평균</span> <span style="font-family:{MONO};">3,800 토큰 · 약 23원</span></span>'
               f'<span><span style="color:{MUTED};">어림</span> <span style="font-family:{MONO};">120,000 토큰</span></span>'
               f'<span style="margin-left:auto;color:{DIM};">OpenAI 사용량 화면 ↗</span></div></div>')
      + '</div></div>')
screen("Settings", SETTINGS, h=1040)

# ───────────────────────────── 7. 문제 편집 ─────────────────────────────
REQS = [("fetch 로 목록 데이터를 받아온다", True), ("로딩 중 상태를 화면에 표시한다", True),
        ("요청이 실패하면 오류 문구를 보여준다", True), ("목록이 비어 있을 때의 화면이 따로 있다", True),
        ("각 항목에 고유한 key 가 있다", True), ("요청을 취소할 수 있다", False), ("재시도 버튼이 있다", False)]

def req_row(i, text, required):
    return (f'<div style="display:flex;align-items:center;gap:12px;padding:9px 14px;border-top:1px solid {RULE};">'
            f'<span style="color:{FAINT};font-size:13px;cursor:grab;">⋮⋮</span><span style="font-family:{MONO};font-size:11.5px;color:{FAINT};width:14px;">{i}</span>'
            f'<div style="flex:1;border:1px solid transparent;padding:4px 0;font-size:13.5px;">{text}</div>'
            f'{badge("필수", "att") if required else badge("선택")}<span style="font-size:12px;color:{FAINT};">삭제</span></div>')

PROBLEM = body(
    pagehead(CLASS_NAME + " › 문제 5", "fetch 로 목록 그리기", actions=f'{btn("학생 화면으로")}{btn("제출 현황 11")}{btn("저장", primary=True)}', extra=badge("열림", "ver"))
    + f'<div style="display:flex;gap:20px;align-items:flex-start;">'
      f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:18px;">'
      + field("제목", "fetch 로 목록 그리기")
      + f'<div style="display:flex;flex-direction:column;gap:6px;"><div style="display:flex;justify-content:space-between;"><span style="font-size:12px;color:{MUTED};">설명</span><span style="font-size:11.5px;color:{DIM};">마크다운 · 작성 | 미리보기</span></div>'
        f'<div style="border:1px solid {RULE};background:{SURFACE};"><div style="border-bottom:1px solid {RULE};padding:6px 10px;font-size:12px;color:{DIM};letter-spacing:2px;">H B I S — 66 ≡ ☑ ⊞ 🖼 🔗 ⟨/⟩</div>'
        f'<div style="padding:12px;min-height:200px;font-size:13.5px;line-height:1.7;">공개 API 에서 목록을 받아 화면에 그립니다.<br><br>비어 있을 때와 실패했을 때를 각각 어떻게 보여줄지가 이 문제의 핵심입니다 — 성공 경로만 만들면 통과하지 못합니다.</div></div></div>'
      + card(cardhead("체크리스트")
             + f'<div style="display:flex;align-items:center;gap:12px;padding:9px 14px;background:{PAPER};font-size:12.5px;color:{MUTED};">{badge("기본")} 소스에 문법 오류가 없다 <span style="margin-left:auto;">{check("켜짐", True).replace("padding:6px 0;", "padding:0;")}</span></div>'
             + "".join(req_row(i, t, r) for i, (t, r) in enumerate(REQS, 1))
             + f'<div style="display:flex;gap:8px;align-items:center;padding:10px 14px;border-top:1px solid {RULE};"><div style="flex:1;border:1px solid {RULE};padding:7px 10px;font-size:13px;color:{FAINT};">새 항목</div>{badge("필수", "att")}{btn("추가", small=True)}</div>')
      + '</div>'
      f'<div style="width:300px;flex-shrink:0;position:sticky;top:24px;display:flex;flex-direction:column;gap:14px;">'
      + card(cardhead("상태") + f'<div style="padding:12px 16px;display:flex;align-items:center;gap:10px;">{badge("열림", "ver")}<span style="margin-left:auto;">{btn("숨기기", small=True)}</span></div>')
      + card(cardhead("제출 형식") + f'<div style="padding:6px 16px 10px;">{check("zip 파일", True)}{check("GitHub 저장소", True)}</div>')
      + card(cardhead("채점 모델") + f'<div style="padding:6px 16px 10px;">{check("클래스 기본값 — gpt-5-mini", False, radio=True)}{check("이 문제만 gpt-5", True, radio=True)}<div style="margin-top:8px;font-size:11.5px;color:{DIM};">시도 1건 약 30원 · 참여자 24명 × 평균 1.6회 ≈ 1,150원</div></div>')
      + card(cardhead("채점 지침", right=badge("보통")) + f'<div style="padding:10px 16px;">{check("엄격", False, radio=True)}{check("보통", True, radio=True)}{check("관대", False, radio=True)}{check("직접 입력", False, radio=True)}</div>')
      + f'<div style="font-size:12.5px;color:{DIM};padding:4px 2px;line-height:2;"><span style="text-decoration:underline;">다른 클래스로 복사</span> · <span style="text-decoration:underline;">템플릿으로 공개</span> · <span style="text-decoration:underline;color:{ATT};">문제 삭제</span></div>'
      + '</div></div>')
screen("ProblemEdit", PROBLEM, h=1000)

# ───────────────────────────── 8. 참여자 · 문제 목록 ─────────────────────────────
MINE = [("HTML 문서 구조 잡기", "passed", 1, "9/2"), ("CSS 선택자와 박스 모델", "passed", 2, "9/5"),
        ("Flexbox 로 카드 목록 만들기", "passed", 1, "9/9"), ("JavaScript 배열 다루기", "failed", 3, "어제"),
        ("fetch 로 목록 그리기", "scoring", 3, "방금"), ("폼 검증과 접근성", "none", 0, "—")]

def mine_row(title, k, tries, when):
    label = {"passed": badge("통과", "ver"), "failed": badge("미통과", "att"), "scoring": badge("채점 중"), "none": badge("미제출")}[k]
    t = f'<span style="font-size:12px;color:{DIM};white-space:nowrap;">시도 {tries}회 · 마지막 {when}</span>' if tries else ""
    return (f'<div style="display:flex;align-items:center;gap:14px;padding:10px 16px;border-bottom:1px solid {RULE};">'
            f'<div style="flex:1;min-width:0;font-size:14px;">{title}</div>{t}{label}</div>')

MINE_PAGE = body(
    pagehead(CLASS_NAME + " · 김선우, 박조교", "문제", None,
             actions=f'<span style="font-size:12.5px;color:{MUTED};">내 이름 <b style="color:{INK};">서지우</b> · <span style="text-decoration:underline;">바꾸기</span></span>')
    + f'<div style="display:flex;align-items:center;gap:14px;"><div style="font-family:{MONO};font-size:15px;font-weight:600;">3/6 통과</div>{bar(50, 320, VER, 8)}<span style="font-size:12px;color:{DIM};">채점 중 1 · 미제출 1</span></div>'
    + card("".join(mine_row(*r) for r in MINE))
    + f'<div style="font-size:12.5px;color:{DIM};">▸ 숨겨진 문제 1</div>')
screen("Mine", MINE_PAGE, h=760)

# ───────────────────────────── 9. 참여자 · 문제와 제출 ─────────────────────────────
VERD = [("fetch 로 목록 데이터를 받아온다", True, "passed", None),
        ("로딩 중 상태를 화면에 표시한다", True, "passed", None),
        ("요청이 실패하면 오류 문구를 보여준다", True, "failed", "요청이 실패해도 화면이 로딩 상태 그대로 멈춥니다. catch 블록이 콘솔에만 남기고 화면에는 아무것도 바꾸지 않습니다."),
        ("목록이 비어 있을 때의 화면이 따로 있다", True, "failed", "빈 배열일 때 아무것도 그리지 않아 화면이 비어 보입니다 — 「아직 없습니다」 같은 안내가 필요합니다."),
        ("각 항목에 고유한 key 가 있다", True, "passed", None),
        ("요청을 취소할 수 있다", False, "none", None), ("재시도 버튼이 있다", False, "none", None)]

def verdict_row(text, required, k, reason):
    tag = "" if required else " " + badge("선택")
    r = f'<div style="font-size:12.5px;color:{MUTED};line-height:1.65;margin-top:4px;">{reason}</div>' if reason else ""
    m = mark(k) if k != "none" else f'<span style="display:inline-block;width:14px;height:14px;border:1px solid {RULE};"></span>'
    return f'<div style="display:flex;gap:12px;padding:11px 16px;border-top:1px solid {RULE};"><div style="margin-top:3px;">{m}</div><div style="flex:1;"><div style="font-size:13.5px;">{text}{tag}</div>{r}</div></div>'

def attempt(n, when, k, detail):
    b = {"scoring": badge("채점 중"), "passed": badge("통과", "ver"), "failed": badge("미통과", "att"), "pending": badge("채점 대기")}[k]
    return (f'<div style="display:flex;align-items:center;gap:14px;padding:12px 16px;border-top:1px solid {RULE};">'
            f'<span style="font-family:{MONO};font-size:12.5px;color:{FAINT};width:48px;">시도 {n}</span>{b}'
            f'<span style="font-size:12.5px;color:{MUTED};flex:1;">{detail}</span><span style="font-size:11.5px;color:{FAINT};">{when}</span></div>')

SUBMIT_CARD = card(cardhead("제출")
    + f'<div style="padding:16px;display:flex;flex-direction:column;gap:12px;">'
      f'<div style="border:1px dashed {RULE};background:{PAPER};padding:22px;text-align:center;"><div style="font-size:13.5px;color:{MUTED};">소스 zip 을 끌어다 놓거나 <span style="color:{ATT};">고르기</span></div><div style="font-size:11.5px;color:{FAINT};margin-top:4px;">최대 50MB</div></div>'
      f'<div style="display:flex;align-items:center;gap:12px;color:{FAINT};font-size:11.5px;"><div style="height:1px;background:{RULE};flex:1;"></div>또는<div style="height:1px;background:{RULE};flex:1;"></div></div>'
      f'<div style="border:1px solid {RULE};padding:9px 12px;font-family:{MONO};font-size:13px;color:{FAINT};">https://github.com/…</div>'
      f'{btn("제출하기", primary=True)}</div>')

PROGRESS_CARD = card(f'<div style="padding:14px 16px;"><div style="font-size:12px;color:{MUTED};margin-bottom:8px;">이 문제의 진행</div>'
                     f'<div style="display:flex;align-items:center;gap:10px;">{bar(60, 200, INK)}<span style="font-family:{MONO};font-size:13px;font-weight:600;">3/5</span></div></div>')

SUBMIT = body(
    pagehead(CLASS_NAME + " › 문제", "fetch 로 목록 그리기", actions=btn("문제 목록으로", small=True), extra=badge("아직 미통과", "att"))
    + f'<div style="display:flex;gap:20px;align-items:flex-start;">'
      f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:18px;">'
      + card(cardhead("설명") + f'<div style="padding:14px 16px;font-size:13.5px;line-height:1.7;">공개 API 에서 목록을 받아 화면에 그립니다.<br><br>비어 있을 때와 실패했을 때를 각각 어떻게 보여줄지가 이 문제의 핵심입니다 — 성공 경로만 만들면 통과하지 못합니다.</div>')
      + card(f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;">'
             f'<div style="font-size:15px;font-weight:600;">체크리스트 <span style="font-size:12.5px;color:{DIM};font-weight:400;margin-left:10px;">시도 2 의 판정 · 12분 전 · 지침 「보통」</span></div>{badge("미통과 · 필수 3/5", "att")}</div>'
             + "".join(verdict_row(*v) for v in VERD)
             + f'<div style="padding:10px 16px;border-top:1px solid {RULE};font-size:11.5px;color:{FAINT};">gpt-5 · 12분 전</div>')
      + card(cardhead("내 시도", "3회") + attempt(3, "방금", "scoring", "")
             + attempt(2, "12분 전", "failed", "필수 3/5 — 오류 화면과 빈 목록 화면 · <span style='text-decoration:underline;'>판정 보기</span>")
             + attempt(1, "1시간 전", "failed", "필수 1/5"))
      + '</div>'
      f'<div style="width:360px;flex-shrink:0;position:sticky;top:24px;display:flex;flex-direction:column;gap:14px;">{SUBMIT_CARD}{PROGRESS_CARD}</div></div>')
screen("Submit", SUBMIT, h=1000)

# ───────────────────────────── 10. 가입 링크 (모바일, 로그인 전 · 후) ─────────────────────────────
def join_frame(logged_in):
    stats = (f'<div style="display:flex;gap:18px;font-size:13px;color:{MUTED};"><span>강사 김선우, 박조교</span>'
             f'<span><b style="font-family:{MONO};color:{INK};">8</b> 문제</span><span><b style="font-family:{MONO};color:{INK};">24</b> 참여자</span></div>')
    head_bits = (f'<div style="display:flex;flex-direction:column;gap:8px;">{eyebrow("초대받은 클래스")}'
                 f'<div style="font-size:24px;font-weight:600;letter-spacing:-0.01em;line-height:1.3;">{CLASS_NAME}</div>{stats}</div>')
    if logged_in:
        form = (f'<div style="display:flex;flex-direction:column;gap:14px;">'
                f'{field("이 클래스에서 불릴 이름", "서지우")}'
                f'{btn("가입하고 문제 보기", primary=True)}</div>')
    else:
        form = f'<div style="display:flex;">{btn("로그인하고 가입하기", primary=True).replace("display:inline-block;", "display:block;flex:1;text-align:center;")}</div>'
    return (f'<div style="flex:1;display:flex;justify-content:center;padding:64px 32px;">'
            f'<div style="width:440px;display:flex;flex-direction:column;gap:28px;">{head_bits}'
            f'<div style="border:1px solid {RULE};background:{SURFACE};padding:20px;">{form}</div></div></div>')

screen("JoinGuest", header(guest=True) + join_frame(False), h=640)
screen("JoinMember", header(who="서지우") + join_frame(True), h=640)

# ───────────────────────────── 11. 제출 현황 (강사) ─────────────────────────────
def sub_row(name, n, k, when, items_ok, items_total, extra=""):
    b = {"passed": badge("통과", "ver"), "failed": badge("미통과", "att"), "scoring": badge("채점 중"), "pending": badge("채점 대기", "att")}[k]
    return (f'<div style="display:flex;align-items:center;gap:14px;padding:11px 16px;border-top:1px solid {RULE};">'
            f'<div style="width:90px;font-size:13.5px;">{name}</div><span style="font-family:{MONO};font-size:12px;color:{FAINT};width:44px;">시도 {n}</span>{b}'
            f'<span style="font-size:12.5px;color:{MUTED};flex:1;">필수 {items_ok}/{items_total}{extra}</span>'
            f'<span style="font-size:11.5px;color:{FAINT};">{when}</span>{btn("판정", small=True, ghost=True)}{btn("저장소", small=True, ghost=True)}</div>')

SUBMISSIONS = body(
    pagehead(CLASS_NAME + " › 문제 5", "fetch 로 목록 그리기 · 제출 현황", actions=f'{btn("문제 편집")}', extra=badge("열림", "ver"))
    + statbar([("통과", "11/24", VER), ("시도", "38", None), ("채점 중", "2", None), ("채점 대기", "0", None)])
    + f'<div style="display:flex;gap:8px;align-items:center;font-size:12.5px;color:{MUTED};">{btn("참여자별 최신 시도", primary=True, small=True)}{btn("모든 시도", small=True)}<span style="margin-left:auto;">정렬: 최근 제출순</span></div>'
    + card(sub_row("서지우", 3, "scoring", "방금", "—", 5)
           + sub_row("한도현", 2, "failed", "9분 전", 3, 5, " — 오류 화면, 빈 목록")
           + sub_row("최민재", 1, "passed", "12분 전", 5, 5)
           + sub_row("오세아", 4, "failed", "18분 전", 4, 5, " — 빈 목록")
           + sub_row("배수연", 1, "passed", "1시간 전", 5, 5)
           + sub_row("문지호", 2, "passed", "2시간 전", 5, 5)
           + f'<div style="padding:10px 16px;border-top:1px solid {RULE};font-size:12.5px;color:{DIM};">아직 내지 않은 참여자 13명 — <span style="text-decoration:underline;">참여자 탭에서 보기</span></div>')
)
screen("Submissions", SUBMISSIONS, h=760)

if __name__ == "__main__":
    for name, (inner, h, w) in SCREENS.items():
        inner_full = inner if name.startswith("Join") else header() + inner
        write(f"{name}.dc.html", inner_full, h=h, w=w)
