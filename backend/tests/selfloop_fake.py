"""우리 채점 루프(#1245) 시험의 가짜 `llm-proxy` — 진짜 모델을 부르지 않는다.

진짜 API 가 거절하는 것은 똑같이 400 으로 거절한다(무조건 받아 주면 그 버그를 숨긴다):
  - Anthropic: `x-api-key`·`anthropic-version` 없음, user/assistant 가 번갈지 않음, 앞 assistant 의 tool_use 마다
    다음 user 메시지의 tool_result 가 없음, tool_result 가 text 뒤에 옴.
  - OpenAI: `Authorization: Bearer` 없음, 앞에 없는 call_id 의 function_call_output, 짝 없는 function_call.
  - 둘 다: 발급된 토큰·모델이 아님(401·403 — 진짜 프록시처럼).
usage 는 JSON 본문 맨 위에 싣는다(스트리밍하지 않는 응답의 꼴, 진짜 프록시가 이것을 센다).

대본(`script`)은 문맥 열쇠마다 응답 목록이다. 열쇠는 지도 단계면 "map", 하위 루프면 요구사항 id. 응답 하나는
`Say(text)`·`Call(name, args)` 목록·`Status(code)` 다. 목록이 다하면 마지막 것을 되풀이한다.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "cmrt_fake-token"
USAGE_IN = 100
USAGE_OUT = 10

JSONValue = dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None


@dataclass(frozen=True)
class Say:
    text: str


@dataclass(frozen=True)
class Call:
    name: str
    args: dict[str, JSONValue] | str  # str 이면 그대로 싣는다(깨진 JSON 흉내)


@dataclass(frozen=True)
class Status:
    code: int


Step = Say | Status | list[Call | Say]
Key = str | int


@dataclass
class FakeProxy:
    vendor: str
    model: str
    script: dict[Key, list[Step]]
    url: str = ""
    requests: list[dict[str, JSONValue]] = field(default_factory=list)
    #: 문맥 열쇠마다 모델이 받은 tool_result 글(차례대로)
    tool_results: dict[Key, list[str]] = field(default_factory=dict)
    rejections: list[str] = field(default_factory=list)
    _calls: dict[Key, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def handle(self, path: str, headers: dict[str, str], body: dict[str, JSONValue]) -> tuple[int, dict[str, JSONValue]]:
        problem = self._auth(path, headers, body)
        if problem:
            return problem
        bad = self._anthropic_history(body) if self.vendor == "anthropic" else self._openai_history(body)
        if bad:
            self.rejections.append(bad)
            return 400, {"error": {"message": bad}}
        key = self._key(body)
        with self._lock:
            self.requests.append(body)
            self.tool_results.setdefault(key, []).extend(self._last_results(body))
            index = self._calls.get(key, 0)
            self._calls[key] = index + 1
        steps = self.script.get(key) or [Say("모르는 문맥")]
        step = steps[min(index, len(steps) - 1)]
        if isinstance(step, Status):
            return step.code, {"error": {"message": f"fake {step.code}"}}
        parts: list[Call | Say] = [step] if isinstance(step, Say) else step
        return 200, self._reply(parts, index)

    def calls_for(self, key: Key) -> int:
        return self._calls.get(key, 0)

    # ── 진짜 API·프록시가 보는 것 ─────────────────────────────────────────────────────────────────────────

    def _auth(self, path: str, headers: dict[str, str], body: dict[str, JSONValue]) -> tuple[int, dict[str, JSONValue]] | None:
        expected_path = "/v1/messages" if self.vendor == "anthropic" else "/v1/responses"
        if path != expected_path:
            return 404, {"error": "not found"}
        if self.vendor == "anthropic":
            token = headers.get("x-api-key", "")
            if not headers.get("anthropic-version"):
                return 400, {"error": {"message": "anthropic-version header is required"}}
        else:
            token = headers.get("authorization", "").removeprefix("Bearer ")
        if token != TOKEN:
            return 401, {"error": "unknown token"}
        if body.get("model") != self.model:
            return 403, {"error": "other model"}
        return None

    def _anthropic_history(self, body: dict[str, JSONValue]) -> str:
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return "messages: at least one message is required"
        pending: set[str] = set()
        for i, message in enumerate(messages):
            if not isinstance(message, dict) or message.get("role") != ("user" if i % 2 == 0 else "assistant"):
                return f"messages.{i}: roles must alternate starting with user"
            content = message.get("content")
            blocks = content if isinstance(content, list) else []
            if message["role"] == "user":
                results = [b.get("tool_use_id") for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
                if set(results) != pending:
                    return f"messages.{i}: tool_use ids were found without tool_result blocks immediately after"
                kinds = [b.get("type") for b in blocks if isinstance(b, dict)]
                if kinds[: len(results)] != ["tool_result"] * len(results):
                    return f"messages.{i}: tool_result blocks must come first"
                pending = set()
            else:
                pending = {str(b.get("id")) for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"}
        return ""

    def _openai_history(self, body: dict[str, JSONValue]) -> str:
        items = body.get("input")
        if not isinstance(items, list):
            return "input must be a list"
        open_calls: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                open_calls.add(str(item.get("call_id")))
            elif item.get("type") == "function_call_output":
                call_id = str(item.get("call_id"))
                if call_id not in open_calls:
                    return f"No tool call found for function call output with call_id {call_id}."
                open_calls.discard(call_id)
            elif open_calls and item.get("role") == "user":
                return f"No tool output found for function call {sorted(open_calls)[0]}."
        if open_calls:
            return f"No tool output found for function call {sorted(open_calls)[0]}."
        return ""

    def _key(self, body: dict[str, JSONValue]) -> Key:
        tools = body.get("tools")
        names = {t.get("name") for t in tools if isinstance(t, dict)} if isinstance(tools, list) else set()
        if "submit_plan" in names:
            return "map"
        match = re.search(r"requirement_id (\d+)", self._first_user_text(body))
        return int(match.group(1)) if match else "?"

    def _first_user_text(self, body: dict[str, JSONValue]) -> str:
        if self.vendor == "anthropic":
            messages = body.get("messages")
            first = messages[0] if isinstance(messages, list) and messages else {}
            content = first.get("content") if isinstance(first, dict) else None
            return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict)) if isinstance(content, list) else ""
        items = body.get("input")
        first = items[0] if isinstance(items, list) and items else {}
        return str(first.get("content", "")) if isinstance(first, dict) else ""

    def _last_results(self, body: dict[str, JSONValue]) -> list[str]:
        if self.vendor == "anthropic":
            messages = body.get("messages")
            last = messages[-1] if isinstance(messages, list) and messages else {}
            content = last.get("content") if isinstance(last, dict) else None
            blocks = content if isinstance(content, list) else []
            return [str(b.get("content")) for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
        items = body.get("input")
        tail: list[str] = []
        for item in reversed(items if isinstance(items, list) else []):
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                tail.append(str(item.get("output")))
            elif isinstance(item, dict) and item.get("type") == "function_call":
                break
        return list(reversed(tail))

    def _reply(self, parts: list[Call | Say], index: int) -> dict[str, JSONValue]:
        if self.vendor == "anthropic":
            content: list[JSONValue] = []
            for n, part in enumerate(parts):
                if isinstance(part, Say):
                    content.append({"type": "text", "text": part.text})
                else:
                    content.append({"type": "tool_use", "id": f"toolu_{index}_{n}", "name": part.name, "input": part.args})
            return {
                "type": "message",
                "role": "assistant",
                "content": content,
                "stop_reason": "tool_use" if any(isinstance(p, Call) for p in parts) else "end_turn",
                "usage": {"input_tokens": USAGE_IN, "output_tokens": USAGE_OUT, "cache_read_input_tokens": 0},
            }
        output: list[JSONValue] = []
        for n, part in enumerate(parts):
            if isinstance(part, Say):
                output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": part.text}]})
            else:
                raw = part.args if isinstance(part.args, str) else json.dumps(part.args, ensure_ascii=False)
                output.append({"type": "function_call", "call_id": f"call_{index}_{n}", "name": part.name, "arguments": raw})
        return {
            "object": "response",
            "output": output,
            "usage": {"input_tokens": USAGE_IN, "output_tokens": USAGE_OUT, "input_tokens_details": {"cached_tokens": 0}},
        }


@contextmanager
def serve(proxy: FakeProxy) -> Iterator[FakeProxy]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — 부모 서명
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, payload = proxy.handle(self.path, headers, body)
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield proxy
    finally:
        server.shutdown()
        server.server_close()
