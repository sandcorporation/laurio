# -*- coding: utf-8 -*-
# 강의실 「권장 기한·마감」 시안 (2026-10-21). v2(../classroom-v2) 의 조각·데이터를 그대로 쓰고,
# 기한이 닿는 화면 여섯 장만 다시 그린다. `python3 gen.py` 가 이 디렉터리에 HTML 을 쓴다.
import sys, os
V2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "classroom-v2")
sys.path.insert(0, V2)
from _lib import *
import gen as v2

SCREENS = {}
def screen(name, inner, h=960, w=1200):
    SCREENS[name] = (inner, h, w)

CLASS_NAME = v2.CLASS_NAME

# ── 기한 표기 조각 ─────────────────────────────────────────────────────────
def when(d, t="23:59"):
    return f'<span style="font-family:{MONO};font-size:12.5px;">{d} {t}</span>'

def due_inline(rec=None, due=None, passed_due=False):
    """강사 표: 제목 옆 한 줄 — 「마감 10/27」만. 지난 마감은 흐리게(붉지 않다 — 강사에게는 경고가 아니다)."""
    mono = lambda d: f'<span style="font-family:{MONO};">{d}</span>'
    if due:
        return f'<span style="font-size:11.5px;color:{FAINT if passed_due else DIM};margin-left:10px;">마감 {mono(due)}</span>'
    if rec:
        return f'<span style="font-size:11.5px;color:{DIM};margin-left:10px;">권장 {mono(rec)}</span>'
    return ""

def due_cell(rec=None, due=None, passed_due=False, passed_rec=False, done=False, w=250):
    """참여자 목록: 권장·마감이 각각 고정 폭 칸이라 앞뒤 글자 길이와 무관하게 같은 x 에 선다.
    붉은 글자는 **아직 통과하지 못했는데 마감이 지난** 경우뿐이다. 이미 통과한 문제는 전부 흐리게."""
    mono = lambda d: f'<span style="font-family:{MONO};">{d}</span>'
    rec_html = f'<span style="color:{FAINT if (done or passed_rec) else DIM};">권장 {mono(rec)}</span>' if rec else ""
    if due:
        if done:
            due_html = f'<span style="color:{FAINT};">마감 {mono(due)}</span>'
        elif passed_due:
            due_html = f'<span style="color:{ATT};">마감 지남 {mono(due)}</span>'
        else:
            due_html = f'<span style="color:{INK};">마감 {mono(due)}</span>'
    else:
        due_html = ""
    return (f'<div style="display:flex;flex-shrink:0;font-size:12.5px;white-space:nowrap;">'
            f'<span style="display:inline-block;width:100px;text-align:left;">{rec_html}</span>'
            f'<span style="display:inline-block;width:150px;text-align:left;">{due_html}</span></div>')

def late_badge():
    return badge("늦음")

# ── 1. 문제 편집 — 오른쪽 열에 「기한」 카드 ──────────────────────────────────
def datetime_field(label, date, time, empty=False):
    col = f"color:{FAINT};" if empty else ""
    box = lambda v, w: f'<div style="border:1px solid {RULE};background:{SURFACE};padding:7px 10px;font-family:{MONO};font-size:13px;{col}width:{w}px;">{v}</div>'
    clear = "" if empty else f'<span style="font-size:11.5px;color:{FAINT};margin-left:auto;text-decoration:underline;">비우기</span>'
    return (f'<div style="display:flex;flex-direction:column;gap:6px;padding:10px 16px;">'
            f'<div style="display:flex;align-items:center;font-size:12px;color:{MUTED};">{label}{clear}</div>'
            f'<div style="display:flex;gap:6px;">{box(date, 124)}{box(time, 72)}</div></div>')

DUE_CARD = card(cardhead("기한")
    + datetime_field("권장 기한", "2026-10-24", "23:59")
    + f'<div style="border-top:1px solid {RULE};"></div>'
    + datetime_field("마감", "2026-10-27", "23:59"))

