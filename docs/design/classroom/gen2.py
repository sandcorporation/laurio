# -*- coding: utf-8 -*-
from _lib import *

# ── Classes: 강사의 클래스 목록 ──────────────────────────────────────────
LIVE = [("프론트엔드 입문 3기", "24", "8", 61, "3분 전"),
        ("파이썬 기초 · 사내 2기", "17", "12", 84, "1시간 전"),
        ("백엔드 스터디 (야간)", "9", "5", 38, "어제")]
ARCHIVED = [("프론트엔드 입문 2기", "22", "8", 73, "3개월 전"),
            ("프론트엔드 입문 1기", "16", "6", 68, "8개월 전")]

def class_row(name, members, problems, pct, when, archived=False):
    c = FAINT if archived else INK
    col = VER if pct >= 60 else (ATT if pct < 30 else INK)
    action = (btn("복사해서 새 기수 열기", primary=True, small=True) if archived
              else f'<div style="display: flex; gap: 8px;">{btn("복사", small=True)}{btn("보관", small=True)}</div>')
    return (f'<div style="border-bottom: 1px solid {RULE}; padding: 16px 18px; display: flex; align-items: center; gap: 24px;">'
            f'<div style="flex: 1; min-width: 0;">'
            f'<div style="font-size: 15px; color: {c}; font-weight: 500;">{name}</div>'
            f'<div style="font-size: 12px; color: {DIM}; margin-top: 4px;">참여자 {members}명 · 문제 {problems}개 · 마지막 활동 {when}</div></div>'
            f'<div style="display: flex; align-items: center; gap: 11px; width: 200px;">{bar(pct, 120, col if not archived else FAINT)}'
            f'<span style="font-family: {MONO}; font-size: 13px; color: {col if not archived else FAINT}; font-weight: 600;">{pct}%</span>'
            f'<span style="font-size: 11px; color: {FAINT};">평균 달성률</span></div>'
            f'{action}</div>')

CLASSES = body(
    f'<div style="display: flex; align-items: flex-end; justify-content: space-between;">'
    f'<div style="display: flex; flex-direction: column; gap: 6px;">'
    f'<div style="font-size: 11px; letter-spacing: 0.08em; color: {DIM};">강의실</div>'
    f'<div style="font-size: 22px; font-weight: 600; letter-spacing: -0.01em;">내 클래스</div>'
    f'<div style="font-size: 13px; color: {MUTED};">클래스마다 문제와 참여자가 따로 삽니다. 지난 기수를 복사하면 문제와 체크리스트가 그대로 따라옵니다.</div></div>'
    f'{btn("새 클래스 열기", primary=True)}</div>'
    + f'<div style="display: flex; flex-direction: column; gap: 10px;">{sectiontitle("진행중", "3")}'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      + "".join(class_row(*c) for c in LIVE) + '</div></div>'
    + f'<div style="display: flex; flex-direction: column; gap: 10px;">{sectiontitle("보관", "새 가입과 새 제출은 닫혔고 읽기는 남습니다")}'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      + "".join(class_row(*c, archived=True) for c in ARCHIVED) + '</div></div>'
    + note("<b>복사는 문제·체크리스트·채점 설정만 가져옵니다</b> — 참여자와 제출물과 점수는 따라오지 않습니다. 지난 기수의 달성률은 그 기수에 그대로 남습니다."))
write("Classes.dc.html", header(active="내 클래스") + CLASSES, h=900)

# ── Problem: 문제 편집 ───────────────────────────────────────────────────
REQS = [("fetch 로 목록 데이터를 받아온다", True), ("로딩 중 상태를 화면에 표시한다", True),
        ("요청이 실패하면 오류 문구를 보여준다", True), ("목록이 비어 있을 때의 화면이 따로 있다", True),
        ("각 항목에 고유한 key 가 있다", True),
        ("요청을 취소할 수 있다", False), ("재시도 버튼이 있다", False)]

def req_row(text, required, i):
    tag = (f'<span style="border: 1px solid {ATT}; color: {ATT}; font-size: 10.5px; padding: 1px 7px;">필수</span>'
           if required else f'<span style="border: 1px solid {RULE}; color: {DIM}; font-size: 10.5px; padding: 1px 7px;">선택</span>')
    return (f'<div style="display: flex; align-items: center; gap: 12px; padding: 11px 14px; border-bottom: 1px solid {RULE};">'
            f'<div style="font-family: {MONO}; font-size: 11.5px; color: {FAINT}; width: 14px;">{i}</div>'
            f'<div style="flex: 1; font-size: 13.5px; line-height: 1.5;">{text}</div>{tag}'
            f'<div style="color: {FAINT}; font-size: 13px;">⋮⋮</div></div>')

