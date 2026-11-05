# ROLLING-DEPLOY-SAFE: 연결된 앱의 다섯 모델을 core 로 옮기는 짝이다 — 상태에서만 지우고 테이블은 그대로 둔다(core.0005 가 같은 테이블을 이어받는다). DB 연산이 없다(#870).
"""연결된 앱의 허락·토큰·확인 표가 `core` 로 올라갔다 (#870, `core.0005`).

쓰기 기록(`ConnectedAppWrite`)의 외래 키를 `core.ConnectedApp` 으로 돌리고, 옛 다섯 모델을
상태에서 지운다. 같은 테이블·같은 FK 제약이라 DB 에는 아무것도 하지 않는다.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0034_anthropic_key_connection_kind"),
        ("core", "0005_connected_apps"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="connectedappwrite",
                    name="connected_app",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="writes", to="core.connectedapp"
                    ),
                ),
                migrations.DeleteModel(name="ConnectedAppConfirmation"),
                migrations.DeleteModel(name="OAuthToken"),
                migrations.DeleteModel(name="OAuthAuthorizationCode"),
                migrations.DeleteModel(name="ConnectedApp"),
                migrations.DeleteModel(name="OAuthClient"),
            ],
            database_operations=[],
        ),
    ]
