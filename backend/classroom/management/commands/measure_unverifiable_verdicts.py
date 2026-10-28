"""강의실 판정의 「확인 불가」 쏠림을 실제 모델로 잰다(#811, ADR-0067) — 일회성 측정 명령.

녹화 응답 시험은 모델이 어려운 항목을 확인 불가로 **미루는 쏠림**을 못 잡는다. 작은 예시 소스 하나에
항목 8개(실행·접속형 4, 정적 4)를 강의실 채점과 같은 프롬프트(`classroom.scoring._build_prompt`)·같은
어댑터(`allow_unverifiable=True`)로 보내, 항목별·모델별 met/unmet/unverifiable 횟수와 실제 토큰·원화를 찍는다.

- 키는 환경변수 `CODEMIT_MEASURE_OPENAI_KEY`·`CODEMIT_MEASURE_ANTHROPIC_KEY` 에서만 읽는다. 출력하지 않는다.
  없으면 「키 없음」으로 멈춘다 — 호출은 하나도 나가지 않는다.
- 돌기 전에 `scoring_cost` 어림으로 합계를 찍고, `MAX_ESTIMATED_KRW`(500원)를 넘으면 돌지 않는다.
- DB 를 읽거나 쓰지 않는다(문제·항목은 저장하지 않은 인스턴스다).

    set -a; . ~/.config/codemit-measure.env; set +a
    uv run python manage.py measure_unverifiable_verdicts
"""

from __future__ import annotations

import os
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from classroom import scoring_cost
from classroom.models import ChecklistItem, ClassroomSubmission, Problem
from classroom.scoring import CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS, _build_prompt
from classroom.syntax_check import SyntaxCheckPass
from core.llm_scoring import (
    VERDICT_VALUES,
    LLMAdapterError,
    OpenAIScoringAdapter,
    RequirementInput,
    ScoringInput,
)
from core.llm_scoring_anthropic import AnthropicScoringAdapter

OPENAI_KEY_ENV = "CODEMIT_MEASURE_OPENAI_KEY"
ANTHROPIC_KEY_ENV = "CODEMIT_MEASURE_ANTHROPIC_KEY"
MAX_ESTIMATED_KRW = 500
DEFAULT_RUNS = 5
OPENAI_MODEL = "gpt-4.1-mini"
ANTHROPIC_MODEL = "claude-haiku-5-5"
#: 강의실 클래스의 기본 추론 강도(「낮음」) — Claude 는 늘 강도를 싣는다(ADR-0066). gpt-4.1-mini 는 싣지 않는다.
ANTHROPIC_EFFORT = "low"

#: 예시 소스 — 번호로 원래 주소를 찾아 302 로 보내는 작은 단축 주소 서비스. README 는 배포·동작을 주장한다.
SAMPLE_FILES: dict[str, str] = {
    "README.md": (
        "# 짧은 주소\n\n"
        "긴 주소를 번호로 줄여 주는 서비스입니다.\n\n"
        "## 실행 방법\n\n"
        "```\npip install flask\npython app.py\n```\n\n"
        "브라우저에서 http://localhost:5000 을 엽니다.\n\n"
        "## 배포\n\n"
        "https://short.example.com 에 배포했고, /1 로 들어가면 원래 주소로 바로 이동합니다. "
        "단축 주소 만들기는 50ms 안에 응답합니다.\n"
    ),
    "app.py": (
        "import sqlite3\n"
        "from flask import Flask, abort, g, redirect, render_template, request\n\n"
        "app = Flask(__name__)\n"
        "app.config['DATABASE'] = 'links.sqlite3'\n\n\n"
        "def db():\n"
        "    if 'db' not in g:\n"
        "        g.db = sqlite3.connect(app.config['DATABASE'])\n"
        "        g.db.execute('CREATE TABLE IF NOT EXISTS links (id INTEGER PRIMARY KEY, url TEXT NOT NULL)')\n"
        "    return g.db\n\n\n"
        "@app.get('/')\n"
        "def index():\n"
        "    return render_template('index.html')\n\n\n"
        "@app.post('/links')\n"
        "def create_link():\n"
        "    url = request.form['url']\n"
        "    cur = db().execute('INSERT INTO links (url) VALUES (?)', (url,))\n"
        "    db().commit()\n"
        "    return {'id': cur.lastrowid, 'short': f'/{cur.lastrowid}'}, 201\n\n\n"
        "@app.get('/<int:link_id>')\n"
        "def follow(link_id: int):\n"
        "    row = db().execute('SELECT url FROM links WHERE id = ?', (link_id,)).fetchone()\n"
        "    if row is None:\n"
        "        abort(404)\n"
        "    return redirect(row[0], code=302)\n\n\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n"
    ),
    "templates/index.html": (
        "<form id='make'><input name='url'><button>줄이기</button></form>\n"
        "<p id='result'></p><button id='copy'>복사</button>\n"
        "<script>\n"
        "document.getElementById('make').onsubmit = async (e) => {\n"
        "  e.preventDefault();\n"
        "  const res = await fetch('/links', {method: 'POST', body: new FormData(e.target)});\n"
        "  const data = await res.json();\n"
        "  document.getElementById('result').textContent = location.origin + data.short;\n"
        "};\n"
        "document.getElementById('copy').onclick = () =>\n"
        "  navigator.clipboard.writeText(document.getElementById('result').textContent);\n"
        "</script>\n"
    ),
}

