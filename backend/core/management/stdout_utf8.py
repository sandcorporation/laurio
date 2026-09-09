"""관리 명령이 한글이 섞인 payload 를 안전하게 표준출력에 쓰는 한 곳 (#257 코드리뷰).

`export_openapi_schema.py`(#28)와 `seed_e2e_contests.py`(#39)가 각자 같은
`_write_stdout_utf8` 메서드를 갖고 있었다 — `print_contest_transition_diagram.py`(#257)
가 세 번째로 같은 문제(한글이 섞인 payload 를 `--output` 없이 표준출력으로 그대로
돌리는 것이 기본 사용법인 명령)를 만나면서, 손으로 세 번째 사본을 더 만드는 대신
여기 한 곳으로 모은다.

**왜 필요한가.** 이 저장소의 개발 플랫폼인 Windows 콘솔의 기본 코덱(cp949)은 한글
설명(예: em dash "—")을 인코딩하지 못해 평범한 `self.stdout.write()`가
`UnicodeEncodeError`로 죽는다. `--output` 경로만 안전한 걸로는 부족하다 —
표준출력이 기본 사용법인 명령은 그 경로도 안전해야 한다.
"""

from __future__ import annotations

from django.core.management.base import OutputWrapper


def write_stdout_utf8(stdout: OutputWrapper, payload: str) -> None:
    """`stdout` 으로 UTF-8을 강제해서 쓴다.

    실제 콘솔에 연결된 스트림은 바이트 버퍼(`.buffer`)를 갖고 있으므로 그걸 직접
    얻어 UTF-8로 인코딩한 바이트를 쓴다. 테스트가 `call_command(..., stdout=
    StringIO())`로 바꿔치기한 스트림처럼 버퍼가 없으면(`OutputWrapper.__getattr__`
    이 위임하다 `AttributeError`를 던지고 `getattr`의 기본값으로 떨어진다) 애초에
    인코딩 문제가 없으므로 그냥 문자열로 쓴다.
    """

    buffer = getattr(stdout, "buffer", None)
    if buffer is not None:
        buffer.write(payload.encode("utf-8"))
        buffer.flush()
    else:
        stdout.write(payload, ending="")
