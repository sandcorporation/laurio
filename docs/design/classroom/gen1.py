# -*- coding: utf-8 -*-
from _lib import *

def crumb():
    return f'<div style="font-size: 11px; letter-spacing: 0.08em; color: {DIM};">내 클래스 · 프론트엔드 입문</div>'

def classtitle(sub):
    return (f'<div style="display: flex; align-items: flex-end; justify-content: space-between; gap: 24px;">'
            f'<div style="display: flex; flex-direction: column; gap: 6px;">{crumb()}'
            f'<div style="display: flex; align-items: center; gap: 12px;">'
            f'<div style="font-size: 22px; font-weight: 600; letter-spacing: -0.01em;">프론트엔드 입문 3기</div>'
            f'<div style="border: 1px solid {VER}; color: {VER}; font-size: 11px; padding: 2px 8px;">진행중</div></div>'
            f'<div style="font-size: 13px; color: {MUTED};">{sub}</div></div>'
            f'{statbar([("참여자","24",None),("문제","8",None),("평균 달성률","61%",None)])}</div>')

def invite():
    return (f'<div style="border: 1px solid {RULE}; background: {SURFACE}; display: flex; align-items: center; '
            f'justify-content: space-between; padding: 13px 18px; gap: 20px;">'
            f'<div style="display: flex; align-items: center; gap: 16px; min-width: 0;">'
            f'<div style="font-size: 12px; color: {DIM}; letter-spacing: 0.06em; white-space: nowrap;">가입 링크</div>'
            f'<div style="font-family: {MONO}; font-size: 13.5px; color: {INK}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">edu.laurio.kr/join/fe3-8kq2mx</div></div>'
            f'<div style="display: flex; align-items: center; gap: 12px;">'
            f'<div style="font-size: 12px; color: {DIM};">이 링크로 들어오면 회원가입과 클래스 가입이 한 번에 끝납니다</div>'
            f'{btn("복사", small=True)}{btn("새 링크", small=True)}</div></div>')

def tabs(active):
    out = ""
    for t in ["문제", "참여자", "설정"]:
        if t == active:
            out += (f'<div style="padding: 9px 18px; border: 1px solid {RULE}; border-bottom: 1px solid {SURFACE}; '
                    f'background: {SURFACE}; font-size: 13.5px; font-weight: 500; margin-bottom: -1px;">{t}</div>')
        else:
            out += f'<div style="padding: 9px 18px; font-size: 13.5px; color: {MUTED};">{t}</div>'
    return (f'<div style="display: flex; align-items: flex-end; border-bottom: 1px solid {RULE}; gap: 2px;">{out}</div>')

PROBLEMS = [
    ("HTML 문서 구조 잡기", 3, 92, "22/24", "3분 전", False),
    ("CSS 선택자와 박스 모델", 4, 79, "19/24", "21분 전", False),
    ("Flexbox 로 카드 목록 만들기", 4, 67, "16/24", "1시간 전", False),
    ("JavaScript 배열 다루기", 5, 54, "13/24", "2시간 전", False),
    ("fetch 로 목록 그리기", 5, 46, "11/24", "어제", False),
    ("상태를 컴포넌트로 나누기", 4, 25, "6/24", "어제", False),
    ("폼 검증과 접근성", 6, 12, "3/24", "3일 전", False),
    ("배포와 환경변수", 3, 0, "0/24", "—", True),
]

