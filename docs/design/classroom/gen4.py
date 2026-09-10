# -*- coding: utf-8 -*-
from _lib import *
from gen1 import tabs, classtitle, invite

MODELS = [("gpt-5-mini", "400K", "저렴", True, "클래스 기본값"),
          ("gpt-5", "400K", "보통", False, "소스가 긴 문제에 쓰입니다"),
          ("gpt-5-nano", "128K", "가장 저렴", False, "짧은 문제만 — 긴 소스는 잘립니다")]

def model_row(name, ctx, cost, chosen, hint):
    dot = (f'<div style="width: 13px; height: 13px; border: 1px solid {INK}; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">'
           f'<div style="width: 7px; height: 7px; background: {INK};"></div></div>' if chosen else
           f'<div style="width: 13px; height: 13px; border: 1px solid {RULE}; flex-shrink: 0;"></div>')
    return (f'<div style="display: flex; align-items: center; gap: 12px; padding: 13px 16px; border-bottom: 1px solid {RULE};">{dot}'
            f'<div style="flex: 1;"><div style="font-family: {MONO}; font-size: 13.5px;">{name}</div>'
            f'<div style="font-size: 11.5px; color: {DIM}; margin-top: 3px;">{hint}</div></div>'
            f'<div style="text-align: right; width: 110px;"><div style="font-family: {MONO}; font-size: 12.5px; color: {MUTED};">{ctx}</div>'
            f'<div style="font-size: 11px; color: {FAINT};">컨텍스트</div></div>'
            f'<div style="text-align: right; width: 80px; font-size: 12.5px; color: {MUTED};">{cost}</div></div>')

halted_preview = (
    f'<div style="border: 1px solid {RULE}; background: {PAPER}; padding: 16px;">'
    f'<div style="font-size: 11px; letter-spacing: 0.08em; color: {DIM}; margin-bottom: 11px;">채점이 멈추면 참여자에게 보이는 것</div>'
    f'<div style="border: 1px solid {RULE}; background: {SURFACE}; padding: 14px 16px;">'
    f'<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 9px;">'
    f'<span style="border: 1px solid {RULE}; color: {MUTED}; font-size: 11.5px; padding: 2px 9px;">채점 대기</span>'
    f'<span style="font-size: 12.5px; color: {MUTED};">시도 4 · 방금</span></div>'
    f'<div style="font-size: 12.5px; color: {MUTED}; line-height: 1.65;">제출은 저장되었습니다. 강사의 채점 예산이 채워지면 이 시도부터 순서대로 채점됩니다 — 다시 제출할 필요가 없습니다.</div>'
    f'</div><div style="font-size: 11.5px; color: {FAINT}; line-height: 1.6; margin-top: 10px;">'
    f'「고장났다」로 읽히지 않게 <b style="color: {MUTED};">무엇이 멈췄고 무엇은 안전한지</b>를 같이 말합니다.</div></div>')

BUDGET = body(
    classtitle("채점은 강사 본인의 키로 돕니다 — 플랫폼이 대신 내지 않습니다.")
    + invite() + tabs("설정")
    + f'<div style="margin-top: -20px; display: flex; flex-direction: column; gap: 18px;">'
      f'<div style="border: 1px solid {ATT}; background: {SURFACE}; padding: 14px 18px; display: flex; align-items: center; gap: 16px;">'
      f'<div style="width: 3px; align-self: stretch; background: {ATT};"></div>'
      f'<div style="flex: 1;"><div style="font-size: 14px; font-weight: 600; color: {ATT};">이번 달 예산의 92% 를 썼습니다</div>'
      f'<div style="font-size: 12.5px; color: {MUTED}; margin-top: 4px; line-height: 1.6;">'
      f'남은 양으로 대략 <b style="color: {INK};">18번</b> 더 채점할 수 있습니다. 다 쓰면 채점이 멈추고 제출은 계속 쌓입니다 — 예산을 채우면 쌓인 것부터 순서대로 이어집니다.</div></div>'
      f'{btn("한도 올리기", primary=True, small=True)}</div>'
      f'<div style="display: flex; gap: 20px; align-items: flex-start;">'
      f'<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 18px;">'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("OpenAI 키", "이 클래스의 채점에만 쓰입니다")}</div>'
      f'<div style="padding: 16px; display: flex; flex-direction: column; gap: 12px;">'
      f'<div style="display: flex; gap: 10px; align-items: center;">'
      f'<div style="flex: 1; border: 1px solid {RULE}; padding: 11px 13px; font-family: {MONO}; font-size: 13px; color: {MUTED};">sk-proj-••••••••••••••••••••••7f2a</div>'
      f'{btn("바꾸기", small=True)}</div>'
      f'<div style="font-size: 11.5px; color: {DIM}; line-height: 1.65;">저장 뒤에는 다시 볼 수 없습니다 — 화면에도 로그에도 남지 않고, 채점 요청을 보낼 때만 복호화됩니다. 참여자에게는 어떤 형태로도 보이지 않습니다.</div>'
      f'</div></div>'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("클래스 기본 모델", "문제마다 따로 정할 수도 있습니다")}</div>'
      + "".join(model_row(*m) for m in MODELS)
      + f'<div style="padding: 13px 16px; font-size: 11.5px; color: {FAINT}; line-height: 1.6;">'
        f'모델마다 한 번에 받을 수 있는 소스의 양이 다릅니다 — 긴 문제에 작은 모델을 고르면 소스 뒷부분이 잘린 채 채점됩니다.</div></div></div>'
      f'<div style="width: 380px; flex-shrink: 0; display: flex; flex-direction: column; gap: 18px;">'
      f'<div style="border: 1px solid {RULE}; background: {SURFACE};">'
      f'<div style="padding: 14px 16px 12px; border-bottom: 1px solid {RULE};">{sectiontitle("이번 달 사용량")}</div>'
      f'<div style="padding: 16px; display: flex; flex-direction: column; gap: 14px;">'
      f'<div style="display: flex; align-items: baseline; justify-content: space-between;">'
      f'<span style="font-family: {MONO}; font-size: 26px; font-weight: 600; color: {ATT};">92%</span>'
      f'<span style="font-size: 12.5px; color: {MUTED};">$46.10 / $50.00</span></div>'
      f'{bar(92, 348, ATT)}'
      f'<div style="display: flex; justify-content: space-between; font-size: 12.5px;">'
      f'<span style="color: {MUTED};">채점 횟수</span><span style="font-family: {MONO};">412회</span></div>'
      f'<div style="display: flex; justify-content: space-between; font-size: 12.5px;">'
      f'<span style="color: {MUTED};">한 번 평균</span><span style="font-family: {MONO};">$0.11</span></div>'
      f'<div style="display: flex; justify-content: space-between; font-size: 12.5px; padding-top: 12px; border-top: 1px solid {RULE};">'
      f'<span style="color: {MUTED};">경고 임계</span><span style="font-family: {MONO};">85%</span></div>'
      f'<div style="font-size: 11.5px; color: {DIM}; line-height: 1.65;">임계에 닿으면 서비스 안 알림으로 알립니다 — 메일이나 문자가 아니라, 이 화면에 들어오면 보이는 알림입니다.</div>'
      f'</div></div>{halted_preview}</div></div></div>')
write("Budget.dc.html", header(active="내 클래스") + BUDGET, h=1080)
