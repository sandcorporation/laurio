# -*- coding: utf-8 -*-
# 「권장 기한·마감」 시안 검토 페이지 — 합의한 규칙 + 화면 일곱 장 + 장마다 「무엇이 달라지나」.
# `python3 build_review.py` 가 `review.html` 을 쓴다. 화면은 gen.py 의 SCREENS 에서 온다.
import sys, os
V2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "classroom-v2")
sys.path.insert(0, V2)
from _lib import frame, header
from build_review import CSS, JS
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location('deadline_gen', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gen.py'))
_mod = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod)
SCREENS = _mod.SCREENS

NOTES = {
    "ProblemEdit": ("문제 편집 · 기한 있음", "1200px", [
        "오른쪽 열, 「상태」 바로 아래에 <b>「기한」 카드</b>. 권장 기한과 마감이 각각 날짜·시각 칸 하나씩이다. 날짜를 고르면 시각은 23:59 로 채워지고 바꿀 수 있다. 시간대는 강사 브라우저의 로컬이다 — 지금 강의실이 시각을 그리는 방식과 같다.",
        "둘 다 선택이고 「비우기」로 지운다. 둘 다 있을 때 권장이 마감 뒤면 「저장」이 그 칸을 붉게 두고 저장하지 않는다(그 상태는 그리지 않았다).",
        "「저장」은 머리 오른쪽 그대로 — 제목·설명·형식·모델과 같은 폼이다. 날짜만 바꿔도 저장을 눌러야 한다.",
    ]),
    "ProblemEditEmpty": ("문제 편집 · 기한 없음", "1200px", [
        "새 문제와 기존 문제 전부의 기본 모습이다. 빈 칸은 자리만 보여 주고 아무것도 막지 않는다 — 지금과 똑같이 동작한다.",
        "템플릿·클래스 복사·다른 클래스의 문제 복사로 들어온 문제도 이 상태로 시작한다(날짜는 따라오지 않는다).",
    ]),
    "Class": ("클래스 상세 · 문제 표", "1200px", [
        "줄 높이를 늘리지 않는다 — 문제 이름 <b>옆에 한 줄</b>로 「마감 10/27」만 작게 붙는다. 권장 기한은 표에 두지 않는다(편집 화면과 참여자 화면에 있다). 지난 마감은 흐려질 뿐 붉지 않다 — 강사에게 지난 마감은 경고가 아니라 사실이다.",
        "표의 열과 폭은 v2 그대로다 — 오른쪽 채점·최근 제출 카드가 밀리지 않는다.",
        "순서는 강사가 정한 그대로다 — 마감순으로 다시 정렬하지 않는다.",
    ]),
    "Roster": ("클래스 상세 · 참여자 격자", "1200px", [
        "문제 머리 아래에 <b>마감 날짜 한 줄</b>(「~10/27」). 지난 것은 흐리게. 기한이 없는 문제는 빈 줄로 높이만 맞춘다.",
        "권장 기한 뒤에 낸 시도는 칸 표식의 <b>오른쪽 아래 점</b>으로 표시한다. 통과·미통과 표식 위에 겹치므로 「통과했지만 늦었다」가 한 칸에 읽힌다. 범례에 「권장 기한 뒤 제출」 한 항목이 는다.",
        "늦음은 그 사람의 <b>마지막 시도</b> 기준이다(격자 칸이 보여 주는 상태가 마지막 시도의 것이라서). 마감 뒤에는 새 시도가 없으니 칸은 마감 전 마지막 상태 그대로 남는다.",
    ]),
    "Mine": ("참여자 · 문제 목록", "1200px", [
        "줄마다 제목 다음에 기한·시도·상태가 <b>고정 폭 세 칸, 한 줄</b>로 선다 — 줄이 달라도 칸이 맞고 높이가 늘지 않는다. 권장과 마감은 <b>각각 고정 폭 칸</b>이라 한쪽이 없거나 글자가 길어도 늘 같은 자리에 선다. 칩은 상태 배지 하나뿐이다.",
        "권장 기한 뒤에 낸 문제는 그 상태 배지의 글자가 <b>「통과 · 늦음」·「미통과 · 늦음」</b>이 된다 — 배지를 하나 더 붙이지 않는다.",
        "<b>붉은 글자는 아직 통과하지 못했는데 마감이 지난 줄에만</b> — 「JavaScript 배열 다루기」. 이미 통과한 문제의 지난 마감은 전부 흐리게 — 그 사람에게는 끝난 일이다. 마감이 지난 문제도 같은 자리에 그대로 있다. 줄을 누르면 아래 「제출 · 마감 지남」 화면이다.",
    ]),
    "Submit": ("참여자 · 제출 · 마감 전", "1200px", [
        "「제출」 카드 머리 아래에 <b>권장 기한과 마감 두 줄</b>(라벨 왼쪽, 값 오른쪽). 권장이 지났으면 그 줄이 흐려진다(여기서는 10/24 가 아직 안 지난 상태).",
        "「내 시도」의 시도 줄도 같은 배지 하나 — 권장 기한 뒤에 낸 시도는 「미통과 · 늦음」처럼 글자가 는다. 지금 날짜 기준으로 셈하므로 강사가 권장 기한을 미루면 이 배지는 사라진다.",
        "제출 칸·버튼은 지금과 같다. 안내 문장은 없다 — 라벨·값·배지만.",
    ]),
    "SubmitClosed": ("참여자 · 제출 · 마감 지남", "1200px", [
        "「제출」 카드 머리에 <b>「마감 지남」</b> 배지, 그 아래 마감 시각 한 줄. 끌어다 놓기·저장소 칸·「제출하기」는 흐려진 채 남는다 — 무엇이 막혔는지는 보이되 누를 수 없다.",
        "설명·체크리스트·지난 시도와 판정은 전부 그대로 읽는다 — 제출과 판정은 참여자의 기록이다(숨김과 같은 원칙).",
        "강사·공동 강사가 「학생 화면으로」 들어오면 이 카드가 막히지 않는다 — 강사는 언제나 낸다.",
        "백엔드는 제출 POST 에 새 차단 이유 하나(마감 지남)를 더하고, 조회 응답의 <span class=\"kbd\">submit_blocked_reason</span> 으로 미리 알린다 — 보관·내보냄·숨김과 같은 길이다.",
    ]),
}
ORDER = ["ProblemEdit", "ProblemEditEmpty", "Class", "Roster", "Mine", "Submit", "SubmitClosed"]

