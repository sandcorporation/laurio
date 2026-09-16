# 운영자 앱 시안 넷 + 다크 한 장(2026-09-16). `python3 gen.py` 로 다시 만든다.
from _lib import DARK, LIGHT, Comp, write


def home(c: Comp) -> str:
    queue_rows = [
        ["심판 대기 중인 이의", c.mono("4", c.p["ink"], "15px", "600"), c.muted("가장 오래 밀린 것 3일"), c.btn("보기")],
        ["지급 대기", c.mono("7", c.p["ink"], "15px", "600"), c.muted("신원 2 · 셀러 3 · 이체 2"), c.btn("보기")],
        ["신고된 템플릿", c.mono("2", c.p["ink"], "15px", "600"), c.muted("검토하면 목록에서 사라진다"), c.btn("보기")],
    ]
    changes = [
        ["플랫폼 정책", "수수료율 300 → 280bps", c.mono("codemit-op"), c.mono("09-16 04:12")],
        ["산출물 종류", "「관리자 페이지」 최소 제안가 올림", c.mono("codemit-op"), c.mono("09-15 21:40")],
        ["개최 권한", "계정 #12 에 부여 — 사내 스터디 운영", c.mono("codemit-op"), c.mono("09-15 18:03")],
    ]
    return (
        c.card(c.table(["큐", "건수", "", ""], queue_rows, [260, 70, None, 70])) +
        f'<div style="display: flex; gap: 18px; align-items: flex-start;">'
        f'<div style="flex: 1; min-width: 0;">'
        + c.card(c.table(["무엇", "무슨 값이 어떻게", "누가", "언제"], changes, [110, None, 110, 110]),
                 title="최근 변경 이력", hint="바꾼 사람과 시각이 남는다 — 지울 수 없다") +
        f'</div><div style="width: 360px; flex-shrink: 0; display: flex; flex-direction: column; gap: 18px;">'
        + c.card(
            f'<div style="padding: 14px 15px; display: flex; flex-direction: column; gap: 10px;">'
            f'{c.note("이 화면은 <b>사람이 판단할 일</b>만 센다 — 스캔이 알아서 하는 일(마감 전이·채점·환불·배분)은 여기 오지 않는다.")}'
            f'{c.note("숫자가 0이면 그 줄은 「비었다」로 남는다 — 줄 자체가 사라지지 않아, 큐가 있다는 사실은 늘 보인다.", "dim")}'
            f'</div>', title="이 홈이 세는 것") +
        c.card(
            f'<div style="padding: 14px 15px; display: flex; flex-direction: column; gap: 9px;">'
            f'<div style="display: flex; justify-content: space-between;">{c.muted("오늘 심판")}{c.mono("3건")}</div>'
            f'<div style="display: flex; justify-content: space-between;">{c.muted("오늘 지급 승인")}{c.mono("1건")}</div>'
            f'<div style="display: flex; justify-content: space-between; padding-top: 9px; border-top: 1px solid ' + c.p["rule"] + f';">{c.muted("대기 중 가장 오래된 것")}{c.mono("3일", c.p["ink"])}</div>'
            f'</div>', title="오늘") +
        f'</div></div>')