#: (종류, 항목 문장) — 실행·접속형 4, 정적 4. 번호는 1부터 차례로 붙인다.
SAMPLE_ITEMS: list[tuple[str, str]] = [
    ("live", "/숫자 주소로 들어가면 실제로 원래 주소로 이동한다"),
    ("live", "배포된 주소에 접속하면 첫 화면이 뜬다"),
    ("live", "단축 주소 만들기 요청이 100ms 안에 응답한다"),
    ("live", "브라우저에서 복사 버튼을 누르면 단축 주소가 클립보드에 들어간다"),
    ("static", "/숫자 경로를 리디렉션 응답(301/302/307/308)으로 처리하는 코드가 있다"),
    ("static", "README 에 실행 방법이 적혀 있다"),
    ("static", "없는 번호로 요청하면 404 를 돌려주는 코드가 있다"),
    ("static", "단축 주소를 데이터베이스에 저장하는 코드가 있다"),
]


def sample_prompt() -> str:
    """강의실 채점과 같은 프롬프트 — 저장하지 않은 문제·항목으로 `_build_prompt` 를 부른다."""

    problem = Problem(title="짧은 주소 서비스", description="번호로 원래 주소를 찾아 보내는 단축 주소 서비스를 만든다.")
    items = [ChecklistItem(id=index, label=label, required=True) for index, (_, label) in enumerate(SAMPLE_ITEMS, 1)]
    source_text = "\n\n".join(f"# {path}\n{content}" for path, content in SAMPLE_FILES.items())
    return _build_prompt(
        ClassroomSubmission(problem=problem),
        items,
        source_text,
        asset_kind="source",
        syntax_check=SyntaxCheckPass(resolved=None),
    )


def sample_input(prompt: str) -> ScoringInput:
    return ScoringInput(
        submission_id=0,
        contest_id=0,
        prompt=prompt,
        source_files=[],
        requirements=[
            RequirementInput(requirement_id=index, text=label, grade="required", self_reported_met=False, evidence=[])
            for index, (_, label) in enumerate(SAMPLE_ITEMS, 1)
        ],
    )


def _actual_krw(model: str, input_tokens: int, output_tokens: int) -> float:
    price = scoring_cost.price_for(model)
    if price is None:
        return 0.0
    usd = (input_tokens * price.input_usd_per_million + output_tokens * price.output_usd_per_million) / 1_000_000
    return usd * scoring_cost.KRW_PER_USD


