# -*- coding: utf-8 -*-
"""#321 이후의 시안 — 템플릿을 클래스 안에서 집는 길, 미리보기 탭, 「클래스 설정」.

사용자가 걸어 보고 지적한 넷을 화면으로 답한다:
  1. 새 문제를 낼 때 공유된 템플릿에서 가져올 길이 없다 (지금은 클래스를 나갔다 와야 한다)
  3. 미리보기가 설명만 그린다 — 참여자가 실제로 보는 화면을 못 본다
  5. 「클래스를 템플릿으로 공개」가 매일 보는 화면의 자리를 차지한다
  6. 「채점 설정」이 그 화면이 하는 일보다 좁은 이름이다
"""
from _lib import (INK, PAPER, SURFACE, RULE, ATT, VER, MUTED, DIM, FAINT, SANS, MONO,
                  HEAD, TAIL, frame, body, btn, card, note, caption, sectiontitle, write)

def header(unread=3, who="내 계정"):
    badge = (f'<span style="font-family:{MONO};font-size:10.5px;background:{ATT};color:{PAPER};'
             f'padding:1px 6px;margin-left:6px;">{unread}</span>') if unread else ""
    return (f'<div style="height: 72px; border-bottom: 1px solid {RULE}; display: flex; align-items: center; '
            f'justify-content: space-between; padding: 0 40px; background: {SURFACE}; flex-shrink: 0;">'
            f'<div style="font-size: 21px; font-weight: 700; letter-spacing: -0.01em;">Laurio '
            f'<span style="font-weight:400;color:{DIM};font-size:15px;">클래스</span></div>'
            f'<div style="display:flex;align-items:center;gap:22px;font-size:13px;color:{MUTED};">'
            f'<div>알림{badge}</div>'
            f'<div style="border:1px solid {RULE};padding:5px 11px;color:{INK};">{who}</div></div></div>')

def crumb(eyebrow, title, right=""):
    return (f'<div style="display:flex;align-items:flex-end;justify-content:space-between;">'
            f'<div style="display:flex;flex-direction:column;gap:6px;">'
            f'<div style="font-size:11px;letter-spacing:0.08em;color:{DIM};">{eyebrow}</div>'
            f'<div style="font-size:22px;font-weight:600;">{title}</div></div>'
            f'<div style="display:flex;gap:8px;">{right}</div></div>')

def tabs(items, active):
    out = ""
    for t in items:
        if t == active:
            out += (f'<div style="padding:9px 2px;margin-right:24px;font-size:13.5px;color:{INK};'
                    f'font-weight:500;border-bottom:2px solid {ATT};">{t}</div>')
        else:
            out += (f'<div style="padding:9px 2px;margin-right:24px;font-size:13.5px;color:{MUTED};'
                    f'border-bottom:2px solid transparent;">{t}</div>')
    return f'<div style="display:flex;border-bottom:1px solid {RULE};">{out}</div>'

def field(label, value, hint=None, mono=False, minh=None):
    ff = f"font-family:{MONO};" if mono else ""
    mh = f"min-height:{minh}px;" if minh else ""
    h = f'<div style="font-size:11.5px;color:{DIM};line-height:1.55;">{hint}</div>' if hint else ""
    return (f'<div style="display:flex;flex-direction:column;gap:7px;">'
            f'<div style="font-size:12px;color:{MUTED};">{label}</div>'
            f'<div style="border:1px solid {RULE};background:{SURFACE};padding:11px 13px;'
            f'font-size:13.5px;line-height:1.6;{ff}{mh}">{value}</div>{h}</div>')

def checkitem(n, text, required=True, last=False):
    b = "" if last else f"border-bottom:1px solid {RULE};"
    tag = (f'<span style="border:1px solid {ATT};color:{ATT};font-size:10.5px;padding:1px 7px;">필수</span>'
           if required else
           f'<span style="border:1px solid {RULE};color:{DIM};font-size:10.5px;padding:1px 7px;">선택</span>')
    return (f'<div style="display:flex;align-items:center;gap:12px;padding:11px 14px;{b}">'
            f'<div style="font-family:{MONO};font-size:11.5px;color:{FAINT};width:14px;">{n}</div>'
            f'<div style="flex:1;font-size:13.5px;line-height:1.5;">{text}</div>{tag}'
            f'<div style="color:{FAINT};font-size:13px;">⋮⋮</div></div>')

