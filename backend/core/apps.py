from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # 전이 레지스트리에 이 앱의 스캐폴딩 모델을 등록한다. 임포트를 여기서 하는 이유는
        # settings.py 로딩 시점에 아직 앱 레지스트리가 완성되지 않아 모델을 못 불러오기
        # 때문이다(Django 앱 로딩 순서 규칙).
        from . import transitions  # noqa: F401