def appeal(c: Comp) -> str:
    left = (
        c.card(
            f'<div style="padding: 15px; display: flex; flex-direction: column; gap: 13px;">'
            f'<div style="display: flex; gap: 10px; align-items: center;">{c.badge("심판 대기")}{c.muted("접수 3일 전 · 공모전 #41 「할 일 앱 만들기」")}</div>'
            f'<div style="font-size: 13.5px; line-height: 1.75;">체크리스트 3번(로그인 유지)을 구현했는데 미충족으로 적혔습니다. '
            f'소스의 <span style="font-family: \'IBM Plex Mono\', monospace;">auth/session.ts</span> 에 그 코드가 있습니다.</div>'
            f'{c.note("제출자가 쓴 사유 그대로다 — 운영자가 고쳐 쓰지 않는다.", "dim")}'
            f'</div>', title="이의 사유", hint="제출자 #128") +
        c.card(
            c.table(["체크리스트", "AI 판정", "AI 가 적은 사유"],
                    [["1. 할 일을 추가·완료할 수 있다", c.badge("충족", "ver"), c.muted("addTodo·toggleTodo 가 있다")],
                     ["2. 목록이 저장된다", c.badge("충족", "ver"), c.muted("localStorage 에 쓴다")],
                     ["3. 로그인이 유지된다", c.badge("미충족", "att"), c.muted("세션 복원 코드를 찾지 못했다")]],
                    [None, 80, 360]),
            title="채점 결과", hint="점수 67% · 모델 gpt-5-mini") +
        c.card(
            f'<div style="padding: 15px; display: flex; flex-direction: column; gap: 10px;">'
            f'<div style="display: flex; gap: 8px; flex-wrap: wrap;">{c.btn("소스 내려받기")}{c.btn("저장소 열기")}{c.btn("AI 채점 원문")}</div>'
            f'{c.note("소스를 열어 본 사실은 기록된다(ADR-0027) — 제출자에게도 보인다.", "dim")}'
            f'</div>', title="무엇을 보고 판단하나"))
    right = (
        c.card(
            f'<div style="padding: 15px; display: flex; flex-direction: column; gap: 13px;">'
            f'<div style="display: flex; flex-direction: column; gap: 7px;">'
            f'<div style="display: flex; align-items: center; gap: 9px; border: 1px solid {c.p["ink"]}; padding: 10px 12px;">'
            f'<div style="width: 11px; height: 11px; border: 1px solid {c.p["ink"]}; display: flex; align-items: center; justify-content: center;">'
            f'<div style="width: 6px; height: 6px; background: {c.p["ink"]};"></div></div>'
            f'<div><div style="font-size: 13px; font-weight: 500;">인용 — 점수를 다시 매긴다</div>'
            f'<div style="font-size: 11.5px; color: {c.p["dim"]}; margin-top: 3px;">그 체크리스트만 충족으로 바꾼다</div></div></div>'
            f'<div style="display: flex; align-items: center; gap: 9px; border: 1px solid {c.p["rule"]}; padding: 10px 12px;">'
            f'<div style="width: 11px; height: 11px; border: 1px solid {c.p["rule"]};"></div>'
            f'<div style="font-size: 13px;">기각 — 판정을 유지한다</div></div></div>'
            + c.field("사유 (필수)", "3번은 세션 복원이 아니라 토큰 재발급만 있어…", hint="제출자에게 그대로 보인다 — 심판자 이름은 보이지 않는다")
            + f'<div style="display: flex; gap: 8px;">{c.btn("심판 확정", primary=True, small=False)}{c.btn("나중에", small=False)}</div>'
            f'{c.note("확정하면 되돌릴 수 없다 — 원장에 남고 점수도 그 자리에서 바뀐다.", "att")}'
            f'</div>', title="심판") +
        c.card(
            c.table(["언제", "무엇"],
                    [[c.mono("09-13 10:02"), c.muted("제출자가 이의 접수")],
                     [c.mono("09-13 10:02"), c.muted("자동 배정 — 심판 대기")],
                     [c.mono("09-16 04:20"), c.muted("운영자가 소스를 열어 봄")]],
                    [110, None]),
            title="감사 추적", hint="append-only"))
    return (f'<div style="display: flex; gap: 18px; align-items: flex-start;">'
            f'<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 18px;">{left}</div>'
            f'<div style="width: 420px; flex-shrink: 0; display: flex; flex-direction: column; gap: 18px;">{right}</div></div>')


