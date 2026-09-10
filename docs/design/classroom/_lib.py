INK="#17160F"; PAPER="#F5F3EC"; SURFACE="#FFFEFA"; RULE="#DDD9CE"
ATT="#C4442B"; VER="#2E6A4C"
MUTED="rgba(23,22,15,0.62)"; DIM="rgba(23,22,15,0.45)"; FAINT="rgba(23,22,15,0.28)"
SANS="Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', system-ui, sans-serif"
MONO="'IBM Plex Mono', ui-monospace, monospace"

HEAD = open('_head.txt', encoding='utf-8').read()
TAIL = "</x-dc>\n</body>\n</html>\n"

def frame(inner, h=1020, w=1440):
    return (f'<div style="width: {w}px; min-height: {h}px; background: {PAPER}; color: {INK}; '
            f'font-family: {SANS}; display: flex; flex-direction: column;">\n{inner}\n</div>\n')

def header(active="내 클래스", who="강사 · 김선우"):
    tabs = ["내 클래스", "알림", "설정"]
    items = "".join(
        f'<div style="color: {INK}; font-weight: 500; border-bottom: 2px solid {ATT}; padding-bottom: 3px;">{t}</div>'
        if t == active else f'<div>{t}</div>' for t in tabs)
    return (f'<div style="height: 72px; border-bottom: 1px solid {RULE}; display: flex; align-items: center; '
            f'justify-content: space-between; padding: 0 40px; background: {SURFACE}; flex-shrink: 0;">'
            f'<div style="display: flex; align-items: center; gap: 40px;">'
            f'<div style="font-size: 21px; font-weight: 700; letter-spacing: -0.01em;">Laurio <span style="font-weight:400;color:{DIM};font-size:15px;">강의실</span></div>'
            f'<div style="display: flex; gap: 26px; font-size: 14px; color: {MUTED};">{items}</div></div>'
            f'<div style="font-size: 13px; color: {MUTED};">{who}</div></div>')

def body(inner, gap=20, pad="28px 40px 36px"):
    return f'<div style="flex: 1; display: flex; flex-direction: column; gap: {gap}px; padding: {pad};">{inner}</div>'

def btn(label, primary=False, small=False):
    pad = "7px 13px" if small else "9px 17px"
    fs = "12.5px" if small else "13.5px"
    if primary:
        return (f'<div style="padding: {pad}; background: {INK}; color: {PAPER}; font-size: {fs}; '
                f'font-weight: 500; white-space: nowrap;">{label}</div>')
    return (f'<div style="padding: {pad}; border: 1px solid {RULE}; background: {SURFACE}; '
            f'font-size: {fs}; color: {INK}; white-space: nowrap;">{label}</div>')

def stat(label, value, color=None, mono=True):
    c = color or INK
    ff = f"font-family: {MONO};" if mono else ""
    return (f'<div style="display: flex; flex-direction: column; gap: 3px; padding: 11px 18px;">'
            f'<div style="font-size: 11px; color: {DIM}; letter-spacing: 0.06em;">{label}</div>'
            f'<div style="{ff} font-size: 16px; font-weight: 600; color: {c};">{value}</div></div>')

def statbar(items):
    inner = ""
    for i, (l, v, c) in enumerate(items):
        border = f"border-right: 1px solid {RULE};" if i < len(items) - 1 else ""
        inner += f'<div style="{border}">{stat(l, v, c)}</div>'
    return f'<div style="display: flex; border: 1px solid {RULE}; background: {SURFACE};">{inner}</div>'

def card(inner, pad="0"):
    return f'<div style="border: 1px solid {RULE}; background: {SURFACE}; padding: {pad};">{inner}</div>'

def bar(pct, w=120, color=None):
    c = color or VER
    return (f'<div style="width: {w}px; height: 6px; background: {PAPER}; border: 1px solid {RULE}; position: relative;">'
            f'<div style="position: absolute; left: 0; top: 0; bottom: 0; width: {max(0,min(100,pct))}%; background: {c};"></div></div>')

def note(text, tone="muted"):
    c = ATT if tone == "att" else MUTED
    bg = SURFACE
    return (f'<div style="border: 1px solid {RULE}; background: {bg}; padding: 12px 16px; font-size: 13px; '
            f'color: {c}; line-height: 1.65;">{text}</div>')

def caption(text):
    return (f'<div style="font-size: 11.5px; color: {FAINT}; letter-spacing: 0.06em; line-height: 1.6;">{text}</div>')

def sectiontitle(t, sub=None):
    s = f'<span style="font-size: 12.5px; color: {DIM}; font-weight: 400; margin-left: 10px;">{sub}</span>' if sub else ""
    return f'<div style="font-size: 15px; font-weight: 600; letter-spacing: -0.005em;">{t}{s}</div>'

def write(name, inner, h=1020, w=1440):
    open(name, 'w', encoding='utf-8').write(HEAD + frame(inner, h, w) + TAIL)
    print(f"wrote {name}")
