from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


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

        # 연결된 앱(ADR-0052, #512, #870) — 90일 동안 쓰지 않은 허락을 끊고, 아무도 허락하지
        # 않은 등록을 걷는다. 탈퇴·휴면이면 그 자리에서 끊는다(`accounts.signals`). 강의실과
        # 공모전이 같은 허락 표를 쓰므로 공유층이 맡는다. 스캔 이름은 처음 생긴 그대로다.
        from accounts.signals import user_became_dormant, user_withdrawn

        from .connected_app_signals import revoke_on_dormancy, revoke_on_withdrawal
        from .oauth import CONNECTED_APP_EXPIRY_SCAN, UNUSED_CLIENT_SCAN

        register_scan(CONNECTED_APP_EXPIRY_SCAN)
        register_scan(UNUSED_CLIENT_SCAN)
        user_withdrawn.connect(revoke_on_withdrawal, dispatch_uid="classroom-connected-app-withdrawal")
        user_became_dormant.connect(revoke_on_dormancy, dispatch_uid="classroom-connected-app-dormancy")

        # LLM 채점·GitHub 저장소 어댑터 부팅 가드(#83, #193, #274, #287) — 원래
        # scoring·repositories 앱이 각각 등록했다. core.llm_scoring·
        # core.repository_adapters로 어댑터가 공유층에 옮겨오면서 검사도 함께
        # 옮겨왔다.
        from django.core.checks import register

        from . import checks

        register(checks.check_llm_adapter_mode, BOOT_CHECK_TAG)
        register(checks.check_github_adapter_mode, BOOT_CHECK_TAG)
        register(checks.check_event_bus_adapter_mode, BOOT_CHECK_TAG)

        # 변환 플러그인 목록(#496) — 쓸 수 없는 경로는 첫 채점이 아니라 부팅에서 거절한다.
        from .source_converters import check_source_converters

        register(check_source_converters, BOOT_CHECK_TAG)

        # 모든 로그 레코드에 요청 id 를 붙인다(2026-09-21, core/request_id.py).
        from .request_id import install_log_record_factory

        install_log_record_factory()