RULES = [
    ("대상", "Class 안의 <b>Problem(문제)</b> 하나하나. 클래스 전체의 기한은 없다."),
    ("두 날짜", "<b>권장 기한</b>과 <b>마감</b>. 각각 선택이고, 둘 다 있으면 권장 ≤ 마감. 시각까지 저장하고 화면은 날짜·시각을 고르되 시각 기본값은 23:59(브라우저 로컬)."),
    ("마감이 지나면", "참여자는 새 시도를 낼 수 없다. 문제는 목록의 같은 자리에 「마감 지남」으로 남고, 지난 시도·판정은 그대로 본다. 강사·공동 강사는 언제나 낸다."),
    ("권장 기한이 지나면", "낼 수 있다. 그 뒤에 낸 시도는 「늦음」 — 참여자 본인 화면과 강사 격자 둘 다에 보인다."),
    ("붉은 글자", "참여자가 <b>아직 통과하지 못한 문제의 지난 마감</b>에만. 이미 통과한 문제와 강사 화면의 지난 마감은 흐린 글자다 — 붉음은 「네가 할 일이 막혔다」는 뜻 하나로 둔다."),
    ("다시 셈한다", "「늦음」·「마감 지남」은 시도에 박지 않고 지금 날짜 기준으로 셈한다. 날짜는 언제든 앞뒤로 옮길 수 있다 — 체크리스트를 고치면 달성률만 다시 셈하는 것과 같은 결."),
    ("따라가지 않는다", "템플릿·클래스 복사·다른 클래스의 문제 복사에서 날짜는 비운다. 공모전 문제에도 강사가 둔다(공모전 자체의 마감과 별개)."),
    ("범위 밖", "알림(마감 임박·마감 지남)은 다음 티켓. 백엔드 회전 유예 같은 다른 일과 섞지 않는다."),
    ("용어집", "Problem 항목의 「마감이 없고」를 고치고 「권장 기한」·「마감」·「늦음」을 화면 말로 올린다. 피하는 말의 「마감」은 「숨김을 마감이라 부르지 않는다」로 좁힌다. 짧은 ADR 하나."),
]