DUE_CARD_EMPTY = card(cardhead("기한")
    + datetime_field("권장 기한", "연도-월-일", "--:--", empty=True)
    + f'<div style="border-top:1px solid {RULE};"></div>'
    + datetime_field("마감", "연도-월-일", "--:--", empty=True))

def problem_edit(due_card, status_badge=badge("열림", "ver")):
    return body(
        pagehead(CLASS_NAME + " › 문제 5", "fetch 로 목록 그리기", actions=f'{btn("학생 화면으로")}{btn("제출 현황 11")}{btn("저장", primary=True)}', extra=status_badge)
        + f'<div style="display:flex;gap:20px;align-items:flex-start;">'
          f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:18px;">'
          + field("제목", "fetch 로 목록 그리기")
          + f'<div style="display:flex;flex-direction:column;gap:6px;"><div style="display:flex;justify-content:space-between;"><span style="font-size:12px;color:{MUTED};">설명</span><span style="font-size:11.5px;color:{DIM};">마크다운 · 작성 | 미리보기</span></div>'
            f'<div style="border:1px solid {RULE};background:{SURFACE};"><div style="border-bottom:1px solid {RULE};padding:6px 10px;font-size:12px;color:{DIM};letter-spacing:2px;">H B I S — 66 ≡ ☑ ⊞ 🖼 🔗 ⟨/⟩</div>'
            f'<div style="padding:12px;min-height:200px;font-size:13.5px;line-height:1.7;">공개 API 에서 목록을 받아 화면에 그립니다.<br><br>비어 있을 때와 실패했을 때를 각각 어떻게 보여줄지가 이 문제의 핵심입니다 — 성공 경로만 만들면 통과하지 못합니다.</div></div></div>'
          + card(cardhead("체크리스트")
                 + f'<div style="display:flex;align-items:center;gap:12px;padding:9px 14px;background:{PAPER};font-size:12.5px;color:{MUTED};">{badge("기본")} 소스에 문법 오류가 없다 <span style="margin-left:auto;">{check("켜짐", True).replace("padding:6px 0;", "padding:0;")}</span></div>'
                 + "".join(v2.req_row(i, t, r) for i, (t, r) in enumerate(v2.REQS, 1))
                 + f'<div style="display:flex;gap:8px;align-items:center;padding:10px 14px;border-top:1px solid {RULE};"><div style="flex:1;border:1px solid {RULE};padding:7px 10px;font-size:13px;color:{FAINT};">새 항목</div>{badge("필수", "att")}{btn("추가", small=True)}</div>')
          + '</div>'
          f'<div style="width:300px;flex-shrink:0;position:sticky;top:24px;display:flex;flex-direction:column;gap:14px;">'
          + card(cardhead("상태") + f'<div style="padding:12px 16px;display:flex;align-items:center;gap:10px;">{status_badge}<span style="margin-left:auto;">{btn("숨기기", small=True)}</span></div>')
          + due_card
          + card(cardhead("제출 형식") + f'<div style="padding:6px 16px 10px;">{check("zip 파일", True)}{check("GitHub 저장소", True)}</div>')
          + card(cardhead("채점 모델") + f'<div style="padding:6px 16px 10px;">{check("클래스 기본값 — gpt-5-mini", False, radio=True)}{check("이 문제만 gpt-5", True, radio=True)}</div>')
          + card(cardhead("채점 지침", right=badge("보통")) + f'<div style="padding:10px 16px;">{check("엄격", False, radio=True)}{check("보통", True, radio=True)}{check("관대", False, radio=True)}{check("직접 입력", False, radio=True)}</div>')
          + f'<div style="font-size:12.5px;color:{DIM};padding:4px 2px;line-height:2;"><span style="text-decoration:underline;">다른 클래스로 복사</span> · <span style="text-decoration:underline;">템플릿으로 공개</span> · <span style="text-decoration:underline;color:{ATT};">문제 삭제</span></div>'
          + '</div></div>')

