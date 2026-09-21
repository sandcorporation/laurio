"""금칙어 목록(`core.banned_words`)을 JSON 으로 내보낸다.

`packages/banned-words`(#476)가 이 출력을 먹여 TypeScript 목록을 생성한다.
`export_openapi_schema`와 같은 이유로 스택이 필요 없다 — 순수 파이썬 모듈을
읽어들일 뿐 DB 에 접속하지 않는다.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandParser

from core.banned_words import IMPERSONATION_WORDS, PROFANITY_WORDS
from core.management.stdout_utf8 import write_stdout_utf8


class Command(BaseCommand):
    help = "core.banned_words 의 사칭·욕설 목록을 JSON으로 출력한다."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output",
            "-o",
            default=None,
            help="쓸 파일 경로. 생략하면 표준출력으로 쓴다.",
        )

    def handle(self, *args, **options) -> None:
        payload_dict = {
            "impersonation": sorted(IMPERSONATION_WORDS),
            "profanity": sorted(PROFANITY_WORDS),
        }
        payload = json.dumps(payload_dict, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

        output_path = options.get("output")
        if output_path:
            with open(output_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
        else:
            write_stdout_utf8(self.stdout, payload)
