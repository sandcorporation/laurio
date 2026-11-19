"""느린 경로 판정을 상태 없이 찍어 보거나, GlitchTip 에 시험 경고 하나를 올린다(#971).

    python manage.py slow_routes                # 지금(최근 30분)과 어제 하루의 판정 — 읽기만, 상태·전송 없음
    python manage.py slow_routes --send-sample  # 시험 경고 하나(지문 ["slow-route", "sample"]) — DB 에 쓰지 않는다
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ops_metrics import slow_route_check
from ops_metrics.recorder import minute_of
from ops_metrics.slow_routes import DAILY, REALTIME, SlowRoute

#: 시험 경고의 경로 자리 — 실제 URL 패턴이 될 수 없는 값.
SAMPLE_ROUTE = "sample"


class Command(BaseCommand):
    help = "느린 경로 판정을 찍는다(읽기만). --send-sample 은 GlitchTip 에 시험 경고 하나를 올린다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--send-sample", action="store_true", help="GlitchTip 에 시험 경고 하나를 올린다")

    def handle(self, *args, send_sample: bool = False, **options) -> None:
        if send_sample:
            self._send_sample()
            return
        now = datetime.now(dt_timezone.utc)
        current = minute_of(now.timestamp())
        first = current - (REALTIME.window_minutes - 1) * 60
        window = slow_route_check.histograms(slow_route_check._at(first), slow_route_check._at(current + 60))
        start, end = slow_route_check.yesterday(now)
        for label, found in (
            (f"실시간 ({slow_route_check.threshold(REALTIME)})", slow_route_check.find_slow(window, slow_route_check._at(first), REALTIME)),
            (
                f"어제 {start:%m-%d} ({slow_route_check.threshold(DAILY)})",
                slow_route_check.find_slow(slow_route_check.histograms(start, end), start, DAILY),
            ),
        ):
            self.stdout.write(f"{label}: {len(found)}개")
            for item in found:
                self.stdout.write("  " + slow_route_check.message(item, REALTIME if label.startswith("실시간") else DAILY))

    def _send_sample(self) -> None:
        if not getattr(settings, "SENTRY_ENABLED", False):
            raise CommandError("SENTRY_DSN 이 없어 보낼 곳이 없다")
        import sentry_sdk

        sample = SlowRoute(route=SAMPLE_ROUTE, requests=3, median_seconds=2.5, usual_median_seconds=0.04, usual_requests=40)
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("slow_route_sample", "1")
            slow_route_check.report(sample, "sample", REALTIME)
        sentry_sdk.flush(timeout=10)
        self.stdout.write("시험 경고를 보냈다 — 지문 [\"slow-route\", \"sample\"]")