screen("ProblemEdit", problem_edit(DUE_CARD), h=1060)
screen("ProblemEditEmpty", problem_edit(DUE_CARD_EMPTY), h=1060)

# ── 2. 클래스 상세 · 문제 표 — 「기한」 열 ──────────────────────────────────
# (이름, 필수, 달성률, 통과, 최근 제출, 상태, 권장, 마감, 권장 지남, 마감 지남)
PROBLEMS = [
    ("HTML 문서 구조 잡기", 3, 96, "23/24", "9/12", "open", None, "9/12", False, True),
    ("CSS 선택자와 박스 모델", 4, 88, "21/24", "9/20", "open", "9/17", "9/19", True, True),
    ("Flexbox 로 카드 목록 만들기", 5, 79, "19/24", "어제", "open", None, None, False, False),
    ("JavaScript 배열 다루기", 4, 54, "13/24", "10/20", "open", "10/17", "10/20", True, True),
    ("fetch 로 목록 그리기", 5, 46, "11/24", "방금", "open", "10/24", "10/27", False, False),
    ("폼 검증과 접근성", 6, 8, "2/24", "3시간 전", "open", None, "11/3", False, False),
    ("비동기 흐름과 에러 경계", 5, None, "0/24", "—", "draft", "11/7", "11/10", False, False),
    ("컴포넌트 쪼개기", 4, 0, "0/24", "—", "hidden", None, None, False, False),
]

def problem_table():
    th = lambda t, a="left", w="": f'<th style="text-align:{a};font-size:11px;letter-spacing:0.06em;color:{DIM};font-weight:400;padding:10px 12px;border-bottom:1px solid {RULE};{w}">{t}</th>'
    head = "<tr>" + th("", "left", "width:28px") + th("문제") + th("필수", "right", "white-space:nowrap;") + th("달성률") + th("통과", "right") + th("최근 제출", "right") + th("", "right") + "</tr>"
    rows = ""
    for i, (name, req, pct, passed, last, st, rec, due, prec, pdue) in enumerate(PROBLEMS, 1):
        tag = {"open": "", "hidden": " " + badge("숨김", "att"), "draft": " " + badge("초안")}[st]
        if pct is None:
            rate = f'<span style="font-size:12.5px;color:{FAINT};">아직 아무도 내지 않음</span>'
        else:
            col = ratecolor(pct)
            rate = f'<div style="display:flex;align-items:center;gap:10px;">{bar(pct, 90, col)}<span style="font-family:{MONO};font-size:13px;color:{col};font-weight:600;">{pct}%</span></div>'
        dimmed = f"color:{DIM};" if st == "draft" else ""
        cells = [
            f'<td style="padding:11px 12px;font-family:{MONO};font-size:12px;color:{FAINT};">{i}</td>',
            f'<td style="padding:11px 12px;font-size:14px;white-space:nowrap;{dimmed}">{name}{tag}{due_inline(rec, due, pdue)}</td>',
            f'<td style="padding:11px 12px;text-align:right;font-family:{MONO};font-size:13px;color:{MUTED};">{req}</td>',
            f'<td style="padding:11px 12px;">{rate}</td>',
            f'<td style="padding:11px 12px;text-align:right;font-family:{MONO};font-size:13px;color:{MUTED};">{passed}</td>',
            f'<td style="padding:11px 12px;text-align:right;font-size:12.5px;color:{DIM};white-space:nowrap;">{last}</td>',
            f'<td style="padding:11px 12px;text-align:right;white-space:nowrap;font-size:12.5px;color:{MUTED};"><span style="text-decoration:underline;text-underline-offset:3px;">편집</span><span style="text-decoration:underline;text-underline-offset:3px;margin-left:12px;">제출 현황</span><span style="margin-left:12px;">{kebab()}</span></td>',
        ]
        rows += f'<tr style="border-bottom:1px solid {RULE};">{"".join(cells)}</tr>'
    return (f'<div style="border:1px solid {RULE};border-top:none;background:{SURFACE};">'
            f'<table style="width:100%;border-collapse:collapse;">{head}{rows}</table>'
            f'<div style="padding:12px 14px;display:flex;align-items:center;gap:10px;">{btn("새 문제", primary=True, small=True)}{btn("템플릿에서 가져오기", small=True)}</div></div>')

