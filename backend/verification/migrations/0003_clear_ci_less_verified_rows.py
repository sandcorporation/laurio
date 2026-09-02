"""오염된 「CI 없이 VERIFIED」 행을 정리한다 (#84/#85 코드리뷰 지적 5, ADR-0024).

구코드의 `Verification.set_ci("")`는 빈 해시가 아니라 `HMAC(key, "")`라는
정상적인 64자 hex를 만들었다 — #84가 이 결함을 계약 타입·모델 양쪽에서 막았지만,
그 수정이 배포되기 전에 이미 이 버그를 밟은 환경(dev seed 데이터, 혹은 실물
어댑터가 카카오처럼 CI를 안 주는 응답을 한 번이라도 통과시킨 staging/prod)에는
`ci_hash = HMAC(key, "")`인 VERIFIED 행이 이미 남아 있을 수 있다.

이 행들을 그대로 두면 `submissions.api._reject_self_dealing`의
`if not developer_verification.ci_hash: return` 가드가 값이 falsy가 아니라서
전혀 걸러내지 못하고, 서로 남남인 그 CI-less 사용자들은 **영구히** 동일인으로
오차단된 채로 남는다 — 앱 코드를 아무리 고쳐도 이미 저장된 행은 스스로
바뀌지 않는다.

그래서 이 오염된 행 자체를 지운다 — 진짜 CI 없이 얻어진 VERIFIED는 애초에
무효이므로, CI/DI만 비우고 status=VERIFIED로 남겨 두면 "본인확인 없이도
VERIFIED"라는 또 다른 결함을 만든다. 행을 통째로 지우면 다음 실제 본인확인
시도에서 `get_or_create`가 깨끗한 상태로 다시 만든다.

현재 `VERIFICATION_ENCRYPTION_KEY`로 계산한 해시만 지울 수 있다 — 키가 그
사이 바뀐 환경이 있다면 그 오염 행은 이 마이그레이션이 잡지 못한다(그런
경우는 ci_hash로 아무것도 못 찾으므로 애초에 collision도 못 일으킨다).
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.db import migrations


def _ci_hash_of_empty_string() -> str:
    key = settings.VERIFICATION_ENCRYPTION_KEY
    key_bytes = key.encode() if isinstance(key, str) else key
    return hmac.new(key_bytes, b"", hashlib.sha256).hexdigest()


def clear_contaminated_ci_less_verifications(apps, schema_editor):
    Verification = apps.get_model("verification", "Verification")
    poisoned_hash = _ci_hash_of_empty_string()
    Verification.objects.filter(status="verified", ci_hash=poisoned_hash).delete()


def noop_reverse(apps, schema_editor):
    """되돌릴 데이터가 없다 — 지운 오염 행은 애초에 무효였으므로 복원 대상이 아니다."""


class Migration(migrations.Migration):

    dependencies = [
        ("verification", "0002_verificationrequest"),
    ]

    operations = [
        migrations.RunPython(clear_contaminated_ci_less_verifications, noop_reverse),
    ]
