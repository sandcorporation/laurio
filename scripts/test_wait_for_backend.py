#!/usr/bin/env python3
"""앱 진입점 `docker/entrypoint/wait-for-backend.cjs` 를 고정한다(#869).

`python3 scripts/test_wait_for_backend.py` 하나로 돈다(node 필요). 가짜 server.js 는 뜨면
표지 한 줄을 찍고, 가짜 backend 는 늦게 여는 TCP 포트다.
"""

from __future__ import annotations

import http.server
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "docker" / "entrypoint" / "wait-for-backend.cjs"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(503)  # 워커 신호가 없어도 듣고 있다는 뜻이다
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


class WaitForBackend(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.server_js = Path(self._tmp.name) / "server.js"
        self.server_js.write_text("console.log('APP_STARTED');\n")

    def run_entry(self, port: int, wait_seconds: str) -> tuple[str, float]:
        env = {**os.environ, "CODEMIT_API_BASE_URL": f"http://127.0.0.1:{port}", "CODEMIT_BACKEND_WAIT_SECONDS": wait_seconds}
        t0 = time.monotonic()
        out = subprocess.run(
            ["node", str(SCRIPT), str(self.server_js)], env=env, capture_output=True, text=True, timeout=30
        ).stdout
        return out, time.monotonic() - t0

    def test_backend_already_up_starts_immediately(self) -> None:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        out, took = self.run_entry(srv.server_address[1], "20")
        self.assertIn("APP_STARTED", out)
        self.assertNotIn("기다린다", out)
        self.assertLess(took, 3)

    def test_late_backend_app_starts_only_after_it_answers(self) -> None:
        port = free_port()
        opened_at: list[float] = []

        def open_late() -> None:
            time.sleep(2)
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
            opened_at.append(time.monotonic())
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            srv.serve_forever()

        threading.Thread(target=open_late, daemon=True).start()
        out, _ = self.run_entry(port, "20")
        done = time.monotonic()
        self.assertIn("기다린다", out)
        self.assertIn("APP_STARTED", out)
        self.assertTrue(opened_at and done >= opened_at[0])

    def test_gives_up_after_the_cap_and_still_starts_the_app(self) -> None:
        out, took = self.run_entry(free_port(), "2")
        self.assertIn("멈추고 앱을 띄운다", out)
        self.assertIn("APP_STARTED", out)
        self.assertLess(took, 8)

    def test_zero_disables_waiting(self) -> None:
        out, took = self.run_entry(free_port(), "0")
        self.assertIn("APP_STARTED", out)
        self.assertNotIn("기다린다", out)
        self.assertLess(took, 3)


if __name__ == "__main__":
    unittest.main()