# ── 1. 새 문제 — 작성 탭. 템플릿 진입점이 여기 있다 ──────────────────────────
FROM_TEMPLATE = (
    f'<div style="border:1px solid {RULE};background:{SURFACE};display:flex;align-items:center;'
    f'justify-content:space-between;padding:14px 18px;">'
    f'<div style="display:flex;flex-direction:column;gap:4px;">'
    f'<div style="font-size:14px;font-weight:600;">이미 있는 문제로 시작하기</div>'
    f'<div style="font-size:12px;color:{MUTED};line-height:1.6;">다른 강사가 공개한 문제나 '
    f'내가 지난 기수에 쓴 문제를 가져오면 체크리스트까지 따라옵니다 — 가져온 뒤 고칠 수 있습니다.</div>'
    f'</div>{btn("템플릿에서 가져오기", primary=False)}</div>')

NEWPROBLEM = body(
    crumb("[데모] 웹 프론트엔드 스터디 · 새 문제", "새 문제",
          btn("초안으로 저장") + btn("만들고 바로 열기", primary=True))
    + FROM_TEMPLATE
    + tabs(["작성", "미리보기"], "작성")
    + f'<div style="display:flex;gap:20px;align-items:flex-start;">'
    + f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:18px;">'
    + field("제목", "3주차 — 서버와 붙이기")
    + f'<div style="display:flex;flex-direction:column;gap:7px;">'
      f'<div style="font-size:12px;color:{MUTED};">설명</div>'
      f'<div style="border:1px solid {RULE};background:{SURFACE};">'
      f'<div style="display:flex;gap:2px;border-bottom:1px solid {RULE};padding:6px 8px;'
      f'font-size:12.5px;color:{MUTED};">'
      + "".join(f'<div style="padding:4px 8px;border:1px solid transparent;">{t}</div>'
                for t in ["H", "<b>B</b>", "<i>I</i>", "“ ”", "• 목록", "1. 번호", "&lt;/&gt; 코드", "🔗 링크", "🖼 이미지", "표"])
      + f'<div style="margin-left:auto;display:flex;gap:2px;">'
        f'<div style="padding:4px 9px;border:1px solid {RULE};background:{PAPER};font-size:12px;">마크다운</div>'
        f'<div style="padding:4px 9px;font-size:12px;color:{DIM};">보이는 대로</div></div></div>'
      f'<div style="padding:13px 15px;font-size:13.5px;line-height:1.75;min-height:240px;font-family:{MONO};'
      f'color:{MUTED};">'
      f'<span style="color:{INK};">## 무엇을 만드나요</span><br><br>'
      f'앞 주차에 만든 목록을 <span style="color:{INK};">`fetch`</span> 로 서버에서 받아오게 고칩니다.<br><br>'
      f'<span style="color:{INK};">## 꼭 다뤄야 하는 것</span><br><br>'
      f'- 받아오는 동안 보여줄 화면<br>- 실패했을 때 보여줄 화면<br>- 목록이 비었을 때 보여줄 화면<br><br>'
      f'성공한 경우만 만들면 통과하지 못합니다.'
      f'</div></div>'
      f'<div style="font-size:11.5px;color:{DIM};line-height:1.55;">'
      f'ToastUI 에디터 — 마크다운으로 쓰거나 보이는 대로 쓰거나 고를 수 있습니다. '
      f'저장되는 것은 언제나 마크다운 원문입니다.</div></div>'
    + f'<div style="display:flex;flex-direction:column;gap:4px;">'
      f'<div style="font-size:12px;color:{MUTED};">제출 형식</div>'
      f'<div style="display:flex;gap:10px;align-items:center;padding:9px 0;">'
      f'<div style="width:13px;height:13px;border:1px solid {RULE};"></div>'
      f'<div style="font-size:13.5px;">소스 파일을 올린다</div></div>'
      f'<div style="display:flex;gap:10px;align-items:center;padding:9px 0;">'
      f'<div style="width:13px;height:13px;border:1px solid {INK};display:flex;align-items:center;'
      f'justify-content:center;"><div style="width:7px;height:7px;background:{INK};"></div></div>'
      f'<div style="font-size:13.5px;">GitHub 저장소 주소를 낸다</div></div></div>'
    + '</div>'
    + f'<div style="width:460px;flex-shrink:0;display:flex;flex-direction:column;gap:18px;">'
    + card(f'<div style="padding:14px 16px 12px;border-bottom:1px solid {RULE};">'
           + sectiontitle("체크리스트", "필수를 전부 충족하면 「통과」") + '</div>'
           + checkitem(1, "fetch 로 목록을 받아온다")
           + checkitem(2, "받아오는 동안의 화면이 있다")
           + checkitem(3, "실패했을 때의 화면이 있다")
           + checkitem(4, "목록이 비었을 때의 화면이 있다")
           + checkitem(5, "재시도할 수 있다", required=False)
           + f'<div style="padding:13px 14px;display:flex;gap:8px;align-items:center;">'
             f'<div style="flex:1;border:1px solid {RULE};background:{PAPER};padding:8px 11px;'
             f'font-size:12.5px;color:{FAINT};">새 항목 — 채점이 이 문장으로 판정합니다</div>'
             + btn("추가", small=True) + '</div>')
    + note(f'<b style="color:{INK};">필수 항목이 4개 있으니 바로 열 수 있습니다.</b> '
           f'하나도 없으면 「통과」가 무엇인지 정해지지 않아 문제를 열 수 없습니다.')
    + '</div></div>')

