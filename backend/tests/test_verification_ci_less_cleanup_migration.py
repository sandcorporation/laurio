"""0003_clear_ci_less_verified_rows이 오염된 행만 지우고 정상 행은 남기는지 확인한다.

#84/#85 코드리뷰 지적 5 — 구코드가 한 번이라도 돈 환경에는
`ci_hash = HMAC(key, "")`인 VERIFIED 행이 이미 남아 있을 수 있고, 그 행들은
`_reject_self_dealing`의 falsy 가드를 통과하지 못해(값이 falsy가 아니므로)
서로 남남인 사람들을 영구히 동일인으로 오차단한다. 이 테스트는 0002 상태에서
오염된 행 하나와 정상 행 하나를 만든 뒤 마이그레이션을 최신까지 전진시켜,
오염된 행만 지워지고 정상 행은 그대로 남는지 직접 확인한다
(`test_contest_ledger_id_migration.py`와 같은 패턴).
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


def _hash_of(ci: str) -> str:
    key = settings.VERIFICATION_ENCRYPTION_KEY
    key_bytes = key.encode() if isinstance(key, str) else key
    return hmac.new(key_bytes, ci.encode("utf-8"), hashlib.sha256).hexdigest()


class ClearCiLessVerifiedRowsMigrationTests(TransactionTestCase):
    def test_only_the_poisoned_empty_ci_hash_rows_are_deleted(self):
        executor = MigrationExecutor(connection)

        executor.migrate([("verification", "0002_verificationrequest")])
        executor.loader.build_graph()

        old_state = executor.loader.project_state(("verification", "0002_verificationrequest"))
        HistoricalVerification = old_state.apps.get_model("verification", "Verification")

        User = get_user_model()
        contaminated_user = User.objects.create_user(
            username="contaminated", email="contaminated@example.com"
        )
        legit_user = User.objects.create_user(username="legit", email="legit@example.com")
        underage_user = User.objects.create_user(username="underage", email="underage@example.com")

        poisoned_hash = _hash_of("")
        legit_hash = _hash_of("a-real-ci-value")

        contaminated = HistoricalVerification.objects.create(
            user_id=contaminated_user.id,
            status="verified",
            reason="",
            real_name_encrypted="",
            birth_date_encrypted="",
            ci_encrypted="",
            ci_hash=poisoned_hash,
            di_encrypted="",
        )
        legit = HistoricalVerification.objects.create(
            user_id=legit_user.id,
            status="verified",
            reason="",
            real_name_encrypted="",
            birth_date_encrypted="",
            ci_encrypted="",
            ci_hash=legit_hash,
            di_encrypted="",
        )
        # UNDERAGE 행은 ci_hash가 원래도 빈 문자열이다 — 오염 판정(ci_hash ==
        # poisoned_hash)에 걸리지 않아야 정상이다. poisoned_hash 자체가 빈
        # 문자열이 아니므로("") 애초에 안전하지만, 회귀를 명시적으로 지킨다.
        underage = HistoricalVerification.objects.create(
            user_id=underage_user.id,
            status="underage",
            reason="만 19세 미만은 본인확인을 완료할 수 없습니다.",
            real_name_encrypted="",
            birth_date_encrypted="",
            ci_encrypted="",
            ci_hash="",
            di_encrypted="",
        )

        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from verification.models import Verification

        assert not Verification.objects.filter(id=contaminated.id).exists()
        assert Verification.objects.filter(id=legit.id, ci_hash=legit_hash).exists()
        assert Verification.objects.filter(id=underage.id, status="underage").exists()