CLASS = body(
    f'<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;">{v2.class_head(None)}{v2.class_stats()}</div>'
    + v2.join_strip() + v2.class_tabs("문제")
    + f'<div style="display:flex;gap:20px;align-items:flex-start;margin-top:-20px;">'
      f'<div style="flex:1;min-width:0;">{problem_table()}</div>'
      f'<div style="width:300px;flex-shrink:0;display:flex;flex-direction:column;gap:16px;padding-top:20px;">{v2.scoring_card()}{v2.recent_card()}</div></div>')
screen("Class", CLASS, h=1000)

# ── 3. 참여자 격자 — 머리에 마감, 칸에 「늦음」 점 ─────────────────────────────
DUE_SHORT = [None, "9/19", None, "10/20", "10/27", "11/3", "11/10", None]   # 문제 8개의 마감(격자 머리)
DUE_PASSED = [False, True, False, True, False, False, False, False]
LATE = {("서지우", 1), ("한도현", 3), ("오세아", 1), ("오세아", 3), ("배수연", 3), ("문지호", 1)}  # (이름, 문제 index) — 권장 기한 뒤 제출

def late_mark(kind):
    return (f'<span style="position:relative;display:inline-block;line-height:0;">{mark(kind)}'
            f'<span style="position:absolute;right:-4px;bottom:-4px;width:6px;height:6px;background:{INK};border:1.5px solid {SURFACE};"></span></span>')

def roster():
    th = lambda t, a="center", extra="": f'<th style="text-align:{a};padding:10px 10px;font-size:11px;color:{DIM};font-weight:400;border-bottom:1px solid {RULE};white-space:nowrap;vertical-align:bottom;{extra}">{t}</th>'
    heads = ""
    for s, d, p in zip(v2.SHORT, DUE_SHORT, DUE_PASSED):
        sub = (f'<div style="font-family:{MONO};font-size:10.5px;color:{FAINT if p else DIM};margin-top:2px;">~{d}</div>' if d else '<div style="font-size:10.5px;margin-top:2px;">&nbsp;</div>')
        heads += th(f'{s}{sub}')
    head = "<tr>" + th("참여자", "left", f"position:sticky;left:0;background:{SURFACE};letter-spacing:0.06em;padding-left:16px;") + heads + th("통과", "right") + th("최근 제출", "right") + th("", "right") + "</tr>"
    rows = ""
    for m in v2.MEMBERS:
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
        cells = ""
        for i, v in enumerate(vals):
            k = v2.KIND[v]
            m_ = late_mark(k) if (name, i) in LATE and k in ("passed", "failed") else mark(k)
            cells += f'<td style="padding:7px 10px;text-align:center;">{m_}</td>'
        rows += (f'<tr style="border-bottom:1px solid {RULE};">'
                 f'<td style="padding:7px 10px 7px 16px;font-size:13px;white-space:nowrap;position:sticky;left:0;background:{SURFACE};">{label}'
                 f'<span style="font-size:11px;color:{FAINT};margin-left:8px;">{joined} 가입</span></td>'
                 + cells
                 + f'<td style="padding:7px 10px;text-align:right;font-family:{MONO};font-size:12.5px;color:{MUTED};">{n}/8</td>'
                 f'<td style="padding:7px 10px;text-align:right;font-size:12px;color:{DIM};white-space:nowrap;">{last}</td>'
                 f'<td style="padding:7px 16px 7px 10px;text-align:right;">{action}</td></tr>')
    counted = [m for m in v2.MEMBERS if len(m) == 4]
    rates = [round(100 * sum(1 for m in counted if m[1][i] == 3) / len(counted)) for i in range(8)]
    foot = (f'<tr style="background:{PAPER};"><td style="padding:10px 16px;font-size:11px;color:{DIM};letter-spacing:0.06em;position:sticky;left:0;background:{PAPER};">달성률</td>'
            + "".join(f'<td style="padding:10px;text-align:center;font-family:{MONO};font-size:13px;font-weight:600;color:{ratecolor(p)};">{p}%</td>' for p in rates)
            + '<td></td><td></td><td></td></tr>')
    legend = "".join(f'<span style="display:inline-flex;align-items:center;gap:6px;">{m} {l}</span>'
                     for m, l in [(mark("passed", 12), "통과"), (mark("failed", 12), "시도했으나 미통과"), (mark("scoring", 12), "채점 중"),
                                  (mark("blocked", 12), "설정 필요"), (mark("none", 12), "미제출"), (late_mark("passed"), "권장 기한 뒤 제출")])
    return (f'<div style="border:1px solid {RULE};border-top:none;background:{SURFACE};">'
            f'<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">{head}{rows}{foot}</table></div>'
            f'<div style="display:flex;align-items:center;gap:20px;padding:10px 16px;border-top:1px solid {RULE};font-size:12px;color:{MUTED};">{legend}</div></div>')

