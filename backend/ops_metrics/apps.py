from django.apps import AppConfig


class OpsMetricsConfig(AppConfig):
    name = "ops_metrics"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # 공유층이 1분 집계를 import 없이 부르는 자리(#1086, `core.ops_ports`)
        from core.ops_ports import OPS_RECORDER, REQUEST_RECORDER
        from ops_metrics import recorder, request_buffer

        OPS_RECORDER.register(recorder)
        REQUEST_RECORDER.register(request_buffer)

        # 발송 실패·수신자 0 운영 경보 스캔(#1123) — 운영 경보 길이 이 앱에 있고, 이 앱이 notifications 를 읽는다.
        from core.scans import register_scan

        from .notification_dispatch_alert import NOTIFICATION_DISPATCH_ALERT_SCAN

        register_scan(NOTIFICATION_DISPATCH_ALERT_SCAN)
