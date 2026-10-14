# -*- coding: utf-8 -*-
# 시안 v2 검토 페이지 — 흐름 지도 + 화면 열두 장 + 화면마다 「지금과 무엇이 다른가」.
# `python3 build_review.py` 가 `review.html` 을 쓴다. 화면 자체는 gen.py 의 SCREENS 에서 온다.
import html
from gen import SCREENS, header

NOTES = {
    "Home": ("내 클래스", [
        "행마다 참여자 수·문제 수·달성률 막대·마지막 제출이 보인다 — 지금은 「만든 날짜」뿐이라 클래스가 셋만 돼도 어느 게 살아 있는지 열어 봐야 안다. <b>백엔드 집계 필드가 필요하다.</b>",
        "「내가 가르치는 클래스」를 먼저, 「참여 중인 클래스」를 다음에 둔다 — 지금 순서(참여 → 가르침)는 참여자로만 속한 사람 기준이라 강사에겐 자기 클래스가 아래로 밀린다. 참여자로만 속한 사람에겐 지금처럼 참여 목록만 보이면 된다.",
        "참여 중인 클래스 행에는 달성률 대신 「3/6 통과」와 「문제 풀기」 — 참여자가 보는 것은 수업의 달성률이 아니라 자기 진도다.",
        "보관 행의 주 버튼은 #331 결정대로 「지난 기록 보기」를 유지한다.",
    ]),
    "Class": ("클래스 상세 · 문제", [
        "<b>문제 목록이 첫 화면에 들어온다.</b> 지금은 보관 안내·키 배너·가입 링크 카드·강사 카드(초대·떠나기)에 밀려 900px 아래에 있다. 강사 카드는 「강사」 탭으로, 보관은 설정으로 옮긴다.",
        "머리 오른쪽에 참여자·문제·평균 달성률 통계. 「참여자 명단」·「복사해서 새로 열기」 버튼은 각각 참여자 탭과 설정으로 가고 머리에는 「클래스 설정」만 남는다.",
        "흩어진 배너 넷(키 없음·거부됨·크레딧 소진·서버 연결 불가)이 오른쪽 「채점」 카드의 상태 한 줄이 된다 — 정상일 때는 모델·누적 채점 횟수·사용량이 보이고, 문제가 있을 때만 붉어진다.",
        "문제 행: 달성률 막대(60%↑ 초록 · 30%↓ 빨강)·통과 n/N·필수 항목 수·최근 제출. 「위로/아래로」 버튼 둘은 ⋮ 메뉴(또는 끌기)로 접는다 — 매일 보는 표에서 행마다 버튼 셋은 소음이다.",
        "「최근 제출」 카드 — 강사가 이 화면을 여는 이유의 대부분은 「누가 방금 냈나」다. <b>백엔드 엔드포인트가 필요하다.</b>",
        "가입 링크는 한 줄 띠. 「다시 뽑기」는 위험 행동이라 글자 링크로 낮춘다.",
    ]),
    "ClassEmpty": ("클래스 상세 · 방금 연 클래스", [
        "새 클래스는 채점 연결 없이 열린다. 지금은 「키가 없다」 붉은 배너 하나가 그 사실을 말하는데, 그 다음에 뭘 해야 하는지는 말하지 않는다.",
        "「시작하기」 카드가 순서를 준다 — 채점 연결 → 첫 문제 → 가입 링크. 설명 문장 없이 단계 이름과 버튼만. 셋을 마치면 사라지고 그 자리에 「채점」 카드가 들어온다.",
        "빈 문제 목록에서 세 입구(새 문제·템플릿·다른 클래스에서 복사)를 한 번에 보인다.",
    ]),
    "Roster": ("클래스 상세 · 참여자", [
        "<b>참여자 명단(/members)과 격자 탭을 하나로 합친다.</b> 지금은 같은 사람들을 두 화면에서 따로 본다 — 명단은 가입일과 내보내기, 격자는 통과 이력.",
        "표가 카드 폭을 다 쓰고, 행 끝에 「통과 n/8」·「최근 제출」·⋮(내보내기)가 붙는다. 이름 열은 고정.",
        "달성률 행이 색으로 읽힌다. 셀 모양·범례·「설정 필요」 구분은 지금 것을 그대로 쓴다.",
    ]),
    "Instructors": ("클래스 상세 · 강사", [
        "지금 상세 화면 한가운데 있던 강사 목록·공동 강사 초대·소유권 이전·떠나기를 탭 하나로 옮긴다. 학기에 몇 번 안 여는 일이 매일 보는 문제 목록 위에 있을 이유가 없다.",
        "공동 강사의 권한 설명 문장은 화면에 두지 않는다 — 소유자 전용 행동은 공동 강사에게 그 버튼이 안 보이는 것으로 충분하다.",
    ]),
    "Settings": ("클래스 설정", [
        "왼쪽 목차로 여섯 구획을 오간다 — 지금은 한 열 2,000px 을 스크롤한다. 순서는 자주 바꾸는 것부터: 채점 연결 → 기본 모델 → 사용량 → 이름 → 템플릿 공개 → 보관과 삭제.",
        "채점 연결은 상태 한 줄(연결됨·마스킹된 키·「10/02 확인」 — 강사 탭의 「M/D 수락」과 같은 꼴)이 먼저, 바꾸는 폼은 「바꾸기」를 눌러야 열린다 — 지금은 빈 입력 칸이 늘 보여 「키가 없나?」로 읽힌다.",
        "기본 모델은 드롭다운 대신 라디오 표 — 컨텍스트·예상 비용이 나란히 보여 고를 근거가 그 자리에 있다. 비용 표는 접힌 채 그 아래.",
        "<b>채점 예산(토큰 상한)은 뺀다</b>(#629) — 누적 상한이라 학기가 길어지면 반드시 닿고 소유자가 숫자를 올려야 재개되던 것. 대신 「사용량」 구획이 누적 토큰·원화 어림·채점 횟수·1회 평균·어림 몫을 보인다. 지출 상한은 OpenAI 쪽 한도가 맡고, 떨어지면 「크레딧 소진 → 채점 대기」가 받는다. 「보관」을 설정의 마지막 구획으로 옮긴다.",
    ]),
    "ProblemEdit": ("문제 편집", [
        "<b>1200px 에서 두 열.</b> 왼쪽은 글(제목·설명·체크리스트), 오른쪽 300px 은 설정(상태·제출 형식·채점 모델·지침)이 따라온다. 지금은 1840px 이상에서만 옆 레일이 뜨고 그 아래는 한 열 2,000px 이다.",
        "「저장」이 머리 오른쪽에 — 지금은 맨 아래 하나뿐이라 모델만 바꾸고 스크롤해 내려가야 한다. 체크리스트는 지금처럼 즉시 저장.",
        "상태 카드가 전이 버튼(열기·숨기기·다시 열기)을 든다 — 지금은 머리의 「숨기기」 하나가 그 역할을 하는데 왜 붉은지 설명이 없다.",
        "복사·템플릿 공개·삭제는 오른쪽 열 끝의 글자 링크로 — 학기에 한 번 쓰는 일이 카드 셋을 차지했다.",
        "체크리스트 항목은 ⋮⋮ 끌기 손잡이 — 「위로·아래로·삭제」 버튼 셋이 행마다 있던 것을 줄인다.",
    ]),
    "Mine": ("참여자 · 문제 목록", [
        "머리에 「3/6 통과」 진행 막대 — 지금은 문장(「2개 중 0개를 통과했습니다…」)뿐이다.",
        "행마다 제목·시도 횟수·마지막 시도·상태 배지 하나(통과·미통과·채점 중·미제출) — 행 전체가 링크라 버튼은 두지 않는다.",
        "숨겨진 문제 섹션은 지금처럼 접힌 채 아래.",
        "눈썹은 「클래스 이름 · 강사 전원」(「프론트엔드 입문 3기 · 김선우, 박조교」) — 「강사」 낱말 없이 이름만.",
    ]),
    "Submit": ("참여자 · 문제와 제출", [
        "<b>두 열.</b> 오른쪽에 제출 카드와 「이 문제의 진행 3/5」가 따라오고, 왼쪽에 설명·체크리스트·내 시도. 지금은 한 열이라 제출 칸이 체크리스트 아래 900px 에 있다.",
        "체크리스트와 최근 판정을 한 카드로 합친다 — 지금은 「체크리스트」 카드와 「내 시도」 안의 판정이 같은 항목을 두 번 보여 준다. 항목 옆에 지금 상태(충족·미충족)와 사유가 바로 붙는다.",
        "「문제 목록으로」는 머리 오른쪽 버튼 — 지금은 눈썹 위에 홀로 떠 있다. 통과 여부 배지는 제목 옆에.",
        "지난 시도는 한 줄씩, 「판정 보기」로 펼친다. 채점 대기(키 없음·크레딧 소진·서버 연결 불가)일 때는 「제출은 저장됐고 다시 낼 필요 없다」를 같은 줄에 말한다(지금과 같다).",
    ]),
    "Submissions": ("강사 · 제출 현황", [
        "머리에 통과·시도·채점 중·채점 대기 통계. 지금은 시도 전부가 펼쳐진 채 세로로 2,800px 이다.",
        "기본은 「참여자별 최신 시도」 한 줄씩, 「판정」을 눌러 항목별 사유를 펼친다. 「모든 시도」로 전환할 수 있다.",
        "아직 내지 않은 참여자 수를 맨 아래 한 줄로 — 「안 낸 사람」과 「냈는데 채점이 멈춘 사람」이 갈린다.",
    ]),
    "JoinGuest": ("가입 링크 · 로그인 전", [
        "로그인 없이 보는 화면. 가운데 440px 열 하나 — 강사·문제 수·참여자 수와 「로그인하고 가입하기」. 로그인 뒤 이 주소로 돌아오는 것은 지금과 같다(#387). 소스를 올리는 제품이라 폰 화면은 따로 그리지 않는다(v1 의 390px 전제를 버린다).",
    ]),
    "JoinMember": ("가입 링크 · 로그인 뒤", [
        "이름 칸이 카카오 닉네임으로 미리 차 있고 버튼이 「가입하고 문제 보기」 — 가입 뒤 어디로 가는지를 버튼이 말한다.",
    ]),
}

