"""OpenAPI 스키마를 표준출력(또는 파일)로 내보낸다.

프론트엔드(FE-03, #28)가 이 명령의 출력을 openapi-typescript에 먹여 타입을
생성한다. django-ninja의 스키마 생성은 등록된 라우터·스키마 클래스를
파이썬에서 그대로 내부적으로 읽어들일 뿐 DB에 접속하지 않으므로, 이 명령은
`docker compose up` 없이 — `uv sync` 만 한 상태로 — 돈다. 프론트 타입 생성이
백엔드 스택 기동을 전제하지 않게 하기 위해 일부러 이렇게 만들었다
(FE-03 티켓의 "스택 없이 도는지" 요구사항).
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandParser

from config.api import api
from core.management.stdout_utf8 import write_stdout_utf8


class Command(BaseCommand):
    help = "django-ninja가 내주는 OpenAPI 스키마를 JSON으로 출력한다."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output",
            "-o",
            default=None,
            help="쓸 파일 경로. 생략하면 표준출력으로 쓴다.",
        )

    def handle(self, *args, **options) -> None:
        schema = api.get_openapi_schema()
        payload = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

        output_path = options.get("output")
        if output_path:
            with open(output_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
        else:
            # `--output` 없이 표준출력으로 그대로 돌리는 것이 이 명령의 문서화된
            # 기본 사용법이다(이 파일의 모듈 docstring, CLAUDE.md) — Windows 콘솔의
            # 기본 코덱(cp949)이 스키마에 섞인 한글 설명을 인코딩 못 해 죽는 것을
            # `core.management.stdout_utf8.write_stdout_utf8`(#257 이 세 번째 사본을
            # 만드는 대신 여기로 모았다)가 막는다.
            write_stdout_utf8(self.stdout, payload)
