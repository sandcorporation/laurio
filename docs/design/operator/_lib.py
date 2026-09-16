# 운영자 앱 시안 도구(2026-09-16). 강의실 시안(../classroom/_lib.py)과 같은 방식이고,
# 색도 같은 토큰을 쓴다 — 한 사람이 세 앱을 오가는데 생김이 달라지지 않아야 한다.
# 다른 점 둘: (1) 왼쪽에 좁은 내비가 있다, (2) 행이 촘촘하다(운영은 표를 읽는 일이다).

LIGHT = dict(
    ink="#17160F", paper="#F5F3EC", surface="#FFFEFA", rule="#DDD9CE",
    att="#C4442B", ver="#2E6A4C",
    muted="rgba(23,22,15,0.62)", dim="rgba(23,22,15,0.45)", faint="rgba(23,22,15,0.28)",
    zebra="rgba(23,22,15,0.02)",
)
# tokens.css 의 `light-dark()` 둘째 값 그대로.
DARK = dict(
    ink="#ECE8DC", paper="#171611", surface="#211F19", rule="#38352C",
    att="#E5694F", ver="#62B489",
    muted="rgba(236,232,220,0.62)", dim="rgba(236,232,220,0.45)", faint="rgba(236,232,220,0.28)",
    zebra="rgba(236,232,220,0.03)",
)

SANS = "Pretendard, 'Malgun Gothic', 'Apple SD Gothic Neo', system-ui, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"

HEAD = open("_head.txt", encoding="utf-8").read()
TAIL = "</x-dc>\n</body>\n</html>\n"

#: 왼쪽 내비 — 「할 일」·「기준」·「운영」 셋으로 묶는다. 지금 내가 해야 하는 일과,
#: 바꾸면 서비스가 흔들리는 것을 한 바구니에 담지 않는다.
NAV = [
    ("할 일", [("이의 심판", "4"), ("지급", "7"), ("신고된 템플릿", "2")]),
    ("기준", [("플랫폼 정책", None), ("카테고리", None), ("산출물 종류", None)]),
    ("운영", [("운영자 계정", None), ("개최 권한", None), ("운영팀 알림", None), ("무료 공모전", None)]),
]


