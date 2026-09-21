"""배포 환경의 로그를 한 줄 JSON 으로 낸다(2026-09-21).

prod 로그는 Loki 가 모은다(CLAUDE.md 「운영」). 사람이 읽기 좋은 한 줄 포맷은 Loki 에서
**필드로 거를 수 없다** — 「이 요청 id 의 줄만」·「ERROR 이상만」을 문자열 검색으로
어림하게 된다. JSON 이면 Loki 의 `| json` 한 번으로 `level`·`logger`·`request_id` 가
필드가 된다.

**dev 는 그대로 사람이 읽는 포맷이다** — 개발 중 터미널을 JSON 이 덮으면 읽을 수 없다.
어느 쪽을 쓸지는 `config/settings.py` 의 LOGGING 이 배포 여부로 고른다.

필드는 일부러 적다: 시각(UTC ISO8601)·수준·로거·메시지·요청 id, 예외가 있으면 그
역추적. 요청 본문·쿠키·사용자 정보는 싣지 않는다 — 오류 수집기가 보내지 않는 것과
같은 원칙이다(`core.observability`).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        elif record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        # 한국어 메시지를 \\uXXXX 로 부풀리지 않는다 — 사람이 docker logs 로도 읽는다.
        return json.dumps(payload, ensure_ascii=False)
