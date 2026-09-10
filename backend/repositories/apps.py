from django.apps import AppConfig


class RepositoriesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "repositories"
    verbose_name = "Repositories · GitHub 저장소"

    def ready(self) -> None:
        # 어댑터 부팅 가드(check_github_adapter_mode)는 core.apps.CoreConfig.ready()가
        # 등록한다(#287) — 검사 대상(GitHubAdapter)이 core.repository_adapters로
        # 옮겨가면서 검사도 함께 옮겨갔다. `repositories.checks`는 재노출만 남아 있다.

        # 저장소 공개 여부 확인 스캔(#193) — 등록부에 올라 beat 가 주기적으로
        # 돌린다. `POST /api/internal/tick`이 등록부 전부를 도는 만큼 이것도
        # 자동으로 함께 돈다.
        from core.scans import register_scan

        from .services import REPOSITORY_VISIBILITY_SCAN

        register_scan(REPOSITORY_VISIBILITY_SCAN)