class Comp:
    """한 장의 시안. 팔레트를 들고 조각을 조립한다."""

    def __init__(self, palette=LIGHT):
        self.p = palette

    # --- 뼈대 ---------------------------------------------------------------
    def frame(self, inner, w=1440, h=1020):
        p = self.p
        scheme = "dark" if p is DARK else "light"
        return (f'<div style="width: {w}px; min-height: {h}px; background: {p["paper"]}; color: {p["ink"]}; '
                f'font-family: {SANS}; display: flex; color-scheme: {scheme};">{inner}</div>\n')

    def nav(self, active):
        p = self.p
        groups = []
        for title, items in NAV:
            rows = []
            for label, count in items:
                on = label == active
                bg = p["surface"] if on else "transparent"
                weight = "500" if on else "400"
                color = p["ink"] if on else p["muted"]
                mark = (f'<div style="width: 2px; align-self: stretch; background: {p["att"]};"></div>'
                        if on else '<div style="width: 2px;"></div>')
                badge = (f'<span style="font-family: {MONO}; font-size: 12px; color: {p["muted"]};">{count}</span>'
                         if count else "")
                rows.append(
                    f'<div style="display: flex; align-items: stretch; gap: 10px; background: {bg};">'
                    f'{mark}'
                    f'<div style="flex: 1; display: flex; align-items: center; justify-content: space-between; '
                    f'padding: 7px 14px 7px 4px; font-size: 13px; font-weight: {weight}; color: {color};">'
                    f'<span>{label}</span>{badge}</div></div>')
            groups.append(
                f'<div style="display: flex; flex-direction: column; gap: 2px;">'
                f'<div style="font-size: 10.5px; letter-spacing: 0.1em; color: {p["faint"]}; padding: 0 16px 6px;">{title}</div>'
                f'{"".join(rows)}</div>')
        return (f'<div style="width: 208px; flex-shrink: 0; border-right: 1px solid {p["rule"]}; '
                f'background: {p["paper"]}; display: flex; flex-direction: column;">'
                f'<div style="height: 60px; display: flex; align-items: center; padding: 0 16px; '
                f'border-bottom: 1px solid {p["rule"]};">'
                f'<span style="font-size: 16px; font-weight: 700; letter-spacing: -0.01em;">Codemit</span>'
                f'<span style="font-size: 12px; color: {p["att"]}; margin-left: 7px;">운영자</span></div>'
                f'<div style="display: flex; flex-direction: column; gap: 18px; padding: 18px 0;">{"".join(groups)}</div>'
                f'<div style="margin-top: auto; padding: 14px 16px; border-top: 1px solid {p["rule"]}; '
                f'font-size: 12px; color: {p["muted"]};">codemit-op · 상위 등급<br>'
                f'<span style="color: {p["dim"]}; font-size: 11.5px;">로그아웃</span></div></div>')

    def topbar(self, crumb, title, actions="", note=None):
        p = self.p
        right = f'<div style="display: flex; gap: 8px;">{actions}</div>' if actions else ""
        sub = (f'<div style="font-size: 12.5px; color: {p["muted"]}; margin-top: 5px;">{note}</div>'
               if note else "")
        return (f'<div style="display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; '
                f'padding: 22px 32px 16px; border-bottom: 1px solid {p["rule"]}; background: {p["surface"]};">'
                f'<div><div style="font-size: 10.5px; letter-spacing: 0.1em; color: {p["faint"]};">{crumb}</div>'
                f'<div style="font-size: 19px; font-weight: 600; letter-spacing: -0.01em; margin-top: 4px;">{title}</div>'
                f'{sub}</div>{right}</div>')

    def page(self, active, crumb, title, inner, actions="", note=None, w=1440, h=1020):
        main = (f'<div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">'
                f'{self.topbar(crumb, title, actions, note)}'
                f'<div style="flex: 1; display: flex; flex-direction: column; gap: 18px; padding: 22px 32px 32px;">{inner}</div></div>')
        return self.frame(self.nav(active) + main, w=w, h=h)

    # --- 조각 ---------------------------------------------------------------
    def btn(self, label, primary=False, small=True):
        p = self.p
        pad = "6px 12px" if small else "9px 16px"
        fs = "12.5px" if small else "13.5px"
        if primary:
            return (f'<div style="padding: {pad}; background: {p["ink"]}; color: {p["paper"]}; font-size: {fs}; '
                    f'font-weight: 500; white-space: nowrap;">{label}</div>')
        return (f'<div style="padding: {pad}; border: 1px solid {p["rule"]}; background: {p["surface"]}; '
                f'font-size: {fs}; color: {p["ink"]}; white-space: nowrap;">{label}</div>')

    def badge(self, label, tone="neutral"):
        """대기 상태는 **중립**이다 — 전부 「대기」이지 실패가 아니라서 주의색을 쓰지 않는다.
        가르는 것은 색이 아니라 글자다."""
        p = self.p
        color = {"neutral": p["muted"], "ver": p["ver"], "att": p["att"]}[tone]
        border = {"neutral": p["rule"], "ver": p["ver"], "att": p["att"]}[tone]
        return (f'<span style="display: inline-block; border: 1px solid {border}; color: {color}; '
                f'font-size: 11px; line-height: 15px; padding: 1px 7px; white-space: nowrap;">{label}</span>')

    def card(self, inner, title=None, hint=None, pad="0"):
        p = self.p
        head = ""
        if title:
            h = (f'<span style="font-size: 12.5px; color: {p["dim"]}; font-weight: 400; margin-left: 9px;">{hint}</span>'
                 if hint else "")
            head = (f'<div style="padding: 12px 15px; border-bottom: 1px solid {p["rule"]}; font-size: 14px; '
                    f'font-weight: 600;">{title}{h}</div>')
        return (f'<div style="border: 1px solid {p["rule"]}; background: {p["surface"]};">{head}'
                f'<div style="padding: {pad};">{inner}</div></div>')

    def table(self, cols, rows, widths=None):
        """행이 촘촘한 표. 숫자는 고정폭으로 세로줄이 맞는다."""
        p = self.p
        widths = widths or [None] * len(cols)
        head = "".join(
            f'<div style="{"flex: 1; min-width: 0;" if w is None else f"width: {w}px; flex-shrink: 0;"} '
            f'font-size: 11px; letter-spacing: 0.06em; color: {p["faint"]};">{c}</div>'
            for c, w in zip(cols, widths))
        out = [f'<div style="display: flex; gap: 14px; padding: 9px 15px; border-bottom: 1px solid {p["rule"]};">{head}</div>']
        for i, row in enumerate(rows):
            cells = "".join(
                f'<div style="{"flex: 1; min-width: 0;" if w is None else f"width: {w}px; flex-shrink: 0;"} '
                f'font-size: 13px; line-height: 21px; overflow: hidden; text-overflow: ellipsis; '
                f'white-space: nowrap;">{cell}</div>'
                for cell, w in zip(row, widths))
            bg = p["zebra"] if i % 2 else "transparent"
            out.append(f'<div style="display: flex; gap: 14px; align-items: center; padding: 9px 15px; '
                       f'border-bottom: 1px solid {p["rule"]}; background: {bg};">{cells}</div>')
        return "".join(out)

    def mono(self, text, color=None, size="13px", weight="400"):
        return (f'<span style="font-family: {MONO}; font-size: {size}; font-weight: {weight}; '
                f'color: {color or self.p["ink"]};">{text}</span>')

    def muted(self, text, size="12.5px"):
        return f'<span style="font-size: {size}; color: {self.p["muted"]};">{text}</span>'

    def note(self, text, tone="muted"):
        p = self.p
        color = {"muted": p["muted"], "dim": p["dim"], "att": p["att"]}[tone]
        return f'<div style="font-size: 12px; color: {color}; line-height: 1.65;">{text}</div>'

    def field(self, label, value, mono=False, hint=None):
        p = self.p
        ff = f"font-family: {MONO};" if mono else ""
        h = f'<div style="font-size: 11.5px; color: {p["dim"]}; margin-top: 4px;">{hint}</div>' if hint else ""
        return (f'<div style="display: flex; flex-direction: column; gap: 5px;">'
                f'<div style="font-size: 11.5px; color: {p["dim"]};">{label}</div>'
                f'<div style="border: 1px solid {p["rule"]}; padding: 8px 11px; font-size: 13px; {ff} '
                f'background: {p["paper"]}; color: {p["ink"]};">{value}</div>{h}</div>')


def write(name, html):
    open(name + ".dc.html", "w", encoding="utf-8").write(HEAD + html + TAIL)
    print("썼다", name + ".dc.html")
