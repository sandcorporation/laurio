# -*- coding: utf-8 -*-
from _lib import *

# ── Learner: 참여자의 문제 화면 ──────────────────────────────────────────
def lheader(active="문제"):
    tabs = ["문제", "내 제출", "알림"]
    items = "".join(
        f'<div style="color: {INK}; font-weight: 500; border-bottom: 2px solid {ATT}; padding-bottom: 3px;">{t}</div>'
        if t == active else f'<div>{t}</div>' for t in tabs)
    return (f'<div style="height: 72px; border-bottom: 1px solid {RULE}; display: flex; align-items: center; '
            f'justify-content: space-between; padding: 0 40px; background: {SURFACE}; flex-shrink: 0;">'
            f'<div style="display: flex; align-items: center; gap: 40px;">'
            f'<div style="font-size: 21px; font-weight: 700;">Laurio <span style="font-weight:400;color:{DIM};font-size:15px;">강의실</span></div>'
            f'<div style="display: flex; gap: 26px; font-size: 14px; color: {MUTED};">{items}</div></div>'
            f'<div style="font-size: 13px; color: {MUTED};">프론트엔드 입문 3기 · 서지우</div></div>')

REQS = [("fetch 로 목록 데이터를 받아온다", True, True),
        ("로딩 중 상태를 화면에 표시한다", True, True),
        ("요청이 실패하면 오류 문구를 보여준다", True, False),
        ("목록이 비어 있을 때의 화면이 따로 있다", True, False),
        ("각 항목에 고유한 key 가 있다", True, True),
        ("요청을 취소할 수 있다", False, False),
        ("재시도 버튼이 있다", False, False)]

def verdict_row(text, required, met, reason=None):
    if met:
        mark = f'<div style="width: 15px; height: 15px; background: {VER}; flex-shrink: 0; margin-top: 2px;"></div>'
    elif required:
        mark = f'<div style="width: 15px; height: 15px; border: 1px solid {ATT}; flex-shrink: 0; margin-top: 2px;"></div>'
    else:
        mark = f'<div style="width: 15px; height: 15px; border: 1px solid {RULE}; flex-shrink: 0; margin-top: 2px;"></div>'
    tag = ('' if required else
           f'<span style="border: 1px solid {RULE}; color: {DIM}; font-size: 10.5px; padding: 1px 7px; margin-left: 8px;">선택</span>')
    r = (f'<div style="font-size: 12.5px; color: {MUTED}; line-height: 1.65; margin-top: 5px;">{reason}</div>' if reason else "")
    return (f'<div style="display: flex; gap: 12px; padding: 12px 16px; border-bottom: 1px solid {RULE};">{mark}'
            f'<div style="flex: 1;"><div style="font-size: 13.5px; line-height: 1.5;">{text}{tag}</div>{r}</div></div>')

def attempt(n, when, state, detail=""):
    if state == "grading":
        badge = (f'<span style="border: 1px solid {RULE}; color: {MUTED}; font-size: 11.5px; padding: 2px 9px;">채점 중</span>')
    elif state == "pass":
        badge = f'<span style="background: {VER}; color: {PAPER}; font-size: 11.5px; padding: 2px 9px;">통과</span>'
    else:
        badge = f'<span style="border: 1px solid {ATT}; color: {ATT}; font-size: 11.5px; padding: 2px 9px;">미통과</span>'
    return (f'<div style="display: flex; align-items: center; gap: 14px; padding: 13px 16px; border-bottom: 1px solid {RULE};">'
            f'<div style="font-family: {MONO}; font-size: 12.5px; color: {FAINT}; width: 52px;">시도 {n}</div>'
            f'{badge}<div style="font-size: 12.5px; color: {MUTED}; flex: 1;">{detail}</div>'
            f'<div style="font-size: 11.5px; color: {FAINT};">{when}</div></div>')

submit_card = (
    f'<div style="width: 380px; flex-shrink: 0; display: flex; flex-direction: column; gap: 16px;">'
    f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
    f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("제출")}</div>'
    f'<div style="padding: 16px; display: flex; flex-direction: column; gap: 14px;">'
    f'<div style="border: 1px dashed {RULE}; background: {PAPER}; padding: 26px; text-align: center;">'
    f'<div style="font-size: 13.5px; color: {MUTED};">소스 zip 을 끌어다 놓거나 <span style="color: {ATT};">고르기</span></div>'
    f'<div style="font-size: 11.5px; color: {FAINT}; margin-top: 6px;">최대 50MB</div></div>'
    f'<div style="display: flex; align-items: center; gap: 12px; color: {FAINT}; font-size: 11.5px;">'
    f'<div style="height: 1px; background: {RULE}; flex: 1;"></div>또는<div style="height: 1px; background: {RULE}; flex: 1;"></div></div>'
    f'<div style="border: 1px solid {RULE}; padding: 11px 13px; font-family: {MONO}; font-size: 13px; color: {FAINT};">https://github.com/…</div>'
    f'{btn("제출하기", primary=True)}'
    f'<div style="font-size: 11.5px; color: {DIM}; line-height: 1.6;"><b style="color: {INK};">마감이 없습니다.</b> 몇 번이든 다시 낼 수 있고, 낼 때마다 바로 채점이 시작됩니다. 한 번이라도 통과하면 통과로 셉니다 — 고치다 깨져도 사라지지 않습니다.</div>'
    f'</div></div>'
    f'<div style="border: 1px solid {RULE}; background: {SURFACE}; padding: 14px 16px;">'
    f'<div style="font-size: 12px; color: {MUTED}; margin-bottom: 9px;">이 문제의 진행</div>'
    f'<div style="display: flex; align-items: center; gap: 11px;">{bar(46, 210, INK)}'
    f'<span style="font-family: {MONO}; font-size: 13px; font-weight: 600;">3/5</span></div>'
    f'<div style="font-size: 11.5px; color: {FAINT}; margin-top: 8px;">필수 5개 중 3개 충족 — 전부 충족하면 통과입니다.</div></div></div>')

