"""이벤트 서비스(ADR-0046)가 쓰는 ASGI 진입점.

**lifespan 을 우리가 받는다**(2026-09-16). Django 의 ASGI 핸들러는 HTTP 가 아닌
scope 를 보면 `ValueError: Django can only handle ASGI/HTTP connections, not
lifespan.` 을 던진다. uvicorn 은 기본(`--lifespan auto`)으로 시작할 때 lifespan
메시지를 한 번 보내고, 앱이 거부하면 그 기능만 끄고 계속 뜬다 — 즉 서비스는
정상인데 **부팅마다 오류 하나가 로그에 남는다**. 오류 수집기를 붙이자마자 그
예외가 staging 백엔드 프로젝트의 최다 이슈로 올라왔다(6건). 진짜 사고와 섞이면
그 자체가 소음이므로, 여기서 lifespan 을 정상 응답으로 받아 던지지 않게 한다.

서버 기동 명령에 `--lifespan off` 를 붙이는 대안은 버렸다 — compose 파일 세
곳(dev·prod)에 같은 말을 적어야 하고, 새 파일이 생기면 조용히 빠진다.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

_django_application = get_asgi_application()


async def application(scope, receive, send):
    if scope["type"] != "lifespan":
        await _django_application(scope, receive, send)
        return

    # 시작·종료 신호에 「했다」고만 답한다 — 이 프로세스는 시작할 때 따로 준비할
    # 것이 없다(Django 설정은 위에서 이미 끝난다).
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return
