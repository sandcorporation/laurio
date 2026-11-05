# ROLLING-DEPLOY-SAFE: 연결된 앱의 다섯 모델을 classroom 에서 core 로 옮기는 것은 상태만 바뀐다(테이블 이름 그대로, DB 연산 없음). 새 칸 scope 는 db_default 가 있어 옛 코드의 INSERT 가 그대로 'classroom' 으로 채워진다(#870).
"""연결된 앱의 허락·토큰·확인 표를 공유층으로 올린다 (#870).

강의실 MCP(#512)만 쓰던 OAuth 상태를 공모전 MCP 도 쓰게 되어 `core` 로 옮긴다. 테이블은
`classroom_*` 이름 그대로 두고(`db_table`), 여기서는 모델 **상태**만 만든다 — 짝인
`classroom.0035` 가 같은 상태를 지운다. 실제 DB 에 닿는 것은 `ConnectedApp.scope` 한 칸뿐이다.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


_STATE = [
    migrations.CreateModel(
        name="OAuthClient",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("client_id", models.CharField(max_length=64, unique=True)),
            ("client_secret_hash", models.CharField(blank=True, default="", max_length=64)),
            ("token_endpoint_auth_method", models.CharField(default="none", max_length=32)),
            ("client_name", models.CharField(blank=True, default="", max_length=200)),
            ("redirect_uris", models.JSONField(default=list)),
            ("created_at", models.DateTimeField()),
        ],
        options={"db_table": "classroom_oauthclient", "ordering": ["id"]},
    ),
    migrations.CreateModel(
        name="ConnectedApp",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(blank=True, default="", max_length=200)),
            ("created_at", models.DateTimeField()),
            ("last_used_at", models.DateTimeField(blank=True, null=True)),
            ("revoked_at", models.DateTimeField(blank=True, null=True)),
            (
                "revoke_reason",
                models.CharField(
                    blank=True,
                    choices=[
                        ("disconnected", "사용자가 끊음"),
                        ("expired", "90일 동안 쓰지 않음"),
                        ("withdrawn", "탈퇴"),
                        ("dormant", "휴면"),
                    ],
                    default="",
                    max_length=20,
                ),
            ),
            (
                "instructor",
                models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="connected_apps",
                    to=settings.AUTH_USER_MODEL,
                ),
            ),
            (
                "client",
                models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="grants", to="core.oauthclient"
                ),
            ),
        ],
        options={"db_table": "classroom_connectedapp", "ordering": ["-created_at", "-id"]},
    ),
    migrations.CreateModel(
        name="OAuthAuthorizationCode",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("code_hash", models.CharField(max_length=64, unique=True)),
            ("redirect_uri", models.TextField()),
            ("code_challenge", models.CharField(max_length=128)),
            ("resource", models.TextField()),
            ("expires_at", models.DateTimeField()),
            ("used_at", models.DateTimeField(blank=True, null=True)),
            (
                "connected_app",
                models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="codes", to="core.connectedapp"
                ),
            ),
        ],
        options={"db_table": "classroom_oauthauthorizationcode"},
    ),
    migrations.CreateModel(
        name="OAuthToken",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("token_hash", models.CharField(max_length=64, unique=True)),
            ("kind", models.CharField(choices=[("access", "접근"), ("refresh", "갱신")], max_length=10)),
            ("resource", models.TextField()),
            ("created_at", models.DateTimeField()),
            ("expires_at", models.DateTimeField(blank=True, null=True)),
            ("revoked_at", models.DateTimeField(blank=True, null=True)),
            (
                "connected_app",
                models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="tokens", to="core.connectedapp"
                ),
            ),
        ],
        options={"db_table": "classroom_oauthtoken"},
    ),
    migrations.CreateModel(
        name="ConnectedAppConfirmation",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("tool", models.CharField(max_length=64)),
            ("arguments_digest", models.CharField(max_length=64)),
            ("token_hash", models.CharField(max_length=64, unique=True)),
            ("created_at", models.DateTimeField()),
            ("expires_at", models.DateTimeField()),
            ("used_at", models.DateTimeField(blank=True, null=True)),
            (
                "connected_app",
                models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="confirmations",
                    to="core.connectedapp",
                ),
            ),
        ],
        options={"db_table": "classroom_connectedappconfirmation", "ordering": ["-created_at", "-id"]},
    ),
]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_delete_databasebackup"),
        ("classroom", "0034_anthropic_key_connection_kind"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(state_operations=_STATE, database_operations=[]),
        migrations.AddField(
            model_name="connectedapp",
            name="scope",
            field=models.CharField(
                choices=[("classroom", "강의실"), ("contests", "공모전")],
                db_default="classroom",
                default="classroom",
                max_length=20,
            ),
        ),
    ]