def payouts(c: Comp) -> str:
    tabs = []
    for label, on, count in [("전체", True, "7"), ("신원 대기", False, "2"), ("셀러 대기", False, "3"), ("이체 대기", False, "2")]:
        bg = c.p["ink"] if on else c.p["surface"]
        fg = c.p["paper"] if on else c.p["ink"]
        border = c.p["ink"] if on else c.p["rule"]
        tabs.append(f'<div style="border: 1px solid {border}; background: {bg}; color: {fg}; padding: 6px 13px; '
                    f'font-size: 12.5px;">{label} <span style="font-family: \'IBM Plex Mono\', monospace; opacity: 0.7;">{count}</span></div>')
    rows = [
        [c.mono("#41"), "할 일 앱 만들기", "개발자 #128", c.mono("1,120,000"), c.badge("신원 대기"), c.muted("개발자 차례 · 3일째"), c.btn("보기")],
        [c.mono("#41"), "할 일 앱 만들기", "개발자 #131", c.mono("480,000"), c.badge("셀러 대기"), c.muted("지급대행사 심사 · 2일째"), c.btn("보기")],
        [c.mono("#38"), "사내 위키 개편", "개발자 #094", c.mono("2,300,000"), c.badge("이체 대기"), c.muted("재시도 가능 · 오늘"), c.btn("보기")],
        [c.mono("#38"), "사내 위키 개편", "개발자 #101", c.mono("760,000"), c.badge("신원 대기"), c.muted("개발자 차례 · 1일째"), c.btn("보기")],
        [c.mono("#36"), "랜딩 리디자인", "개발자 #077", c.mono("990,000"), c.badge("셀러 대기"), c.muted("지급대행사 심사 · 5일째"), c.btn("보기")],
    ]
    return (
        f'<div style="display: flex; gap: 8px;">{"".join(tabs)}</div>' +
        c.card(c.table(["공모전", "이름", "받는 사람", "금액", "무엇을 기다리나", "누구 차례", ""],
                       rows, [60, None, 110, 110, 96, 190, 60])) +
        f'<div style="display: flex; gap: 18px; align-items: flex-start;">'
        + c.card(f'<div style="padding: 14px 15px; display: flex; flex-direction: column; gap: 9px;">'
                 f'{c.note("<b>대기는 실패가 아니다</b> — 셋 다 「누군가의 차례」이고 색으로 겁주지 않는다. 가르는 것은 배지의 글자와 「누구 차례」 칸이다.")}'
                 f'{c.note("정의되지 않은 조합은 운영자 차례다 — 돈은 움직이지 않고 사람이 본다(ADR-0020).", "dim")}</div>',
                 title="이 표를 읽는 법")
        + f'</div>')