ORDER = ["Home", "ClassEmpty", "Class", "Roster", "Instructors", "Settings", "ProblemEdit", "Submissions", "JoinGuest", "JoinMember", "Mine", "Submit"]

FLOWS = [
    ("강사", [
        ("새 클래스 열기", "이름·강사 이름", "Home"),
        ("시작하기 카드", "채점 연결 → 첫 문제 → 가입 링크", "ClassEmpty"),
        ("문제 만들기", "제목·설명·체크리스트·형식·모델", "ProblemEdit"),
        ("가입 링크 공유", "한 줄 띠에서 복사", "Class"),
        ("제출이 들어온다", "최근 제출 카드 · 알림", "Class"),
        ("막힌 사람 찾기", "달성률 → 참여자 격자 → 제출 현황", "Submissions"),
        ("학기 끝", "설정에서 보관 → 복사해서 새 기수", "Settings"),
    ]),
    ("참여자", [
        ("초대 링크", "클래스 정보 · 로그인", "JoinGuest"),
        ("이름 정하고 가입", "바로 문제 목록으로", "JoinMember"),
        ("문제 고르기", "진행 막대 · 풀기", "Mine"),
        ("제출", "zip 또는 저장소 · 즉시 채점", "Submit"),
        ("판정 읽고 다시 내기", "항목별 사유 · 알림으로 복귀", "Submit"),
        ("통과", "한 번 통과하면 남는다", "Mine"),
    ]),
]