ROSTER = body(
    f'<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;">{v2.class_head(None)}{v2.class_stats()}</div>'
    + v2.join_strip() + v2.class_tabs("참여자") + f'<div style="margin-top:-20px;">{roster()}</div>')
screen("Roster", ROSTER, h=940)

# ── 4. 참여자 · 문제 목록 — 줄마다 기한, 「늦음」 ─────────────────────────────
# (제목, 상태, 시도, 마지막, 권장, 마감, 권장 지남, 마감 지남, 늦음)
MINE = [("HTML 문서 구조 잡기", "passed", 1, "9/2", None, "9/12", False, True, False),
        ("CSS 선택자와 박스 모델", "passed", 2, "9/18", "9/17", "9/19", True, True, True),
        ("Flexbox 로 카드 목록 만들기", "passed", 1, "9/9", None, None, False, False, False),
        ("JavaScript 배열 다루기", "failed", 3, "10/19", "10/17", "10/20", True, True, True),
        ("fetch 로 목록 그리기", "scoring", 3, "방금", "10/24", "10/27", False, False, False),
        ("폼 검증과 접근성", "none", 0, "—", None, "11/3", False, False, False)]

def status_badge(k, late=False):
    text, tone = {"passed": ("통과", "ver"), "failed": ("미통과", "att"), "scoring": ("채점 중", "neutral"), "none": ("미제출", "neutral"), "pending": ("채점 대기", "neutral")}[k]
    return badge(text + (" · 늦음" if late else ""), tone)

def mine_row(title, k, tries, last, rec, due, prec, pdue, late):
    t = f'시도 {tries}회 · 마지막 <span style="font-family:{MONO};">{last}</span>' if tries else ""
    return (f'<div style="display:flex;align-items:center;gap:18px;padding:10px 16px;border-bottom:1px solid {RULE};">'
            f'<div style="flex:1;min-width:0;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{title}</div>'
            f'{due_cell(rec, due, pdue, prec, done=(k == "passed"))}'
            f'<div style="width:170px;flex-shrink:0;text-align:right;font-size:12px;color:{DIM};white-space:nowrap;">{t}</div>'
            f'<div style="width:96px;flex-shrink:0;text-align:right;">{status_badge(k, late)}</div></div>')

