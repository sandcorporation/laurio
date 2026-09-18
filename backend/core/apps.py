from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # 전이 레지스트리에 이 앱의 스캐폴딩 모델을 등록한다. 임포트를 여기서 하는 이유는
        # settings.py 로딩 시점에 아직 앱 레지스트리가 완성되지 않아 모델을 못 불러오기
        # 때문이다(Django 앱 로딩 순서 규칙).
        from . import transitions  # noqa: F401

        # DB 연결 사용률 경고 스캔(#455) — 등록부에 올려 beat·tick·단건 호출 모두가
        # 닿게 한다. `classroom.apps.ClassroomConfig.ready()`와 같은 자리에서 한다.
        from .db_connection_scan import DB_CONNECTION_USAGE_ALERT_SCAN
        from .scans import register_scan

        register_scan(DB_CONNECTION_USAGE_ALERT_SCAN)

        # LLM 채점·GitHub 저장소 어댑터 부팅 가드(#83, #193, #274, #287) — 원래
        # scoring·repositories 앱이 각각 등록했다. core.llm_scoring·
        # core.repository_adapters로 어댑터가 공유층에 옮겨오면서 검사도 함께
        # 옮겨왔다.
        from django.core.checks import register

        from . import checks

        register(checks.check_llm_adapter_mode)
        register(checks.check_github_adapter_mode)
        register(checks.check_event_bus_adapter_mode)