def notice(c: Comp) -> str:
    steps = []
    for i, (label, state) in enumerate([("받는 사람", "done"), ("작성", "current"), ("확인", "todo")], start=1):
        color = c.p["ink"] if state != "todo" else c.p["dim"]
        weight = "600" if state == "current" else "400"
        under = f'border-bottom: 2px solid {c.p["att"]};' if state == "current" else ""
        steps.append(f'<div style="font-size: 13px; color: {color}; font-weight: {weight}; padding-bottom: 4px; {under}">'
                     f'{i}. {label}</div>')
    history = [
        [c.mono("#128"), "kim@example.com", "무료 공모전 수상을 축하드립니다", c.mono("codemit-op"), c.mono("09-16 03:12"), c.badge("읽음", "ver"), c.btn("이미지")],
        [c.mono("#094"), "lee@example.com", "제출 자료 확인 부탁드립니다", c.mono("codemit-op"), c.mono("09-14 11:40"), c.badge("안 읽음"), ""],
    ]
    return (
        f'<div style="display: flex; gap: 26px; align-items: flex-end;">{"".join(steps)}</div>' +
        f'<div style="display: flex; gap: 18px; align-items: flex-start;">'
        f'<div style="flex: 1; min-width: 0;">'
        + c.card(
            f'<div style="padding: 15px; display: flex; flex-direction: column; gap: 14px;">'
            f'<div style="display: flex; align-items: center; justify-content: space-between; border: 1px solid {c.p["rule"]}; '
            f'background: {c.p["paper"]}; padding: 10px 12px;">'
            f'<div style="font-size: 13px;">kim@example.com <span style="color: {c.p["dim"]};">· 참가자 #128</span></div>'
            f'{c.btn("다른 사람 선택")}</div>'
            + c.field("제목 (필수)", "무료 공모전 수상을 축하드립니다")
            + c.field("본문", "상품으로 치킨 기프티콘을 보내 드립니다. 이미지를 저장해 사용하세요.")
            + f'<div style="display: flex; flex-direction: column; gap: 7px;">'
            f'<div style="font-size: 11.5px; color: {c.p["dim"]};">이미지 (선택 · png·jpeg·webp)</div>'
            f'<div style="display: flex; align-items: center; gap: 11px; border: 1px solid {c.p["rule"]}; padding: 10px 12px; background: {c.p["paper"]};">'
            f'<div style="width: 64px; height: 40px; background: {c.p["surface"]}; border: 1px solid {c.p["rule"]}; '
            f'display: flex; align-items: center; justify-content: center; font-size: 11px; color: {c.p["dim"]};">미리보기</div>'
            f'<div style="flex: 1; font-size: 12.5px;">gifticon.png <span style="color: {c.p["dim"]};">· 214KB</span></div>'
            f'{c.btn("떼기")}</div></div>'
            f'<div style="display: flex; gap: 8px;">{c.btn("확인으로", primary=True, small=False)}{c.btn("취소", small=False)}</div>'
            f'</div>', title="운영팀 알림 보내기", hint="한 번에 한 사람")
        + f'</div>'
        f'<div style="width: 380px; flex-shrink: 0; display: flex; flex-direction: column; gap: 18px;">'
        + c.card(f'<div style="padding: 14px 15px; display: flex; flex-direction: column; gap: 9px;">'
                 f'{c.note("<b>이미지는 비공개 저장소에 둔다</b> — 받는 사람과 보낸 운영자만 짧게 유효한 주소를 받는다. 목록 응답에는 주소가 실리지 않는다.")}'
                 f'{c.note("보낸 뒤에는 고칠 수도 지울 수도 없다 — 잘못 보냈으면 새 알림으로 바로잡는다.", "att")}'
                 f'{c.note("문자·알림톡으로 가지 않는다. 앱 안 알림으로만 보인다.", "dim")}</div>',
                 title="이 화면의 약속")
        + f'</div></div>' +
        c.card(c.table(["받는 사람", "이메일", "제목", "보낸 운영자", "보낸 시각", "읽음", ""],
                       history, [80, 170, None, 110, 110, 70, 60]),
               title="발송 이력", hint="최신순 · 고칠 수 없다"))


for name, palette, builder, crumb, title, note_text, active in [
    ("Home", LIGHT, home, "운영자 · 할 일", "할 일", "사람이 판단할 일만 모인다 — 스캔이 도는 일은 여기 오지 않는다.", "이의 심판"),
    ("Appeal", LIGHT, appeal, "할 일 · 이의 심판", "이의 #77", "확정하면 되돌릴 수 없다 — 원장에 남는다.", "이의 심판"),
    ("Payouts", LIGHT, payouts, "할 일 · 지급", "지급 대기 7건", "대기는 실패가 아니다 — 누구 차례인지가 이 표의 핵심이다.", "지급"),
    ("OperatorNotice", LIGHT, notice, "운영 · 운영팀 알림", "운영팀 알림", "앱 안 알림으로만 간다 — 이미지는 비공개 저장소에 둔다.", "운영팀 알림"),
    ("Payouts.dark", DARK, payouts, "할 일 · 지급", "지급 대기 7건", "같은 토큰의 다크 값 — 상태는 여전히 글자로 가른다.", "지급"),
]:
    comp = Comp(palette)
    write(name, comp.page(active, crumb, title, builder(comp), note=note_text))