MINE_PAGE = body(
    pagehead(CLASS_NAME + " · 김선우, 박조교", "문제", None,
             actions=f'<span style="font-size:12.5px;color:{MUTED};">내 이름 <b style="color:{INK};">서지우</b> · <span style="text-decoration:underline;">바꾸기</span></span>')
    + f'<div style="display:flex;align-items:center;gap:14px;"><div style="font-family:{MONO};font-size:15px;font-weight:600;">3/6 통과</div>{bar(50, 320, VER, 8)}<span style="font-size:12px;color:{DIM};">채점 중 1 · 미제출 1</span></div>'
    + card("".join(mine_row(*r) for r in MINE))
    + f'<div style="font-size:12.5px;color:{DIM};">▸ 숨겨진 문제 1</div>')
screen("Mine", MINE_PAGE, h=760)

# ── 5. 참여자 · 제출 — 마감 전(권장 기한 지남) ─────────────────────────────
def due_strip(rec, due, rec_passed=False):
    rc = FAINT if rec_passed else MUTED
    row = lambda l, v, c: f'<div style="display:flex;justify-content:space-between;color:{c};"><span>{l}</span>{v}</div>'
    return (f'<div style="display:flex;flex-direction:column;gap:4px;padding:10px 16px;border-bottom:1px solid {RULE};font-size:12.5px;">'
            f'{row("권장 기한", when(*rec), rc)}{row("마감", when(*due), MUTED)}</div>')

def attempt(n, at, k, detail, late=False):
    b = status_badge(k, late)
    return (f'<div style="display:flex;align-items:center;gap:14px;padding:12px 16px;border-top:1px solid {RULE};">'
            f'<span style="font-family:{MONO};font-size:12.5px;color:{FAINT};width:48px;">시도 {n}</span>{b}'
            f'<span style="font-size:12.5px;color:{MUTED};flex:1;">{detail}</span><span style="font-size:11.5px;color:{FAINT};">{at}</span></div>')

def submit_card(closed=False, due=("10/27 (화)", "23:59"), rec=("10/24 (토)", "23:59"), rec_passed=False):
    if closed:
        head = f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid {RULE};"><div style="font-size:15px;font-weight:600;">제출</div>{badge("마감 지남", "att")}</div>'
        strip = f'<div style="display:flex;justify-content:space-between;padding:10px 16px;border-bottom:1px solid {RULE};font-size:12.5px;color:{MUTED};"><span>마감</span>{when(*due)}</div>'
        inner = (f'<div style="padding:16px;display:flex;flex-direction:column;gap:12px;opacity:0.45;">'
                 f'<div style="border:1px dashed {RULE};background:{PAPER};padding:22px;text-align:center;"><div style="font-size:13.5px;color:{MUTED};">소스 zip 을 끌어다 놓거나 고르기</div></div>'
                 f'<div style="border:1px solid {RULE};padding:9px 12px;font-family:{MONO};font-size:13px;color:{FAINT};">https://github.com/…</div>'
                 f'{btn("제출하기", primary=True)}</div>')
        return card(head + strip + inner)
    return card(cardhead("제출") + due_strip(rec, due, rec_passed)
        + f'<div style="padding:16px;display:flex;flex-direction:column;gap:12px;">'
          f'<div style="border:1px dashed {RULE};background:{PAPER};padding:22px;text-align:center;"><div style="font-size:13.5px;color:{MUTED};">소스 zip 을 끌어다 놓거나 <span style="color:{ATT};">고르기</span></div><div style="font-size:11.5px;color:{FAINT};margin-top:4px;">최대 50MB</div></div>'
          f'<div style="display:flex;align-items:center;gap:12px;color:{FAINT};font-size:11.5px;"><div style="height:1px;background:{RULE};flex:1;"></div>또는<div style="height:1px;background:{RULE};flex:1;"></div></div>'
          f'<div style="border:1px solid {RULE};padding:9px 12px;font-family:{MONO};font-size:13px;color:{FAINT};">https://github.com/…</div>'
          f'{btn("제출하기", primary=True)}</div>')