CSS = """
<style>
/* 레이아웃: 읽는 글은 720px 한 열, 화면 시안은 1200px 틀을 보는 폭에 맞춰 축소한다. */
:root{--bg:#F5F3EC;--fg:#17160F;--muted:rgba(23,22,15,.62);--dim:rgba(23,22,15,.45);--rule:#DDD9CE;--surface:#FFFEFA;--accent:#C4442B;--ok:#2E6A4C;
 --sans:Pretendard,"Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#1C1B16;--fg:#EDE9DF;--muted:rgba(237,233,223,.7);--dim:rgba(237,233,223,.5);--rule:#3A3830;--surface:#24231D;--accent:#E0694F;--ok:#6FA98A;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#1C1B16;--fg:#EDE9DF;--muted:rgba(237,233,223,.7);--dim:rgba(237,233,223,.5);--rule:#3A3830;--surface:#24231D;--accent:#E0694F;--ok:#6FA98A;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;line-height:1.65;padding-inline:16px;padding-block:32px 80px}
.wrap{max-width:1200px;margin:0 auto}
.prose{max-width:720px}
h1{font-size:28px;letter-spacing:-.01em;margin:0 0 6px;text-wrap:balance}
h2{font-size:20px;margin:56px 0 10px;letter-spacing:-.005em;text-wrap:balance}
h3{font-size:16px;margin:0 0 6px}
.eyebrow{font-size:11px;letter-spacing:.08em;color:var(--dim);text-transform:uppercase}
p{margin:0 0 12px}
ul{margin:0 0 12px;padding-left:20px}li{margin:4px 0}
.rule{border:0;border-top:1px solid var(--rule);margin:32px 0}
.flow{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 24px}
.flow .step{flex:1 1 150px;min-width:150px;border:1px solid var(--rule);background:var(--surface);padding:10px 12px;position:relative}
.flow .step .n{font-family:var(--mono);font-size:11px;color:var(--dim)}
.flow .step .t{font-weight:600;font-size:14px;margin-top:2px}
.flow .step .d{font-size:12.5px;color:var(--muted);margin-top:2px}
.flow .step a{font-size:11.5px;color:var(--accent);text-decoration:underline;text-underline-offset:3px}
.screen{margin-top:48px}
.screen .meta{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:baseline;margin-bottom:10px}
.shot{border:1px solid var(--rule);overflow:hidden;background:#F5F3EC}
.shot-inner{transform-origin:top left}
.notes{max-width:720px;margin:14px 0 0}
.tag{display:inline-block;border:1px solid var(--rule);font-size:11px;padding:1px 7px;color:var(--dim);vertical-align:middle}
.tag.be{border-color:var(--accent);color:var(--accent)}
.toc{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;margin:16px 0 0}
.toc a{color:var(--muted);text-decoration:underline;text-underline-offset:3px}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.kbd{font-family:var(--mono);font-size:12.5px}
@media (prefers-reduced-motion: reduce){*{transition:none!important}}
</style>
"""

