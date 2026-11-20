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