def field(label, value, mono=False, hint=None, h=None):
    ff = f"font-family: {MONO};" if mono else ""
    box = (f'<div style="border: 1px solid {RULE}; background: {SURFACE}; padding: 11px 13px; font-size: 13.5px; '
           f'{ff} line-height: 1.6; {"min-height: " + str(h) + "px;" if h else ""}">{value}</div>')
    hintline = f'<div style="font-size: 11.5px; color: {DIM}; line-height: 1.5;">{hint}</div>' if hint else ""
    return (f'<div style="display: flex; flex-direction: column; gap: 7px;">'
            f'<div style="font-size: 12px; color: {MUTED};">{label}</div>{box}{hintline}</div>')

def radio(label, checked, hint=None):
    dot = (f'<div style="width: 13px; height: 13px; border: 1px solid {INK}; display: flex; align-items: center; justify-content: center;">'
           f'<div style="width: 7px; height: 7px; background: {INK};"></div></div>' if checked else
           f'<div style="width: 13px; height: 13px; border: 1px solid {RULE};"></div>')
    h = f'<div style="font-size: 11.5px; color: {DIM}; margin-top: 3px; line-height: 1.5;">{hint}</div>' if hint else ""
    return (f'<div style="display: flex; gap: 10px; align-items: flex-start; padding: 9px 0;">{dot}'
            f'<div><div style="font-size: 13.5px;">{label}</div>{h}</div></div>')

PROBLEM = body(
    f'<div style="display: flex; align-items: flex-end; justify-content: space-between;">'
    f'<div style="display: flex; flex-direction: column; gap: 6px;">'
    f'<div style="font-size: 11px; letter-spacing: 0.08em; color: {DIM};">프론트엔드 입문 3기 · 문제 5</div>'
    f'<div style="font-size: 22px; font-weight: 600;">fetch 로 목록 그리기</div></div>'
    f'<div style="display: flex; gap: 8px;">{btn("다른 클래스로 복사", small=True)}{btn("저장", primary=True, small=True)}</div></div>'
    + note("<b>이미 11명이 통과했습니다.</b> 체크리스트를 고쳐도 지난 점수는 그대로 남고, 달성률만 새 기준으로 다시 셈됩니다 — 돈이 걸려 있지 않아 「나중에 낸 사람이 유리해진다」가 성립하지 않습니다.", tone="att")
    + f'<div style="display: flex; gap: 20px; align-items: flex-start;">'
      f'<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 18px;">'
      + field("제목", "fetch 로 목록 그리기")
      + field("설명", "공개 API 에서 목록을 받아 화면에 그립니다.<br><br>비어 있을 때와 실패했을 때를 각각 어떻게 보여줄지가 이 문제의 핵심입니다 — 성공 경로만 만들면 통과하지 못합니다.", h=150)
      + f'<div style="display: flex; flex-direction: column; gap: 4px;">'
        f'<div style="font-size: 12px; color: {MUTED};">제출 형식</div>'
        + radio("소스 파일", False, "zip 으로 올립니다")
        + radio("GitHub 저장소", False, "공개 저장소 주소만 받습니다")
        + radio("둘 중 아무거나", True, "참여자가 고릅니다 — 근거 연결도 자가 체크도 없습니다. 채점이 소스에서 직접 판정합니다.")
      + f'</div></div>'
      f'<div style="width: 460px; flex-shrink: 0; display: flex; flex-direction: column; gap: 18px;">'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("체크리스트", "필수를 전부 충족하면 「통과」")}</div>'
      + "".join(req_row(t, r, i) for i, (t, r) in enumerate(REQS, 1))
      + f'<div style="padding: 13px 14px;">{btn("항목 추가", small=True)}</div></div>'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("채점 모델")}</div>'
      f'<div style="padding: 6px 16px 14px;">'
      + radio("클래스 기본값을 따른다 — gpt-5-mini", False)
      + radio("이 문제만 gpt-5", True, "소스가 길어 기본 모델의 컨텍스트에 다 안 들어갑니다. 모델마다 받을 수 있는 양이 다르므로 문제별로 정할 수 있습니다.")
      + f'</div></div></div></div>')
write("Problem.dc.html", header(active="내 클래스") + PROBLEM, h=1020)
