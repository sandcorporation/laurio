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
            self._write_stdout_utf8(payload)

    def _write_stdout_utf8(self, payload: str) -> None:
        """`self.stdout` 로 UTF-8을 강제해서 쓴다.

        코디네이터 리뷰 지적: `--output` 없이 표준출력으로 그대로 돌리는 것이 이
        명령의 문서화된 기본 사용법인데(이 파일의 모듈 docstring, CLAUDE.md), 그
        경로만 콘솔의 로케일 코덱을 그대로 썼다. 이 저장소의 개발 플랫폼인
        Windows 콘솔의 기본 코덱(cp949)은 스키마에 섞인 한글 설명(백엔드 Schema
        docstring 원문, 예: em dash "—")을 인코딩하지 못해
        `UnicodeEncodeError` 로 죽는다 — `--output` 경로만 안전한 걸로는
        부족하다.

        실제 콘솔에 연결된 스트림은 바이트 버퍼(`.buffer`)를 갖고 있으므로 그걸
        직접 얻어 UTF-8로 인코딩한 바이트를 쓴다. 테스트가
        `call_command(..., stdout=StringIO())` 로 바꿔치기한 스트림처럼 버퍼가
        없으면(`OutputWrapper.__getattr__` 이 위임하다 `AttributeError` 를
        던지고 `getattr` 의 기본값으로 떨어진다) 애초에 인코딩 문제가 없으므로
        그냥 문자열로 쓴다.
        """
        buffer = getattr(self.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(payload.encode("utf-8"))
            buffer.flush()
        else:
            self.stdout.write(payload, ending="")