def submit_page(closed):
    if closed:
        title, status, verd_head, verd_badge = "JavaScript 배열 다루기", badge("아직 미통과", "att"), "시도 3 의 판정 · 10/19 · 지침 「보통」", badge("미통과 · 필수 3/4", "att")
        attempts = (attempt(3, "10/19 22:40", "failed", "필수 3/4 — 빈 배열 처리 · <span style='text-decoration:underline;'>판정 보기</span>", late=True)
                    + attempt(2, "10/18 01:12", "failed", "필수 2/4", late=True)
                    + attempt(1, "10/15 14:03", "failed", "필수 1/4"))
        desc = "배열의 map·filter·reduce 로 데이터를 다듬습니다.<br><br>빈 배열과 한 개짜리 배열에서도 같은 결과 모양이 나와야 합니다."
        progress = "3/4"
        pct = 75
    else:
        title, status, verd_head, verd_badge = "fetch 로 목록 그리기", badge("아직 미통과", "att"), "시도 2 의 판정 · 12분 전 · 지침 「보통」", badge("미통과 · 필수 3/5", "att")
        attempts = (attempt(3, "방금", "scoring", "", late=True)
                    + attempt(2, "12분 전", "failed", "필수 3/5 — 오류 화면과 빈 목록 화면 · <span style='text-decoration:underline;'>판정 보기</span>", late=True)
                    + attempt(1, "10/23 21:10", "failed", "필수 1/5"))
        desc = "공개 API 에서 목록을 받아 화면에 그립니다.<br><br>비어 있을 때와 실패했을 때를 각각 어떻게 보여줄지가 이 문제의 핵심입니다 — 성공 경로만 만들면 통과하지 못합니다."
        progress = "3/5"
        pct = 60
    verd = "".join(v2.verdict_row(*v) for v in v2.VERD) if not closed else "".join(v2.verdict_row(*v) for v in v2.VERD[:5])
    prog = card(f'<div style="padding:14px 16px;"><div style="font-size:12px;color:{MUTED};margin-bottom:8px;">이 문제의 진행</div>'
                f'<div style="display:flex;align-items:center;gap:10px;">{bar(pct, 200, INK)}<span style="font-family:{MONO};font-size:13px;font-weight:600;">{progress}</span></div></div>')
    return body(
        pagehead(CLASS_NAME + " › 문제", title, actions=btn("문제 목록으로", small=True), extra=status)
        + f'<div style="display:flex;gap:20px;align-items:flex-start;">'
          f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:18px;">'
          + card(cardhead("설명") + f'<div style="padding:14px 16px;font-size:13.5px;line-height:1.7;">{desc}</div>')
          + card(f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;">'
                 f'<div style="font-size:15px;font-weight:600;">체크리스트 <span style="font-size:12.5px;color:{DIM};font-weight:400;margin-left:10px;">{verd_head}</span></div>{verd_badge}</div>'
                 + verd + f'<div style="padding:10px 16px;border-top:1px solid {RULE};font-size:11.5px;color:{FAINT};">gpt-5</div>')
          + card(cardhead("내 시도", "3회") + attempts)
          + '</div>'
          f'<div style="width:360px;flex-shrink:0;position:sticky;top:24px;display:flex;flex-direction:column;gap:14px;">'
          + (submit_card(closed=True, due=("10/20 (월)", "23:59")) if closed else submit_card(rec_passed=False))
          + prog + '</div></div>')

screen("Submit", submit_page(False), h=1000)
screen("SubmitClosed", submit_page(True), h=1000)

if __name__ == "__main__":
    for name, (inner, h, w) in SCREENS.items():
        write(f"{name}.dc.html", header() + inner, h=h, w=w)