def problem_table():
    head = ("<tr>" + "".join(
        f'<th style="text-align: {a}; font-size: 11px; letter-spacing: 0.06em; color: {DIM}; font-weight: 400; '
        f'padding: 11px 14px; border-bottom: 1px solid {RULE};">{t}</th>'
        for t, a in [("", "left"), ("문제", "left"), ("필수 항목", "right"), ("달성률", "left"),
                     ("통과", "right"), ("최근 제출", "right"), ("", "right")]) + "</tr>")
    rows = ""
    for i, (name, req, pct, passed, when, draft) in enumerate(PROBLEMS, 1):
        col = VER if pct >= 60 else (ATT if pct < 30 else INK)
        tag = (f'<span style="border: 1px solid {RULE}; color: {DIM}; font-size: 10.5px; padding: 1px 6px; margin-left: 8px;">초안</span>'
               if draft else "")
        cells = [
            f'<td style="padding: 12px 14px; font-family: {MONO}; font-size: 12.5px; color: {FAINT};">{i}</td>',
            f'<td style="padding: 12px 14px; font-size: 14px;">{name}{tag}</td>',
            f'<td style="padding: 12px 14px; text-align: right; font-family: {MONO}; font-size: 13px; color: {MUTED};">{req}</td>',
            (f'<td style="padding: 12px 14px;"><div style="display: flex; align-items: center; gap: 10px;">'
             f'{bar(pct, 110, col)}<span style="font-family: {MONO}; font-size: 13px; color: {col}; font-weight: 600;">{pct}%</span></div></td>'),
            f'<td style="padding: 12px 14px; text-align: right; font-family: {MONO}; font-size: 13px; color: {MUTED};">{passed}</td>',
            f'<td style="padding: 12px 14px; text-align: right; font-size: 12.5px; color: {DIM};">{when}</td>',
            f'<td style="padding: 12px 14px; text-align: right; font-size: 12.5px; color: {MUTED};">편집 · 복사</td>',
        ]
        rows += f'<tr style="border-bottom: 1px solid {RULE};">{"".join(cells)}</tr>'
    return (f'<div style="border: 1px solid {RULE}; border-top: none; background: {SURFACE};">'
            f'<table style="width: 100%; border-collapse: collapse;">{head}{rows}</table>'
            f'<div style="padding: 14px; display: flex; gap: 10px;">{btn("문제 추가", primary=True, small=True)}'
            f'{btn("다른 클래스에서 복사", small=True)}</div></div>')

def grading_panel():
    recent = [("서지우", "JavaScript 배열 다루기", True, "3분 전"),
              ("한도현", "Flexbox 로 카드 목록", False, "9분 전"),
              ("최민재", "CSS 선택자와 박스 모델", True, "12분 전"),
              ("오세아", "JavaScript 배열 다루기", False, "18분 전")]
    items = ""
    for n, p, ok, w in recent:
        mark = (f'<span style="color: {VER}; font-size: 12px;">통과</span>' if ok
                else f'<span style="color: {MUTED}; font-size: 12px;">미통과</span>')
        items += (f'<div style="padding: 11px 16px; border-top: 1px solid {RULE}; display: flex; '
                  f'justify-content: space-between; align-items: baseline; gap: 10px;">'
                  f'<div style="min-width: 0;"><div style="font-size: 13px;">{n}</div>'
                  f'<div style="font-size: 11.5px; color: {DIM}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{p}</div></div>'
                  f'<div style="text-align: right; white-space: nowrap;">{mark}'
                  f'<div style="font-size: 11px; color: {FAINT};">{w}</div></div></div>')
    return (f'<div style="width: 320px; display: flex; flex-direction: column; gap: 16px; flex-shrink: 0;">'
            f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
            f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("채점")}</div>'
            f'<div style="padding: 14px 16px; display: flex; flex-direction: column; gap: 13px;">'
            f'<div style="display: flex; justify-content: space-between; font-size: 13px;">'
            f'<span style="color: {MUTED};">모델</span><span style="font-family: {MONO};">gpt-5-mini</span></div>'
            f'<div style="display: flex; justify-content: space-between; font-size: 13px;">'
            f'<span style="color: {MUTED};">이번 달 채점</span><span style="font-family: {MONO};">412회</span></div>'
            f'<div style="display: flex; flex-direction: column; gap: 7px;">'
            f'<div style="display: flex; justify-content: space-between; font-size: 13px;">'
            f'<span style="color: {MUTED};">토큰 예산</span>'
            f'<span style="font-family: {MONO}; color: {INK};">78%</span></div>{bar(78, 288, INK)}'
            f'<div style="font-size: 11.5px; color: {DIM}; line-height: 1.55;">85% 에 닿으면 알림이 오고, 100% 에서 채점이 멈춥니다 — 이미 쌓인 제출은 예산을 채우면 그대로 이어서 채점됩니다.</div>'
            f'</div></div></div>'
            f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
            f'<div style="padding: 14px 16px 12px;">{sectiontitle("최근 채점", "마감이 없어 제출 즉시 돕니다")}</div>{items}</div>'
            f'</div>')