write("Main.dc.html", header() + NEWPROBLEM, h=1180)

# ── 2. 같은 화면의 미리보기 탭 — 참여자가 실제로 보는 것 ──────────────────────
LEARNER_VIEW = (
    f'<div style="border:1px solid {RULE};background:{PAPER};padding:26px 30px;">'
    f'<div style="max-width:760px;margin:0 auto;display:flex;flex-direction:column;gap:18px;">'
    f'<div style="display:flex;flex-direction:column;gap:6px;">'
    f'<div style="font-size:11px;letter-spacing:0.08em;color:{DIM};">[데모] 웹 프론트엔드 스터디</div>'
    f'<div style="font-size:21px;font-weight:600;">3주차 — 서버와 붙이기</div></div>'
    + card(f'<div style="padding:18px 20px;font-size:13.5px;line-height:1.8;">'
           f'<div style="font-size:16px;font-weight:600;margin-bottom:10px;">무엇을 만드나요</div>'
           f'앞 주차에 만든 목록을 <span style="font-family:{MONO};border:1px solid {RULE};'
           f'background:{PAPER};padding:1px 5px;font-size:12.5px;">fetch</span> 로 서버에서 받아오게 고칩니다.'
           f'<div style="font-size:16px;font-weight:600;margin:16px 0 8px;">꼭 다뤄야 하는 것</div>'
           f'<ul style="margin:0;padding-left:20px;line-height:1.9;">'
           f'<li>받아오는 동안 보여줄 화면</li><li>실패했을 때 보여줄 화면</li>'
           f'<li>목록이 비었을 때 보여줄 화면</li></ul>'
           f'<div style="margin-top:12px;">성공한 경우만 만들면 통과하지 못합니다.</div></div>')
    + card(f'<div style="padding:14px 16px 12px;border-bottom:1px solid {RULE};">'
           + sectiontitle("이런 것을 봅니다", "아래를 전부 충족하면 통과입니다") + '</div>'
           + "".join(
               f'<div style="display:flex;align-items:center;gap:11px;padding:11px 16px;'
               f'{"" if i==4 else f"border-bottom:1px solid {RULE};"}">'
               f'<div style="width:13px;height:13px;border:1px solid {RULE};"></div>'
               f'<div style="flex:1;font-size:13.5px;">{t}</div>'
               + ("" if req else f'<span style="border:1px solid {RULE};color:{DIM};font-size:10.5px;'
                                 f'padding:1px 7px;">안 해도 됩니다</span>') + '</div>'
               for i, (t, req) in enumerate([
                   ("fetch 로 목록을 받아온다", True),
                   ("받아오는 동안의 화면이 있다", True),
                   ("실패했을 때의 화면이 있다", True),
                   ("목록이 비었을 때의 화면이 있다", True),
                   ("재시도할 수 있다", False)])))
    + card(f'<div style="padding:16px 18px;display:flex;flex-direction:column;gap:11px;">'
           f'<div style="font-size:12px;color:{MUTED};">GitHub 저장소 주소</div>'
           f'<div style="display:flex;gap:8px;">'
           f'<div style="flex:1;border:1px solid {RULE};background:{PAPER};padding:10px 12px;'
           f'font-family:{MONO};font-size:12.5px;color:{FAINT};">https://github.com/…</div>'
           + btn("내기", primary=True) + '</div>'
           f'<div style="font-size:11.5px;color:{DIM};line-height:1.6;">'
           f'내면 바로 채점이 시작되고, <b style="color:{INK};font-weight:500;">끝나면 알림이 옵니다.</b> '
           f'한 번이라도 통과하면 계속 통과로 남으니, 안 되면 몇 번이든 고쳐서 다시 낼 수 있습니다.</div></div>')
    + '</div></div>')