JS = """
<script>
// 1200px 틀을 보는 폭에 맞춰 축소한다 — 가로 스크롤 대신.
function fit(){
  document.querySelectorAll('.shot').forEach(function(box){
    var inner=box.querySelector('.shot-inner'); var frame=inner.firstElementChild;
    var w=parseFloat(frame.style.width); var avail=box.clientWidth;
    var s=Math.min(1, avail/w); inner.style.transform='scale('+s+')';
    inner.style.width=w+'px'; box.style.height=(frame.offsetHeight*s)+'px';
  });
}
window.addEventListener('load',fit); window.addEventListener('resize',fit);
</script>
"""


def flow_html(title, steps):
    out = f'<h3>{title}</h3><div class="flow">'
    for i, (t, d, ref) in enumerate(steps, 1):
        out += f'<div class="step"><div class="n">{i:02d}</div><div class="t">{t}</div><div class="d">{d}</div><a href="#s-{ref}">{NOTES[ref][0]} ↓</a></div>'
    return out + "</div>"


def screen_html(name):
    inner, h, w = SCREENS[name]
    full = inner if name.startswith("Join") else header() + inner
    from _lib import frame
    title, notes = NOTES[name]
    be = any("백엔드" in n for n in notes)
    tag = '<span class="tag be">백엔드 변경 포함</span>' if be else ""
    li = "".join(f"<li>{n}</li>" for n in notes)
    return (f'<section class="screen" id="s-{name}"><div class="meta"><h2 style="margin:0">{title}</h2>'
            f'<span class="tag">{w}px</span>{tag}</div>'
            f'<div class="shot"><div class="shot-inner">{frame(full, h, w)}</div></div>'
            f'<ul class="notes">{li}</ul></section>')


