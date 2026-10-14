# 강의실 시안 v2 의 조각들 (2026-10-14). 값은 `frontend/app/tokens.css` 의 라이트 값 그대로다.
INK = "#17160F"; PAPER = "#F5F3EC"; SURFACE = "#FFFEFA"; RULE = "#DDD9CE"
ATT = "#C4442B"; VER = "#2E6A4C"
MUTED = "rgba(23,22,15,0.62)"; DIM = "rgba(23,22,15,0.45)"; FAINT = "rgba(23,22,15,0.28)"
SANS = "Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', system-ui, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"

HEAD = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>body{margin:0} *{box-sizing:border-box} a{color:inherit;text-decoration:none}</style>
</head><body>
"""
TAIL = "</body></html>\n"


def frame(inner, h=960, w=1200):
    return (f'<div class="dc-frame" style="width:{w}px;min-height:{h}px;background:{PAPER};color:{INK};'
            f'font-family:{SANS};display:flex;flex-direction:column;font-size:13.5px;line-height:1.5;">{inner}</div>')


def header(who="내 계정", guest=False, compact=False):
    right = (f'{btn("로그인", small=True)}' if guest else f'{btn(who, small=True)}' if compact else
             f'{btn("테마: 시스템", small=True)}{btn("알림 <span style=\'display:inline-block;min-width:16px;height:16px;border-radius:8px;background:{ATT};color:{PAPER};font-size:10px;line-height:16px;text-align:center;margin-left:4px;\'>1</span>", small=True)}{btn(who, small=True)}')
    return (f'<div style="height:64px;border-bottom:1px solid {RULE};background:{SURFACE};display:flex;align-items:center;'
            f'justify-content:space-between;padding:0 {"20px" if compact else "32px"};flex-shrink:0;">'
            f'<div style="display:flex;align-items:center;gap:8px;font-size:20px;font-weight:700;letter-spacing:-0.01em;">'
            f'<span style="display:inline-block;width:20px;height:20px;border:3px solid {INK};border-right-color:transparent;border-radius:50%;"></span>'
            f'Codemit <span style="font-size:14px;font-weight:400;color:{DIM};">클래스</span></div>'
            f'<div style="display:flex;gap:6px;">{right}</div></div>')


def body(inner, gap=20, pad="24px 32px 40px"):
    return f'<div style="flex:1;display:flex;flex-direction:column;gap:{gap}px;padding:{pad};">{inner}</div>'


def btn(label, primary=False, small=False, danger=False, ghost=False):
    pad = "6px 12px" if small else "8px 16px"
    fs = "12.5px" if small else "13.5px"
    if primary:
        return f'<span style="display:inline-block;padding:{pad};background:{INK};color:{PAPER};font-size:{fs};font-weight:500;white-space:nowrap;">{label}</span>'
    if danger:
        return f'<span style="display:inline-block;padding:{pad};border:1px solid {ATT};background:{SURFACE};color:{ATT};font-size:{fs};white-space:nowrap;">{label}</span>'
    if ghost:
        return f'<span style="display:inline-block;padding:{pad};color:{MUTED};font-size:{fs};white-space:nowrap;text-decoration:underline;text-underline-offset:3px;">{label}</span>'
    return f'<span style="display:inline-block;padding:{pad};border:1px solid {RULE};background:{SURFACE};color:{INK};font-size:{fs};white-space:nowrap;">{label}</span>'


def badge(label, tone="neutral"):
    c = {"neutral": DIM, "att": ATT, "ver": VER}[tone]
    b = {"neutral": RULE, "att": ATT, "ver": VER}[tone]
    return f'<span style="display:inline-block;border:1px solid {b};color:{c};font-size:11px;line-height:1.2;padding:2px 7px;white-space:nowrap;">{label}</span>'


def eyebrow(text):
    return f'<div style="font-size:11px;letter-spacing:0.08em;color:{DIM};">{text}</div>'


def pagehead(crumb, title, sub=None, actions="", extra=""):
    s = f'<div style="font-size:13px;color:{MUTED};">{sub}</div>' if sub else ""
    return (f'<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:24px;flex-wrap:wrap;">'
            f'<div style="display:flex;flex-direction:column;gap:6px;min-width:0;">{eyebrow(crumb)}'
            f'<div style="display:flex;align-items:center;gap:12px;"><div style="font-size:22px;font-weight:600;letter-spacing:-0.01em;">{title}</div>{extra}</div>{s}</div>'
            f'<div style="display:flex;align-items:center;gap:8px;">{actions}</div></div>')


def stat(label, value, color=None, mono=True):
    ff = f"font-family:{MONO};" if mono else ""
    return (f'<div style="display:flex;flex-direction:column;gap:2px;padding:10px 18px;">'
            f'<div style="font-size:11px;color:{DIM};letter-spacing:0.06em;">{label}</div>'
            f'<div style="{ff}font-size:16px;font-weight:600;color:{color or INK};">{value}</div></div>')


def statbar(items):
    out = ""
    for i, (l, v, c) in enumerate(items):
        border = f"border-right:1px solid {RULE};" if i < len(items) - 1 else ""
        out += f'<div style="{border}">{stat(l, v, c)}</div>'
    return f'<div style="display:flex;border:1px solid {RULE};background:{SURFACE};">{out}</div>'


def card(inner, pad="0", style=""):
    return f'<div style="border:1px solid {RULE};background:{SURFACE};padding:{pad};{style}">{inner}</div>'


def cardhead(title, hint=None, right=""):
    h = f'<span style="font-size:12.5px;color:{DIM};font-weight:400;margin-left:10px;">{hint}</span>' if hint else ""
    return (f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid {RULE};">'
            f'<div style="font-size:15px;font-weight:600;letter-spacing:-0.005em;">{title}{h}</div><div style="display:flex;gap:8px;">{right}</div></div>')


def bar(pct, w=120, color=None, h=6):
    c = color or VER
    width = w if isinstance(w, str) else f"{w}px"
    return (f'<div style="width:{width};height:{h}px;background:{PAPER};border:1px solid {RULE};position:relative;flex-shrink:0;">'
            f'<div style="position:absolute;left:0;top:0;bottom:0;width:{max(0, min(100, pct))}%;background:{c};"></div></div>')


def ratecolor(pct):
    return VER if pct >= 60 else (ATT if pct < 30 else INK)


def note(text, tone="muted"):
    c = INK if tone == "att" else MUTED
    b = ATT if tone == "att" else RULE
    return f'<div style="border:1px solid {b};background:{SURFACE};padding:11px 16px;font-size:13px;color:{c};line-height:1.65;">{text}</div>'


def hint(text):
    return f'<div style="font-size:11.5px;color:{DIM};line-height:1.6;">{text}</div>'


def tabs(items, active):
    out = ""
    for t in items:
        if t == active:
            out += (f'<div style="padding:9px 18px;border:1px solid {RULE};border-bottom:1px solid {SURFACE};'
                    f'background:{SURFACE};font-size:13.5px;font-weight:500;margin-bottom:-1px;">{t}</div>')
        else:
            out += f'<div style="padding:9px 18px;font-size:13.5px;color:{MUTED};">{t}</div>'
    return f'<div style="display:flex;align-items:flex-end;border-bottom:1px solid {RULE};gap:2px;">{out}</div>'


def field(label, value, mono=False, hint_text=None, h=None, placeholder=False):
    ff = f"font-family:{MONO};" if mono else ""
    col = f"color:{FAINT};" if placeholder else ""
    box = (f'<div style="border:1px solid {RULE};background:{SURFACE};padding:9px 12px;font-size:13.5px;{ff}{col}line-height:1.6;'
           f'{"min-height:" + str(h) + "px;" if h else ""}">{value}</div>')
    hl = hint(hint_text) if hint_text else ""
    return f'<div style="display:flex;flex-direction:column;gap:6px;"><div style="font-size:12px;color:{MUTED};">{label}</div>{box}{hl}</div>'


def check(label, on, hint_text=None, radio=False):
    if radio:
        box = (f'<div style="width:13px;height:13px;border:1px solid {INK};display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:3px;">'
               f'<div style="width:7px;height:7px;background:{INK};"></div></div>' if on
               else f'<div style="width:13px;height:13px;border:1px solid {RULE};flex-shrink:0;margin-top:3px;"></div>')
    else:
        box = (f'<div style="width:13px;height:13px;background:{INK};flex-shrink:0;margin-top:3px;"></div>' if on
               else f'<div style="width:13px;height:13px;border:1px solid {RULE};flex-shrink:0;margin-top:3px;"></div>')
    h = hint(hint_text) if hint_text else ""
    return f'<div style="display:flex;gap:10px;align-items:flex-start;padding:6px 0;">{box}<div><div style="font-size:13.5px;">{label}</div>{h}</div></div>'


def mark(kind, size=14):
    """격자·판정 표식. passed / failed / scoring / blocked / none"""
    if kind == "passed":
        return f'<span style="display:inline-block;width:{size}px;height:{size}px;background:{VER};vertical-align:middle;"></span>'
    if kind == "failed":
        return f'<span style="display:inline-block;width:{size}px;height:{size}px;border:1px solid {ATT};vertical-align:middle;"></span>'
    if kind == "scoring":
        return (f'<span style="display:inline-block;width:{size}px;height:{size}px;border:1px solid {RULE};vertical-align:middle;'
                f'background:repeating-linear-gradient(45deg,{RULE} 0 2px,{SURFACE} 2px 4px);"></span>')
    if kind == "blocked":
        return f'<span style="display:inline-block;width:{size}px;height:{size}px;border:1px dashed {ATT};vertical-align:middle;"></span>'
    return f'<span style="display:inline-block;width:5px;height:5px;background:{FAINT};vertical-align:middle;margin:0 {(size-5)//2}px;"></span>'


def kebab():
    return f'<span style="color:{FAINT};font-size:14px;letter-spacing:1px;">⋮</span>'


def write(name, inner, h=960, w=1200):
    open(name, "w", encoding="utf-8").write(HEAD + frame(inner, h, w) + TAIL)
    print("wrote", name)