PREVIEW = body(
    crumb("[데모] 웹 프론트엔드 스터디 · 새 문제", "새 문제",
          btn("초안으로 저장") + btn("만들고 바로 열기", primary=True))
    + FROM_TEMPLATE
    + tabs(["작성", "미리보기"], "미리보기")
    + note(f'<b style="color:{INK};">참여자가 보는 화면 그대로입니다.</b> '
           f'설명이 어떻게 그려지는지, 체크리스트가 어떤 말로 보이는지, 무엇을 어디에 내는지를 '
           f'열기 전에 확인합니다 — 지금은 설명만 미리 볼 수 있어 나머지는 열어 봐야 압니다.')
    + LEARNER_VIEW)

write("NewProblemPreview.dc.html", header() + PREVIEW, h=1420)

# ── 3. 템플릿 고르기 — 클래스를 나가지 않는다 ────────────────────────────────
def tpl_row(title, who, when, taken, items, last=False, picked=False):
    b = "" if last else f"border-bottom:1px solid {RULE};"
    bg = PAPER if picked else SURFACE
    mark = (f'<div style="width:13px;height:13px;border:1px solid {INK};display:flex;align-items:center;'
            f'justify-content:center;flex-shrink:0;"><div style="width:7px;height:7px;background:{INK};">'
            f'</div></div>') if picked else \
           f'<div style="width:13px;height:13px;border:1px solid {RULE};flex-shrink:0;"></div>'
    return (f'<div style="display:flex;gap:13px;padding:14px 18px;{b}background:{bg};">'
            f'{mark}<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:5px;">'
            f'<div style="font-size:14px;font-weight:500;">{title}</div>'
            f'<div style="font-size:11.5px;color:{DIM};">{who} · {when} · 체크리스트 {items}개 · '
            f'{taken}번 가져감</div></div></div>')

