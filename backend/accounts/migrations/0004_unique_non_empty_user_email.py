"""비어 있지 않은 계정 이메일에 유일 제약을 건다(2026-09-16, ADR-0049).

`User` 는 Django 의 기본 모델이라 이 앱에서 `Meta.constraints` 로 걸 수 없다 —
그래서 부분 유일 인덱스를 직접 만든다. **빈 문자열은 제외한다**: 이메일은 로그인
키가 아니라 보조 단서이고, 제공자가 이메일을 주지 않거나 인증되지 않아 비워 둔
계정이 여럿 있을 수 있다(그 계정들도 로그인은 된다).
"""

from django.db import migrations

INDEX = "unique_non_empty_user_email"

CREATE = f'CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON auth_user (email) WHERE email <> \'\';'
DROP = f"DROP INDEX IF EXISTS {INDEX};"


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_social_account_email_verified_and_account_link"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE, reverse_sql=DROP),
    ]
