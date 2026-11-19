"""가짜 벤더(#999) — PR 검사의 `agent-grader` 잡이 `llm-proxy` 자리에 세운다. 표준 라이브러리만.

진짜 벤더(그리고 진짜 프록시)를 부르지 않고 두 CLI 가 도구를 쓰고 구조화 출력을 내는지 본다. 각본:
  Anthropic `/v1/messages`(SSE) — Glob → Grep → Read → StructuredOutput(있으면) → 글. 요청에 tools 가 없으면 바로 글.
  OpenAI `/v1/responses`(SSE)   — 셸 도구로 `rg -n def .`, `env`(셸에 토큰이 안 보이는지) → 스키마에 맞는 JSON 메시지.
`GET /_requests` 가 받은 요청의 경로·인증 꼬리표·모델·도구 이름을 돌려준다(본문은 남기지 않는다).
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TypedDict

FINAL = {"verdict": "ok"}


class Seen(TypedDict):
    path: str
    credential: str
    model: str
    tools: list[str]
    tool_outputs: list[str]  # CLI 가 돌려준 도구 결과(앞 300자) — 샌드박스 실패 원인을 보려고


SEEN: list[Seen] = []
LOCK = threading.Lock()


def _id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:20]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write(f"fake-vendor {format % args}\n")

    def _json(self, status: int, body: object) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, event: str, data: object) -> None:
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def do_GET(self) -> None:
        if self.path == "/_requests":
            with LOCK:
                self._json(200, SEEN)
            return
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        self._json(200, {"data": []})  # /v1/models 등

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            req = {}
        credential = self.headers.get("x-api-key") or self.headers.get("authorization", "").removeprefix("Bearer ")
        tools = [str(t.get("name") or t.get("type")) for t in req.get("tools", []) if isinstance(t, dict)]
        outputs = [str(i.get("output"))[:300] for i in req.get("input", []) if isinstance(i, dict) and i.get("type") == "function_call_output"]
        with LOCK:
            SEEN.append({"path": self.path.split("?")[0], "credential": credential, "model": str(req.get("model")),
                         "tools": tools, "tool_outputs": outputs})
        path = self.path.split("?")[0]
        if path == "/v1/messages/count_tokens":
            self._json(200, {"input_tokens": 10})
        elif path == "/v1/messages":
            self._anthropic(req, tools)
        elif path == "/v1/responses":
            self._openai(req, tools)
        else:
            self._json(404, {"error": {"type": "not_found", "message": path}})

    # ── Anthropic Messages ──
    def _anthropic(self, req: dict, tools: list[str]) -> None:
        used: list[str] = []
        for message in req.get("messages", []):
            if message.get("role") == "assistant" and isinstance(message.get("content"), list):
                used += [c.get("name") for c in message["content"] if c.get("type") == "tool_use"]
        script = [
            ("Glob", {"pattern": "**/*.py"}),
            ("Grep", {"pattern": "def "}),
            ("Read", {"file_path": "app.py"}),
            ("StructuredOutput", FINAL),
        ]
        step = next(((name, args) for name, args in script if name in tools and name not in used), None)
        block: dict = (
            {"type": "tool_use", "id": _id("toolu_"), "name": step[0], "input": step[1]}
            if step
            else {"type": "text", "text": json.dumps(FINAL)}
        )
        stop = "tool_use" if step else "end_turn"
        usage = {"input_tokens": 10, "output_tokens": 5}
        if not req.get("stream"):
            self._json(200, {"id": _id("msg_"), "type": "message", "role": "assistant", "model": req.get("model"),
                             "content": [block], "stop_reason": stop, "usage": usage})
            return
        self._sse_start()
        self._sse("message_start", {"type": "message_start", "message": {
            "id": _id("msg_"), "type": "message", "role": "assistant", "model": req.get("model"), "content": [],
            "stop_reason": None, "usage": {"input_tokens": 10, "output_tokens": 1}}})
        if step:
            self._sse("content_block_start", {"type": "content_block_start", "index": 0,
                                              "content_block": {**block, "input": {}}})
            self._sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                              "delta": {"type": "input_json_delta", "partial_json": json.dumps(step[1])}})
        else:
            self._sse("content_block_start", {"type": "content_block_start", "index": 0,
                                              "content_block": {"type": "text", "text": ""}})
            self._sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                              "delta": {"type": "text_delta", "text": block["text"]}})
        self._sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        self._sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 5}})
        self._sse("message_stop", {"type": "message_stop"})

    # ── OpenAI Responses ──
    def _openai(self, req: dict, tools: list[str]) -> None:
        items = req.get("input", [])
        answered = sum(1 for i in items if isinstance(i, dict) and i.get("type") == "function_call_output")
        shell = "exec_command" if "exec_command" in tools else ("shell" if "shell" in tools else None)
        commands = ["rg -n def .", "env"]
        if shell and answered < len(commands):
            cmd = commands[answered]
            args = {"cmd": cmd} if shell == "exec_command" else {"command": ["sh", "-c", cmd]}
            item: dict = {"type": "function_call", "id": _id("fc_"), "call_id": _id("call_"), "name": shell,
                          "arguments": json.dumps(args), "status": "completed"}
        else:
            item = {"type": "message", "id": _id("msg_"), "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(FINAL), "annotations": []}]}
        rid = _id("resp_")
        self._sse_start()
        self._sse("response.created", {"type": "response.created", "response": {"id": rid}})
        self._sse("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item})
        self._sse("response.completed", {"type": "response.completed", "response": {"id": rid, "usage": {
            "input_tokens": 10, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 15}}})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8002
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104 — 내부 시험 네트워크