LEARNER = body(
    f'<div style="display: flex; flex-direction: column; gap: 6px;">'
    f'<div style="font-size: 11px; letter-spacing: 0.08em; color: {DIM};">프론트엔드 입문 3기 · 문제 5</div>'
    f'<div style="font-size: 22px; font-weight: 600;">fetch 로 목록 그리기</div>'
    f'<div style="font-size: 13px; color: {MUTED};">공개 API 에서 목록을 받아 화면에 그립니다. 비어 있을 때와 실패했을 때를 각각 어떻게 보여줄지가 이 문제의 핵심입니다 — 성공 경로만 만들면 통과하지 못합니다.</div></div>'
    + f'<div style="display: flex; gap: 20px; align-items: flex-start;">'
      f'<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 18px;">'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE}; display: flex; align-items: baseline; justify-content: space-between;">'
      f'{sectiontitle("가장 최근 채점", "시도 2 · 12분 전")}'
      f'<span style="border: 1px solid {ATT}; color: {ATT}; font-size: 11.5px; padding: 2px 9px;">미통과 · 필수 3/5</span></div>'
      + verdict_row(REQS[0][0], True, True)
      + verdict_row(REQS[1][0], True, True)
      + verdict_row(REQS[2][0], True, False, "요청이 실패해도 화면이 로딩 상태 그대로 멈춥니다. catch 블록이 콘솔에만 남기고 화면에는 아무것도 바꾸지 않습니다.")
      + verdict_row(REQS[3][0], True, False, "목록이 빈 배열일 때 아무것도 그리지 않아 화면이 비어 보입니다 — 「아직 없습니다」 같은 안내가 필요합니다.")
      + verdict_row(REQS[4][0], True, True)
      + verdict_row(REQS[5][0], False, False)
      + verdict_row(REQS[6][0], False, False)
      + f'<div style="padding: 13px 16px; font-size: 11.5px; color: {FAINT}; line-height: 1.6;">gpt-5 · 12분 전 · 이 판정은 제출한 소스만 보고 내려졌습니다.</div></div>'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("내 시도", "3")}</div>'
      + attempt(3, "방금", "grading", "제출 직후 바로 채점에 들어갔습니다 — 보통 1~2분")
      + attempt(2, "12분 전", "fail", "필수 3/5 — 오류 화면과 빈 목록 화면")
      + attempt(1, "1시간 전", "fail", "필수 1/5")
      + f'</div></div>{submit_card}</div>')
write("Learner.dc.html", lheader() + LEARNER, h=1080)

# ── Join: 가입 링크 (모바일) ────────────────────────────────────────────
JOIN = (f'<div style="padding: 0 24px; display: flex; flex-direction: column; gap: 22px; flex: 1;">'
        f'<div style="padding-top: 44px; display: flex; flex-direction: column; gap: 7px;">'
        f'<div style="font-size: 19px; font-weight: 700;">Laurio <span style="font-weight:400;color:{DIM};font-size:14px;">강의실</span></div>'
        f'<div style="font-size: 11px; letter-spacing: 0.08em; color: {DIM}; margin-top: 14px;">초대받은 클래스</div>'
        f'<div style="font-size: 21px; font-weight: 600; line-height: 1.35;">프론트엔드 입문 3기</div>'
        f'<div style="font-size: 13px; color: {MUTED};">강사 김선우 · 문제 8개 · 참여자 24명</div></div>'
        f'<div style="border: 1px solid {RULE}; background: {SURFACE}; padding: 16px; display: flex; flex-direction: column; gap: 8px;">'
        f'<div style="font-size: 12px; color: {MUTED};">이 클래스에서 불릴 이름</div>'
        f'<div style="border: 1px solid {RULE}; padding: 11px 12px; font-size: 14px;">서지우</div>'
        f'<div style="font-size: 11.5px; color: {DIM}; line-height: 1.6;">계정 이름과 달라도 됩니다 — 회사 수업과 스터디에서 다른 이름을 쓸 수 있습니다.</div></div>'
        f'<div style="display: flex; flex-direction: column; gap: 10px;">'
        f'<div style="background: #FEE500; color: #191600; padding: 14px; text-align: center; font-size: 14.5px; font-weight: 500;">카카오로 시작하기</div>'
        f'<div style="border: 1px solid {RULE}; background: {SURFACE}; padding: 14px; text-align: center; font-size: 14.5px;">이메일로 가입</div>'
        f'<div style="font-size: 12px; color: {DIM}; text-align: center; line-height: 1.7; margin-top: 4px;">'
        f'가입과 동시에 이 클래스에 들어갑니다.<br>본인확인도 결제도 없습니다.</div></div>'
        f'<div style="margin-top: auto; padding-bottom: 30px; border-top: 1px solid {RULE}; padding-top: 16px;">'
        f'<div style="font-size: 11.5px; color: {FAINT}; line-height: 1.7;">이미 계정이 있다면 로그인만 하면 클래스에 들어갑니다. 한 계정으로 여러 클래스에 들어갈 수 있습니다.</div></div>'
        f'</div>')
write("Join.dc.html", JOIN, h=844, w=390)
