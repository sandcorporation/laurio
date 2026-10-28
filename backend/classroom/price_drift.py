"""모델 단가 표(`scoring_cost.PRICES`)가 낡았는지 하루 한 번 LiteLLM 단가 파일과 대조한다(#798).

OpenAI·Anthropic 어느 쪽도 단가를 주는 공식 API 가 없다. 그래서 커뮤니티가 모으는 LiteLLM 의
`model_prices_and_context_window.json` 을 **참고용으로만** 견준다 — 틀릴 수 있는 파일이라 **표를 자동으로
고치지 않는다**, 다르면 알리고 사람이 공식 가격 페이지를 보고 고친다.

알리는 경우는 셋이다(다 맞으면 알리지 않고 로그 한 줄만):

- `drift`: (a) 최근 7일 실제로 채점에 쓰였는데 이름 맞추기(`price_for`) 뒤에도 표에 없는 모델,
  (b) 표와 LiteLLM 값의 상대 차이가 1% 를 넘는 모델·필드.
- `fetch-failed`: 파일을 받지 못했다(시간 초과·비 200·크기 초과).
- `format-changed`: 받았지만 JSON 객체가 아니거나 기대한 필드가 어느 모델에도 없다.

알림은 GlitchTip 경고 이벤트 하나다. 예외 클래스 `PriceDriftAlert` 가 **`glitchtip_pick.py` 의
`DELIBERATE_EXCEPTION_TYPES` 에 있어** 자동 진단이 코드 버그로 집지 않는다(사람이 가격 페이지를 보고
표를 고칠 일이다). 지문은 알림 종류 하나라 하루 한 번 같은 내용은 이슈 하나로 묶인다.

바깥에 나가는 곳은 `LITELLM_PRICES_URL` 한 주소뿐이고, 받는 함수는 주입할 수 있다 — 시험·dev·CI 는
주입한 흉내만 쓴다(`SENTRY_ENABLED` 가 꺼진 곳에서는 작업 자체가 아무것도 하지 않는다).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from classroom import scoring_cost
from classroom.models import ClassroomScore

logger = logging.getLogger(__name__)

LITELLM_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
FETCH_TIMEOUT_SECONDS = 20
#: 지금 파일은 1.5MB 남짓이다 — 이 상한을 넘으면 형식이 바뀐 것으로 본다.
MAX_BYTES = 8 * 1024 * 1024
#: 상대 차이가 이 값을 **넘으면** 다르다고 본다.
TOLERANCE = 0.01
USED_WITHIN = timedelta(days=7)

_ABOVE_INPUT = re.compile(r"^input_cost_per_token_above_(\d+)k_tokens$")


class PriceDriftAlert(RuntimeError):
    """단가 대조 결과를 GlitchTip 으로 보내는 예외 — 사고가 아니다. 이 클래스 이름이
    `scripts/glitchtip_pick.py` 의 `DELIBERATE_EXCEPTION_TYPES` 에 있다(이름을 바꾸면 거기도)."""


class FetchFailed(Exception):
    pass


class FormatChanged(Exception):
    pass


@dataclass
class DriftReport:
    #: 쓰였는데 표에 없는 모델.
    unpriced_used: list[str] = field(default_factory=list)
    #: (모델, 필드, 우리 값, LiteLLM 값)
    differences: list[tuple[str, str, float, float]] = field(default_factory=list)
    #: 표에는 있지만 LiteLLM 에서 찾지 못해 견주지 못한 모델 — 단독으로는 알리지 않는다.
    not_compared: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.unpriced_used or self.differences)


Fetcher = Callable[[], Any]


def fetch_litellm_prices() -> Any:
    """LiteLLM 단가 파일을 받아 JSON 으로 읽는다. 받지 못하면 `FetchFailed`, JSON 이 아니면 `FormatChanged`."""

    try:
        response = requests.get(LITELLM_PRICES_URL, timeout=FETCH_TIMEOUT_SECONDS, stream=True)
    except requests.RequestException as exc:
        raise FetchFailed(f"{type(exc).__name__}: {exc}") from exc
    try:
        if response.status_code != 200:
            raise FetchFailed(f"HTTP {response.status_code}")
        body = b""
        for chunk in response.iter_content(chunk_size=65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise FetchFailed(f"응답이 {MAX_BYTES} 바이트를 넘는다")
    except requests.RequestException as exc:
        raise FetchFailed(f"{type(exc).__name__}: {exc}") from exc
    finally:
        response.close()
    try:
        return json.loads(body)
    except ValueError as exc:
        raise FormatChanged("JSON 이 아니다") from exc


def _entry_for(data: dict, model_id: str) -> dict | None:
    for key in (model_id, f"anthropic/{model_id}", f"openai/{model_id}"):
        entry = data.get(key)
        if isinstance(entry, dict):
            return entry
    return None


def _per_million(entry: dict, field_name: str) -> float | None:
    value = entry.get(field_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) * 1_000_000


def _differs(ours: float, theirs: float) -> bool:
    if theirs == 0:
        return ours != 0
    return abs(ours - theirs) / abs(theirs) > TOLERANCE


def _compare_one(model_id: str, price: scoring_cost.ModelPrice, entry: dict, report: DriftReport) -> bool:
    """한 모델을 견준다. 기대한 필드를 하나라도 읽었으면 True."""

    read_any = False
    for label, ours, key in (
        ("입력 USD/100만 토큰", price.input_usd_per_million, "input_cost_per_token"),
        ("출력 USD/100만 토큰", price.output_usd_per_million, "output_cost_per_token"),
    ):
        theirs = _per_million(entry, key)
        if theirs is None:
            continue
        read_any = True
        if _differs(ours, theirs):
            report.differences.append((model_id, label, ours, round(theirs, 6)))

    tiers = sorted(
        int(m.group(1)) * 1000 for k in entry if (m := _ABOVE_INPUT.match(k)) and entry[k] is not None
    )
    if price.long_context_input_tokens is None:
        if tiers:
            report.differences.append((model_id, "구간 단가(우리 표에는 없음)", 0.0, float(tiers[0])))
        return read_any
    wanted = round(price.long_context_input_tokens / 1000)
    theirs_in = _per_million(entry, f"input_cost_per_token_above_{wanted}k_tokens")
    theirs_out = _per_million(entry, f"output_cost_per_token_above_{wanted}k_tokens")
    if theirs_in is None and theirs_out is None:
        if tiers:
            report.differences.append(
                (model_id, "구간 기준 토큰", float(price.long_context_input_tokens), float(tiers[0]))
            )
        return read_any
    if theirs_in is not None:
        ours_in = price.input_usd_per_million * price.long_context_input_multiplier
        if _differs(ours_in, theirs_in):
            report.differences.append((model_id, f"구간({wanted}k 초과) 입력", ours_in, round(theirs_in, 6)))
    if theirs_out is not None:
        ours_out = price.output_usd_per_million * price.long_context_output_multiplier
        if _differs(ours_out, theirs_out):
            report.differences.append((model_id, f"구간({wanted}k 초과) 출력", ours_out, round(theirs_out, 6)))
    return True


def used_model_ids(now=None) -> list[str]:
    """최근 7일 실제로 채점에 쓰인 모델 이름 — 플랫폼 자동 처리(`platform-auto`)는 LLM 을 부르지 않았으니 뺀다."""

    since = (now or timezone.now()) - USED_WITHIN
    names = (
        ClassroomScore.objects.filter(created_at__gte=since)
        .exclude(model_version__startswith=scoring_cost._PLATFORM_AUTO_PREFIX)
        .values_list("model_version", flat=True)
        .distinct()
    )
    return sorted({name for name in names if name})


def compare(data: Any, used: list[str]) -> DriftReport:
    """표·쓰인 모델·LiteLLM 데이터를 견준다. 형식이 바뀌었으면 `FormatChanged`."""

    if not isinstance(data, dict) or not data:
        raise FormatChanged("최상위가 JSON 객체가 아니거나 비어 있다")
    report = DriftReport()
    read_any = False
    for model_id, price in scoring_cost.PRICES.items():
        entry = _entry_for(data, model_id)
        if entry is None:
            report.not_compared.append(model_id)
            continue
        compared = _compare_one(model_id, price, entry, report)
        read_any = read_any or compared
    if not read_any:
        raise FormatChanged("기대한 필드(input_cost_per_token·output_cost_per_token)를 어느 모델에서도 읽지 못했다")
    report.unpriced_used = [m for m in used if scoring_cost.price_for(m) is None]
    return report


def render_body(report: DriftReport) -> str:
    lines = ["모델 단가 표(backend/classroom/scoring_cost.py 의 PRICES)가 LiteLLM 단가 파일과 다르다."]
    if report.unpriced_used:
        lines.append("")
        lines.append("최근 7일 채점에 쓰였지만 표에 없는 모델(비용이 「단가 모름」으로 보인다):")
        lines.extend(f"- {m}" for m in report.unpriced_used)
    if report.differences:
        lines.append("")
        lines.append("표와 LiteLLM 의 차이가 1% 를 넘는 값(모델 / 필드 / 우리 / LiteLLM):")
        lines.extend(f"- {m} / {f} / {o:g} / {t:g}" for m, f, o, t in report.differences)
    if report.not_compared:
        lines.append("")
        lines.append("LiteLLM 에서 찾지 못해 견주지 못한 모델: " + ", ".join(report.not_compared))
    lines += [
        "",
        "표를 자동으로 고치지 않는다 — LiteLLM 은 커뮤니티 파일이다. 공식 가격 페이지"
        "(OpenAI: developers.openai.com/api/docs/pricing, Anthropic: platform.claude.com/docs/en/about-claude/pricing)를 "
        "보고 사람이 고친다. 코드 버그가 아니라 자동 진단은 집지 않는다.",
    ]
    return "\n".join(lines)


def send_alert(kind: str, body: str) -> None:
    """GlitchTip 경고 이벤트 하나 — 지문이 종류라 같은 종류는 이슈 하나로 묶인다."""

    import sentry_sdk

    with sentry_sdk.new_scope() as scope:
        scope.level = "warning"
        scope.fingerprint = ["price-drift", kind]
        scope.set_tag("alert", "price-drift")
        scope.set_tag("price_drift_kind", kind)
        sentry_sdk.capture_exception(PriceDriftAlert(body))


def run_price_drift_check(fetch: Fetcher | None = None, *, alert: Callable[[str, str], None] | None = None) -> dict:
    """대조 한 번. 알림 종류(`None` = 다 맞음)와 요지를 돌려준다.

    `SENTRY_ENABLED` 가 꺼진 곳(dev·CI)은 알릴 곳이 없으니 바깥에 나가지 않고 건너뛴다 — 다만 `fetch` 를
    주입했으면(시험) 켜진 것으로 본다."""

    if fetch is None and not getattr(settings, "SENTRY_ENABLED", False):
        logger.info("price-drift: 오류 수집기가 꺼져 있어 건너뛴다")
        return {"kind": None, "skipped": True}
    send = alert or send_alert
    try:
        data = (fetch or fetch_litellm_prices)()
        report = compare(data, used_model_ids())
    except FetchFailed as exc:
        send("fetch-failed", f"LiteLLM 단가 파일을 받지 못했다: {exc}\n{LITELLM_PRICES_URL}")
        logger.warning("price-drift: 받지 못했다 — %s", exc)
        return {"kind": "fetch-failed"}
    except FormatChanged as exc:
        send("format-changed", f"LiteLLM 단가 파일의 형식이 바뀐 듯하다: {exc}\n{LITELLM_PRICES_URL}")
        logger.warning("price-drift: 형식이 바뀌었다 — %s", exc)
        return {"kind": "format-changed"}
    if report.has_drift:
        send("drift", render_body(report))
        logger.warning(
            "price-drift: 쓰였는데 표에 없음 %d, 1%% 초과 %d", len(report.unpriced_used), len(report.differences)
        )
        return {"kind": "drift", "unpriced_used": report.unpriced_used, "differences": len(report.differences)}
    logger.info("price-drift: 모두 같다(견주지 못한 %d)", len(report.not_compared))
    return {"kind": None}