PICKER = (
    f'<div style="border:1px solid {RULE};background:{SURFACE};display:flex;flex-direction:column;'
    f'max-height:760px;">'
    f'<div style="padding:18px 20px 14px;border-bottom:1px solid {RULE};display:flex;'
    f'align-items:flex-end;justify-content:space-between;">'
    f'<div style="display:flex;flex-direction:column;gap:5px;">'
    f'<div style="font-size:17px;font-weight:600;">템플릿에서 가져오기</div>'
    f'<div style="font-size:12px;color:{MUTED};">고른 문제가 <b style="color:{INK};font-weight:500;">'
    f'[데모] 웹 프론트엔드 스터디</b> 에 초안으로 들어옵니다 — 가져온 뒤 고칠 수 있습니다.</div></div>'
    f'<div style="font-size:12.5px;color:{DIM};">닫기 ✕</div></div>'
    + tabs(["공개된 문제", "내가 올린 것", "내 다른 클래스에서"], "공개된 문제")
    + f'<div style="display:flex;gap:8px;padding:14px 18px;border-bottom:1px solid {RULE};">'
      f'<div style="flex:1;border:1px solid {RULE};background:{PAPER};padding:9px 12px;'
      f'font-size:13px;color:{FAINT};">문제 제목으로 찾기</div>' + btn("검색", small=True) + '</div>'
    + f'<div style="flex:1;overflow:hidden;">'
    + tpl_row("할 일 목록 만들기", "김강사", "9월 11일", 12, 3, picked=True)
    + tpl_row("fetch 로 목록 그리기", "이선생", "9월 8일", 7, 5)
    + tpl_row("로그인 폼과 유효성 검사", "박멘토", "9월 2일", 4, 4)
    + tpl_row("무한 스크롤 구현하기", "김강사", "8월 30일", 2, 6, last=True)
    + '</div>'
    + f'<div style="border-top:1px solid {RULE};padding:16px 20px;display:flex;'
      f'align-items:center;justify-content:space-between;background:{PAPER};">'
      f'<div style="font-size:12px;color:{MUTED};line-height:1.6;">'
      f'제목·설명·체크리스트가 따라옵니다. '
      f'<b style="color:{INK};font-weight:500;">채점 모델은 따라오지 않습니다</b> — '
      f'남이 고른 비싼 모델이 내 키로 돌지 않게.</div>'
      f'<div style="display:flex;gap:8px;">{btn("미리보기")}{btn("이 문제 가져오기", primary=True)}</div></div>'
    + '</div>')

write("TemplatePicker.dc.html",
      header() + body(
          crumb("[데모] 웹 프론트엔드 스터디 · 새 문제", "새 문제",
                btn("초안으로 저장") + btn("만들고 바로 열기", primary=True))
          + note("지금은 이 자리에 진입점이 없어, 클래스를 나가 전체 템플릿 목록으로 갔다가 "
                 "거기서 <b style='color:#17160F'>대상 클래스로 자기를 다시 골라야</b> 합니다.", tone="att")
          + PICKER), h=1180)

# ── 4. 「클래스 설정」 — 이름을 넓히고, 공개를 여기로 옮긴다 ──────────────────
def setting_card(title, sub, inner):
    return card(f'<div style="padding:14px 16px 12px;border-bottom:1px solid {RULE};">'
                + sectiontitle(title, sub) + f'</div><div style="padding:16px;">{inner}</div>')

