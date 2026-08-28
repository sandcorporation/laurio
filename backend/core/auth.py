"""내부 전용 엔드포인트 인증.

Celery beat 가 부르는 틱 엔드포인트, 그리고 (아직 사용자 인증이 없는 이 시점의)
notifications 내부 엔드포인트는 사람이 아니라 운영 인프라가 호출한다. 소셜 로그인
(Authentication, 티켓 04+)과는 별개의, 고정 토큰 기반의 최소 인증이다.
"""

from django.conf import settings
from ninja.security import APIKeyHeader


class InternalAuth(APIKeyHeader):
    param_name = "X-Internal-Token"

    def authenticate(self, request, key):
        expected = settings.INTERNAL_API_TOKEN
        # 토큰이 비어 있으면(prod에서 설정을 빠뜨린 경우) 어떤 값으로도 인증되지 않는다.
        if expected and key == expected:
            return key
        return None