def screen_html(name):
    inner, h, w = SCREENS[name]
    title, width, notes = NOTES[name]
    be = any("백엔드" in n for n in notes)
    tag = '<span class="tag be">백엔드 변경 포함</span>' if be else ""
    li = "".join(f"<li>{n}</li>" for n in notes)
    return (f'<section class="screen" id="s-{name}"><div class="meta"><h2 style="margin:0">{title}</h2>'
            f'<span class="tag">{width}</span>{tag}</div>'
            f'<div class="shot"><div class="shot-inner">{frame(header() + inner, h, w)}</div></div>'
            f'<ul class="notes">{li}</ul></section>')

def build():
    toc = " ".join(f'<a href="#s-{n}">{NOTES[n][0]}</a>' for n in ORDER)
    rules = "".join(f'<li><b>{k}.</b> {v}</li>' for k, v in RULES)
    page = (
        '<title>강의실 기한 시안</title>\n'
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap">\n'
        + CSS.replace("padding-inline:16px", "padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))") +
        '<div class="wrap"><div class="prose">'
        '<div class="eyebrow">Codemit 클래스 · 2026-10-21</div><h1>강의실 기한 시안</h1>'
        '<p>문제마다 <b>권장 기한</b>과 <b>마감</b>을 둔다. v2 시안(2026-10-14)의 화면에서 기한이 닿는 일곱 장만 다시 그렸다 — '
        '색·서체·괘선·조각은 v2 와 같고, 달라진 자리는 장마다 아래에 적었다.</p>'
        '<h3 style="margin-top:20px">합의한 규칙</h3><ul>' + rules + '</ul>'
        f'<div class="toc">{toc}</div>'
        '</div><hr class="rule">'
        + "".join(screen_html(n) for n in ORDER)
        + '<hr class="rule"><div class="prose"><h2 style="margin-top:0">코드가 따라가려면</h2>'
        '<h3>백엔드</h3><ul>'
        '<li><span class="kbd">Problem</span> 에 nullable 시각 둘(권장 기한·마감). 만들기·고치기 API 와 MCP 의 <span class="kbd">create_problem</span>·<span class="kbd">update_problem</span> 이 같은 필드를 받는다. 둘 다 있으면 권장 ≤ 마감을 422 로 지킨다.</li>'
        '<li>제출 POST 의 차단 이유에 「마감 지남」 하나 — 순서는 보관 → 내보냄 → 숨김 → 마감. 강사·공동 강사는 건너뛴다. 조회 응답의 <span class="kbd">submit_blocked_reason</span> 도 같은 값을 낸다.</li>'
        '<li>시도·격자·문제 목록 응답에 「늦음」을 <b>계산해서</b> 싣는다(제출 시각 &gt; 권장 기한). 저장하지 않는다.</li>'
        '<li>템플릿 공개·클래스 복사·문제 복사가 두 필드를 비운다.</li>'
        '</ul><h3>강의실 앱</h3><ul>'
        '<li>문제 편집: 「기한」 카드(날짜·시각 입력 둘, 비우기, 순서 검사).</li>'
        '<li>문제 표·격자 머리·참여자 목록·제출 카드: 기한 표기 조각 하나를 나눠 쓴다(권장 흐리게 · 마감 보통 · 지난 마감 붉은 배지).</li>'
        '<li>격자 칸의 늦음 점, 시도 줄과 목록 줄의 「늦음」 배지, 제출 카드의 「마감 지남」 상태.</li>'
        '</ul><h3>문서</h3><ul>'
        '<li><span class="kbd">CONTEXT.md</span> Problem 항목, <span class="kbd">docs/features/classroom.md</span> 의 「마감을 넣을 자리는 애초에 없다」·「마감도 시도 횟수 상한도 없어」, 모델 docstring 의 「마감이 없다」, 짧은 ADR 하나.</li>'
        '</ul></div></div>' + JS
    )
    open("review.html", "w", encoding="utf-8").write(page)
    print("wrote review.html", len(page))

if __name__ == "__main__":
    build()
