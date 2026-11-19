"""`python manage.py llm_proxy` — 에이전트 채점 키 프록시를 띄운다(#998, `core.llm_proxy`).

벤더 주소는 env `LLM_PROXY_ANTHROPIC_BASE_URL`·`LLM_PROXY_OPENAI_BASE_URL` 로 바꿀 수 있다(dev·시험의 흉내 벤더).
"""

from __future__ import annotations

import os
from argparse import ArgumentParser

from aiohttp import web
from django.core.management.base import BaseCommand

from core.llm_proxy import (
    ANTHROPIC_DEFAULT_BASE_URL,
    DEFAULT_PORT,
    OPENAI_DEFAULT_BASE_URL,
    Upstreams,
    build_app,
)


class Command(BaseCommand):
    help = "에이전트 채점 키 프록시(llm-proxy)를 띄운다."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    def handle(self, *args: object, **options: object) -> None:
        upstreams = Upstreams(
            anthropic=os.environ.get("LLM_PROXY_ANTHROPIC_BASE_URL") or ANTHROPIC_DEFAULT_BASE_URL,
            openai=os.environ.get("LLM_PROXY_OPENAI_BASE_URL") or OPENAI_DEFAULT_BASE_URL,
        )
        host = str(options["host"])
        port = options["port"]
        assert isinstance(port, int)
        web.run_app(build_app(upstreams), host=host, port=port, access_log=None)