SETTINGS = body(
    crumb("[데모] 웹 프론트엔드 스터디", "클래스 설정", btn("클래스로 돌아가기"))
    + note(f'「채점 설정」이던 이름을 넓혔다 — 이 화면의 넷 중 '
           f'<b style="color:{INK};">강사 이름</b>과 <b style="color:{INK};">템플릿 공개</b>는 '
           f'채점과 아무 상관이 없다. 이름이 내용보다 좁으면 사람이 찾지 못한다.')
    + f'<div style="display:flex;gap:20px;align-items:flex-start;">'
    + f'<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:18px;">'
    + setting_card("강사 이름", "가입 미리보기에서 이 이름으로 보입니다",
        f'<div style="display:flex;gap:8px;">'
        f'<div style="flex:1;border:1px solid {RULE};background:{PAPER};padding:10px 12px;font-size:13.5px;">김강사</div>'
        + btn("저장", small=True) + '</div>'
        f'<div style="font-size:11.5px;color:{DIM};margin-top:9px;line-height:1.6;">'
        f'참여자 명단과 제출물에 보이는 이름과는 별개입니다 — 그곳은 참여자 본인이 정한 이름을 씁니다.</div>')
    + setting_card("채점 키", "이 클래스의 채점에만 쓰입니다",
        f'<div style="display:flex;align-items:center;gap:10px;font-size:13.5px;">'
        f'<span style="font-family:{MONO};border:1px solid {RULE};background:{PAPER};padding:3px 9px;'
        f'font-size:12.5px;">sk-…9f2a</span>'
        f'<span style="font-size:12px;color:{MUTED};">넣어 둠</span></div>'
        f'<div style="font-size:11.5px;color:{DIM};margin-top:10px;line-height:1.6;">'
        f'저장 뒤에는 다시 볼 수 없습니다 — 화면에도 로그에도 남지 않고, 채점 요청을 보낼 때만 풀립니다.</div>')
    + setting_card("기본 채점 모델", "문제가 자기 모델을 갖지 않으면 이 값을 씁니다",
        f'<div style="display:flex;gap:8px;">'
        f'<div style="flex:1;border:1px solid {RULE};background:{PAPER};padding:10px 12px;font-size:13.5px;'
        f'display:flex;justify-content:space-between;"><span>GPT-4o mini · 컨텍스트 128,000 토큰</span>'
        f'<span style="color:{DIM};">▾</span></div>' + btn("저장", small=True) + '</div>')
    + '</div>'
    + f'<div style="width:460px;flex-shrink:0;display:flex;flex-direction:column;gap:18px;">'
    + setting_card("채점 예산", "한도에 닿으면 채점만 멈추고 제출은 쌓입니다",
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px;">'
        f'<div style="font-size:12px;color:{MUTED};">사용량</div>'
        f'<div style="font-family:{MONO};font-size:13px;color:{ATT};">1,740,000 / 2,000,000</div></div>'
        f'<div style="height:6px;background:{PAPER};border:1px solid {RULE};position:relative;">'
        f'<div style="position:absolute;left:0;top:0;bottom:0;width:87%;background:{ATT};"></div></div>'
        f'<div style="font-size:11.5px;color:{DIM};margin-top:10px;line-height:1.6;">'
        f'기준(80%)을 넘어 알림을 보냈습니다 — 메일이나 문자가 아니라 여기 들어오면 보이는 알림입니다.</div>')
    + setting_card("템플릿으로 공개", "다른 강사가 가져다 쓸 수 있게",
        f'<div style="font-size:12px;color:{MUTED};margin-bottom:11px;line-height:1.65;">'
        f'매일 보는 클래스 화면이 아니라 여기 둡니다 — 학기에 한 번 할까 말까 한 일이 '
        f'가입 링크 옆에 상시로 앉아 있을 이유가 없습니다.</div>'
        f'<div style="display:flex;flex-direction:column;gap:9px;">'
        f'<div style="font-size:12px;color:{MUTED};">공개할 때 보일 이름</div>'
        f'<div style="display:flex;gap:8px;">'
        f'<div style="flex:1;border:1px solid {RULE};background:{PAPER};padding:9px 12px;font-size:13px;'
        f'color:{FAINT};">계정 이름과 달라도 됩니다</div>'
        + btn("공개", small=True) + '</div></div>'
        f'<div style="font-size:11.5px;color:{DIM};margin-top:11px;line-height:1.6;">'
        f'공개하는 순간 문제와 순서·체크리스트가 통째로 사본이 떠집니다 — 이후 이 클래스를 고치거나 '
        f'지워도 템플릿은 그대로입니다. 참여자·제출물·판정·가입 코드·채점 키·채점 모델은 담기지 않습니다.</div>')
    + note(f'<b style="color:{INK};">이름 후보</b><br>'
           f'· <b style="color:{INK};">클래스 설정</b> — 넷을 다 덮고 앞으로 무엇이 늘어도 맞다<br>'
           f'· 설정 — 클래스 안이라 맥락이 있다. 짧지만 링크로 보일 때 덜 분명하다<br>'
           f'· 클래스 관리 — 「관리」가 명단·보관까지 포함하는 것으로 읽혀 범위가 흐려진다')
    + '</div></div>')

write("ClassSettings.dc.html", header() + SETTINGS, h=1180)