MAIN = body(classtitle("초대 링크로 24명이 들어왔고, 문제 8개 중 7개가 열려 있습니다.")
            + invite() + tabs("문제")
            + f'<div style="display: flex; gap: 20px; align-items: flex-start;">'
              f'<div style="flex: 1; min-width: 0; margin-top: -20px;">{problem_table()}</div>'
              f'{grading_panel()}</div>')
write("Main.dc.html", header() + MAIN, h=1020)

# ── Roster: 사람 중심 격자 ────────────────────────────────────────────────
MEMBERS = [
    ("서지우", [3,3,3,2,1,1,0,0]), ("한도현", [3,3,2,2,1,0,0,0]), ("최민재", [3,3,3,3,2,1,1,0]),
    ("오세아", [3,3,3,1,1,0,0,0]), ("배수연", [3,3,3,3,3,2,1,0]), ("문지호", [3,2,1,0,0,0,0,0]),
    ("서아린", [3,3,3,3,2,1,0,0]), ("남기훈", [2,1,0,0,0,0,0,0]), ("조은비", [3,3,3,2,2,1,0,0]),
    ("윤태경", [3,3,2,1,1,0,0,0]), ("강시우", [3,3,3,3,3,3,2,0]), ("임도윤", [3,3,3,3,2,1,1,0]),
    ("신유하", [3,2,1,1,0,0,0,0]), ("허준",   [3,3,3,2,1,1,0,0]), ("정유진", [3,3,2,2,1,0,0,0]),
    ("김하늘", [1,0,0,0,0,0,0,0]), ("이준서", [3,3,3,3,3,2,1,0]), ("박도현", [3,3,3,1,1,0,0,0]),
    ("한서율", [3,3,2,2,2,1,0,0]), ("유진",   [3,3,3,3,1,0,0,0]), ("노아름", [3,2,2,1,0,0,0,0]),
    ("천예린", [3,3,3,2,2,1,0,0]), ("백승호", [2,2,1,0,0,0,0,0]), ("고은서", [3,3,3,3,2,1,0,0]),
]
# 3 = 통과, 2 = 시도했으나 미통과, 1 = 채점 중, 0 = 미제출
SHORT = ["HTML 구조", "CSS 박스", "Flexbox", "JS 배열", "fetch", "컴포넌트", "폼 검증", "배포"]

def cell(v):
    if v == 3:
        return f'<div style="width: 15px; height: 15px; background: {VER}; margin: 0 auto;"></div>'
    if v == 2:
        return f'<div style="width: 15px; height: 15px; border: 1px solid {ATT}; margin: 0 auto;"></div>'
    if v == 1:
        return (f'<div style="width: 15px; height: 15px; border: 1px solid {RULE}; margin: 0 auto; '
                f'background: repeating-linear-gradient(45deg, {RULE} 0 2px, {SURFACE} 2px 4px);"></div>')
    return f'<div style="width: 5px; height: 5px; background: {FAINT}; margin: 5px auto;"></div>'