class Command(BaseCommand):
    help = "강의실 판정의 「확인 불가」 비율을 실제 모델로 잰다(#811). 키는 환경변수에서만 읽는다."

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="모델마다 호출 횟수(기본 5)")

    def handle(self, *args, **options):
        runs = options["runs"]
        if runs < 1:
            raise CommandError("--runs 는 1 이상이어야 한다.")
        prompt = sample_prompt()
        plan = [
            ("openai", OPENAI_MODEL, None, OPENAI_KEY_ENV),
            ("anthropic", ANTHROPIC_MODEL, ANTHROPIC_EFFORT, ANTHROPIC_KEY_ENV),
        ]

        estimated = 0.0
        for _, model, effort, _ in plan:
            cost = scoring_cost.attempt_cost(model, effort, prompt_chars=len(prompt))
            if cost is None:
                raise CommandError(f"단가표에 없는 모델이라 비용 상한을 잴 수 없다: {model}")
            self.stdout.write(f"어림 {model}: 호출당 {cost.krw:.1f}원 × {runs} = {cost.krw * runs:.1f}원")
            estimated += cost.krw * runs
        self.stdout.write(f"어림 합계 {estimated:.1f}원 (상한 {MAX_ESTIMATED_KRW}원)")
        if estimated > MAX_ESTIMATED_KRW:
            raise CommandError(f"어림 합계가 상한 {MAX_ESTIMATED_KRW}원을 넘어 돌지 않는다.")

        keys = {env: os.environ.get(env, "").strip() for _, _, _, env in plan}
        missing = [env for env, value in keys.items() if not value]
        if missing:
            raise CommandError(f"키 없음: {', '.join(missing)} — 호출하지 않았다.")

        scoring_input = sample_input(prompt)
        total_krw = 0.0
        for vendor, model, effort, env in plan:
            adapter = self._adapter(vendor, model=model, effort=effort, api_key=keys[env])
            counts: dict[int, Counter] = {index: Counter() for index in range(1, len(SAMPLE_ITEMS) + 1)}
            failures: Counter = Counter()
            input_tokens = output_tokens = 0
            for _ in range(runs):
                try:
                    output = adapter.score(scoring_input)
                except LLMAdapterError as exc:
                    # 예외 메시지는 식별자만 담는다(ADR-0014) — 그래도 종류 이름만 찍는다.
                    failures[type(exc).__name__] += 1
                    continue
                input_tokens += output.input_tokens
                output_tokens += output.output_tokens
                for verdict in output.verdicts:
                    counts[verdict.requirement_id][verdict.verdict or "?"] += 1
            krw = _actual_krw(model, input_tokens, output_tokens)
            total_krw += krw
            self._report(model, counts, failures, input_tokens, output_tokens, krw)
        self.stdout.write(f"실제 합계 {total_krw:.1f}원")

    def _adapter(self, vendor: str, *, model: str, effort: str | None, api_key: str):
        common = {
            "api_key": api_key,
            "model": model,
            "timeout": CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS,
            "product": "classroom",
            "log_context": {"measure": "unverifiable"},
            "allow_unverifiable": True,
        }
        if vendor == "openai":
            return OpenAIScoringAdapter(**common)
        return AnthropicScoringAdapter(reasoning_effort=effort, **common)

    def _report(self, model, counts, failures, input_tokens, output_tokens, krw) -> None:
        self.stdout.write(f"\n== {model}")
        self.stdout.write("번호 종류    " + " ".join(f"{v:>12}" for v in VERDICT_VALUES) + "  항목")
        for index, (kind, label) in enumerate(SAMPLE_ITEMS, 1):
            row = " ".join(f"{counts[index][v]:>12}" for v in VERDICT_VALUES)
            self.stdout.write(f"{index:>4} {kind:<7}{row}  {label}")
        for kind in ("live", "static"):
            total = Counter()
            for index, (item_kind, _) in enumerate(SAMPLE_ITEMS, 1):
                if item_kind == kind:
                    total.update(counts[index])
            self.stdout.write(f"합계 {kind:<7}" + " ".join(f"{total[v]:>12}" for v in VERDICT_VALUES))
        if failures:
            self.stdout.write("실패: " + ", ".join(f"{name} {n}" for name, n in failures.items()))
        self.stdout.write(f"토큰 입력 {input_tokens} · 출력 {output_tokens} · {krw:.1f}원")