def build():
    toc = " ".join(f'<a href="#s-{n}">{NOTES[n][0]}</a>' for n in ORDER)
    page = (
        '<title>강의실 시안 v2</title>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap">\n'
        + CSS +
        '<div class="wrap"><div class="prose">'
        '<div class="eyebrow">Codemit 클래스 · 2026-10-14</div><h1>강의실 시안 v2</h1>'
        '<p>2026-09-10 시안 뒤에 들어온 기능(공동 강사·채점 연결·템플릿·숨김 문제·공모전 문제)을 다 담되, '
        '화면마다 <b>매일 쓰는 것이 첫 화면에 들어오게</b> 다시 짰다. 색·서체·모서리·괘선은 v1 과 같다 — '
        '<span class="kbd">frontend/app/tokens.css</span> 그대로다.</p>'
        '<h3 style="margin-top:20px">여섯 가지 원칙</h3><ul>'
        '<li><b>자주 하는 일이 위.</b> 문제 목록·제출 칸·채점 상태가 첫 화면에. 학기에 한 번 하는 일(강사 초대·템플릿 공개·보관·삭제)은 탭이나 설정으로.</li>'
        '<li><b>경고는 한 곳에서 한 줄로.</b> 키 없음·거부·크레딧·서버 연결 배너 넷이 「채점」 카드의 상태 한 줄이 된다. 새 클래스는 배너 대신 「시작하기」 순서를 받는다.</li>'
        '<li><b>숫자는 막대와 함께.</b> 달성률·진행은 막대 + %. 60% 이상 초록, 30% 미만 빨강.</li>'
        '<li><b>같은 사람을 두 화면에서 보지 않는다.</b> 참여자 명단과 격자를 합치고, 체크리스트와 최근 판정을 합친다.</li>'
        '<li><b>행마다 버튼 셋을 두지 않는다.</b> 순서 바꾸기·삭제는 ⋮ 메뉴와 끌기로. 주 행동 하나만 채움 버튼.</li>'
        '<li><b>화면에 설명 문장을 두지 않는다.</b> 부제·힌트·안내 문단 없이 라벨·값·버튼만. 무슨 일이 일어나는지는 버튼 이름과 상태 배지가 말한다.</li>'
        '</ul>'
        f'<div class="toc">{toc}</div>'
        '</div><hr class="rule"><div class="prose"><h2 style="margin-top:0">두 흐름</h2>'
        '<p>각 단계가 어느 화면인지 링크로 이어진다.</p></div>'
        + "".join(flow_html(t, s) for t, s in FLOWS)
        + '<hr class="rule">'
        + "".join(screen_html(n) for n in ORDER)
        + '<hr class="rule"><div class="prose"><h2 style="margin-top:0">코드가 따라가려면</h2>'
        '<p>프론트만으로 되는 것과 백엔드가 먼저 열어야 하는 것을 가른다.</p>'
        '<h3>프론트만</h3><ul>'
        '<li>클래스 상세: 통계 바, 채점 카드(배너 넷 → 상태 줄), 한 줄 가입 링크, 문제 표(막대·통과·필수·⋮), 탭 셋(문제·참여자·강사), 빈 클래스의 「시작하기」.</li>'
        '<li>참여자 탭: 명단 + 격자 합치기(두 API 를 한 화면에서), 통과 열, 색 달성률. <span class="kbd">/members</span> 는 이 탭으로 리다이렉트.</li>'
        '<li>설정: 목차, 연결 상태 줄 + 접힌 폼, 모델 라디오 표, 사용량 구획(예산 제거는 #629), 보관 구획.</li>'
        '<li>문제 편집: 1200px 두 열(옆 레일 기준을 1840 → 1200), 머리의 저장, 상태 카드, 링크로 낮춘 복사·공개·삭제.</li>'
        '<li>참여자: 목록의 진행 막대·행 모양, 제출 화면 두 열, 체크리스트 + 판정 합치기, 「문제 목록으로」 자리.</li>'
        '<li>제출 현황: 통계 바, 참여자별 최신 시도 접기, 안 낸 사람 수(격자 API 로 셈).</li>'
        '</ul><h3>백엔드가 먼저</h3><ul>'
        '<li><span class="kbd">GET /classes</span> 행에 참여자 수·문제 수·평균 달성률·마지막 제출 시각. <span class="kbd">/classes/joined</span> 행에 통과 수·문제 수.</li>'
        '<li><span class="kbd">GET /classes/{id}/problems</span> 행에 마지막 제출 시각(「최근 제출」 열).</li>'
        '<li><span class="kbd">GET /classes/{id}/recent-attempts</span> — 최근 제출 카드. 격자 행에 가입일·마지막 제출(명단과 합치기).</li>'
        '<li>클래스 상세 응답에 누적 채점 횟수·원화 어림(채점·사용량 카드).</li>'
        '</ul></div></div>' + JS
    )
    open("review.html", "w", encoding="utf-8").write(page)
    print("wrote review.html", len(page))


if __name__ == "__main__":
    build()