def roster_grid():
    head = (f'<tr><th style="text-align: left; padding: 10px 14px; font-size: 11px; letter-spacing: 0.06em; '
            f'color: {DIM}; font-weight: 400; border-bottom: 1px solid {RULE}; position: sticky; left: 0; background: {SURFACE};">참여자</th>'
            + "".join(f'<th style="padding: 10px 6px; font-size: 11px; color: {DIM}; font-weight: 400; '
                      f'border-bottom: 1px solid {RULE}; width: 92px;">{s}</th>' for s in SHORT)
            + f'<th style="padding: 10px 14px; font-size: 11px; letter-spacing: 0.06em; color: {DIM}; font-weight: 400; '
              f'border-bottom: 1px solid {RULE}; text-align: right;">통과</th></tr>')
    rows = ""
    for name, vals in MEMBERS:
        n = sum(1 for v in vals if v == 3)
        rows += (f'<tr style="border-bottom: 1px solid {RULE};">'
                 f'<td style="padding: 7px 14px; font-size: 13px; white-space: nowrap;">{name}</td>'
                 + "".join(f'<td style="padding: 7px 6px;">{cell(v)}</td>' for v in vals)
                 + f'<td style="padding: 7px 14px; text-align: right; font-family: {MONO}; font-size: 12.5px; '
                   f'color: {MUTED};">{n}/8</td></tr>')
    rates = []
    for i in range(8):
        p = round(100 * sum(1 for _, v in MEMBERS if v[i] == 3) / len(MEMBERS))
        rates.append(p)
    foot = (f'<tr style="background: {PAPER};">'
            f'<td style="padding: 11px 14px; font-size: 12px; color: {DIM}; letter-spacing: 0.06em;">달성률</td>'
            + "".join(f'<td style="padding: 11px 6px; text-align: center; font-family: {MONO}; font-size: 13px; '
                      f'font-weight: 600; color: {VER if p >= 60 else (ATT if p < 30 else INK)};">{p}%</td>' for p in rates)
            + f'<td></td></tr>')
    return (f'<div style="border: 1px solid {RULE}; border-top: none; background: {SURFACE};">'
            f'<table style="width: 100%; border-collapse: collapse;">{head}{rows}{foot}</table></div>')

legend = (f'<div style="display: flex; align-items: center; gap: 22px; font-size: 12px; color: {MUTED};">'
          f'<div style="display: flex; align-items: center; gap: 7px;"><div style="width: 12px; height: 12px; background: {VER};"></div>통과</div>'
          f'<div style="display: flex; align-items: center; gap: 7px;"><div style="width: 12px; height: 12px; border: 1px solid {ATT};"></div>시도했으나 미통과</div>'
          f'<div style="display: flex; align-items: center; gap: 7px;"><div style="width: 12px; height: 12px; border: 1px solid {RULE}; background: repeating-linear-gradient(45deg, {RULE} 0 2px, {SURFACE} 2px 4px);"></div>채점 중</div>'
          f'<div style="display: flex; align-items: center; gap: 7px;"><div style="width: 5px; height: 5px; background: {FAINT};"></div>미제출</div>'
          f'<div style="margin-left: auto; color: {DIM};">강사 본인이 들어와도 이 표와 달성률에서는 빠집니다</div></div>')

ROSTER = body(classtitle("한 사람이 어디서 막혔는지를 세로로 읽습니다 — 달성률만으로는 안 보이는 것.")
              + invite() + tabs("참여자")
              + f'<div style="margin-top: -20px; display: flex; flex-direction: column; gap: 14px;">'
                f'{roster_grid()}{legend}'
                f'{note("<b>이 격자는 문제 12개까지 가로 스크롤 없이 들어갑니다</b> — 심사 비교 화면에서 재 봤던 것과 같은 한계입니다. 그보다 많아지면 열을 접고 「최근 4개 + 전체 보기」로 갑니다. 세로는 참여자 수만큼 늘어나되 이름 열이 고정됩니다.")}</div>')
write("Roster.dc.html", header() + ROSTER, h=1180)
