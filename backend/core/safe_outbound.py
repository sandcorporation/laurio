"""강사가 적은 주소로 나가는 안전한 HTTP (#600, ADR-0058).

강의실의 호환 채점 서버 주소는 강사가 적고 **우리 채점 워커가 직접 부른다**. 워커는 docker 내부망에
있어 `db`·`redis`·`backend` 와 클라우드 메타데이터 주소에 닿는다 — 막지 않으면 강사 입력 칸 하나가
내부망을 찌르는 통로(SSRF)가 된다. 강사 주소로 나가는 요청은 전부 이 모듈을 거친다.

- **https 만.** 평문이면 강사의 인증 값과 학생 소스가 그대로 인터넷을 지난다.
- **공인 IP 로 풀리는 이름만.** 사설·루프백·링크로컬(메타데이터)·CGNAT·예약·멀티캐스트·미지정,
  IPv6 ULA·IPv4-mapped·NAT64·6to4 로 감싼 사설 주소, 그리고 docker 내부 이름(점 없는 이름,
  `localhost`·`.internal`·`.local`)을 거부한다. 풀린 IP 가 여럿이면 모두 공인이어야 한다.
- **푼 IP 로 직접 붙는다.** 저장할 때 확인(`check`)하고 연결할 때 `requests` 가 이름을 다시 풀면,
  그 사이에 DNS 를 사설 주소로 되바꾸는 공격을 못 막는다. 그래서 연결할 때 이 모듈이 한 번 풀어
  확인한 **그 IP 를 URL 에 넣어** 보내고, 이름은 세 곳에만 남긴다 — `Host` 헤더, TLS SNI
  (`server_hostname`), 인증서 이름 검증(`assert_hostname`). 둘 다 urllib3 의 연결 풀 인자라
  `HTTPAdapter.init_poolmanager` 에서 고정한다. `requests` 는 IP 로 된 URL 을 다시 풀 일이 없다.
  환경 변수의 프록시(`HTTPS_PROXY`)를 타면 프록시가 이름을 다시 풀 수 있어 `trust_env` 를 끈다.
- **리다이렉트를 따라가지 않는다.** 3xx 는 실패다 — 따라가면 공인 서버가 `Location` 하나로 내부
  주소를 가리킬 수 있다.
- **인증서는 정식으로 검증한다.** 자체 서명은 안 된다.

거부·실패는 `OutboundRefused.reason`(`OutboundReason`)으로 이유별로 갈린다 — 화면 문장과 「연결
불가」 분류(#598)가 이것을 쓴다.

**fake 스위치(ADR-0043).** `CLASSROOM_SCORING_ADAPTER_MODE` 가 fake 인 환경(dev·CI)에서는
나가지 않는다: 요청은 `OFFLINE` 으로 거부하고, `check` 는 주소 모양(https·내부 이름·IP 리터럴)만
보고 이름은 풀지 않는다.

시험은 `resolver`(주소 풀기)·`is_allowed`(공인 판정)·`ca_bundle`(신뢰할 CA)을 갈아끼운다.
"""

from __future__ import annotations

import enum
import ipaddress
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter

from core.adapters import is_fake_adapter_binding

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], list[str]]


class OutboundReason(enum.StrEnum):
    NOT_HTTPS = "not_https"
    NOT_PUBLIC = "not_public"
    DNS_FAILED = "dns_failed"
    UNREACHABLE = "unreachable"  # 연결 거부·연결 타임아웃·연결 끊김
    #: 닿았는데 답을 제때·끝까지 받지 못했다(읽기 타임아웃·끊긴 몸통, #603) — 위의 것들과 달리
    #: 서버가 요청을 받았다. 강의실 채점은 이것만 실패 시도로 세고 나머지는 「연결 불가」로 멈춘다.
    RESPONSE_FAILED = "response_failed"
    CERTIFICATE = "certificate"
    REDIRECT = "redirect"
    OFFLINE = "offline"  # fake 스위치 — dev·CI 는 나가지 않는다


class OutboundRefused(Exception):
    def __init__(self, reason: OutboundReason, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)

    @property
    def reached(self) -> bool:
        """요청이 서버에 닿았는가(#603) — 닿지 않았으면(이름·주소·연결·인증서·리다이렉트) 그
        서버의 문제라 다시 시도해도 같다."""

        return self.reason is OutboundReason.RESPONSE_FAILED


#: 이름만 보고 내부로 판정하는 꼬리 — 공인 DNS 에 없거나(RFC 6761·6762·8375) 클라우드 내부 이름이다.
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".localdomain")

#: `is_global` 이 참이어도 안에 IPv4 를 싣는 대역 — 실린 IPv4 를 다시 본다.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def is_public_address(address: IPAddress) -> bool:
    """공인 유니캐스트 주소인가. `is_global` 을 바탕으로 하되 그것이 놓치는 것을 더 막는다 —
    IPv6 전역 멀티캐스트(`ff0e::/16` 는 `is_global` 이 참이다), IPv4 를 감싼 IPv6(mapped·NAT64·6to4)."""

    if address.version == 6:
        embedded = address.ipv4_mapped or address.sixtofour
        if embedded is None and address in _NAT64:
            embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        if embedded is not None:
            return is_public_address(embedded)
        if address.teredo is not None:
            return False
    return address.is_global and not (
        address.is_multicast
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def _system_resolver(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


class _PinnedHostAdapter(HTTPAdapter):
    """URL 에는 IP, TLS 에는 원래 이름 — SNI 와 인증서 이름 검증을 `hostname` 으로 고정한다."""

    def __init__(self, hostname: str):
        self._hostname = hostname  # `HTTPAdapter.__init__` 이 `init_poolmanager` 를 부르기 전에
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["server_hostname"] = self._hostname
        pool_kwargs["assert_hostname"] = self._hostname
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


class SafeOutbound:
    def __init__(
        self,
        *,
        resolver: Resolver = _system_resolver,
        is_allowed: Callable[[IPAddress], bool] = is_public_address,
        ca_bundle: str | None = None,
    ):
        self._resolve = resolver
        self._is_allowed = is_allowed
        self._verify: bool | str = ca_bundle or True

    # --- 확인 ----------------------------------------------------------------------------

    def check(self, url: str) -> list[IPAddress]:
        """주소를 받아도 되는가 — 저장할 때 부른다. 공인 IP 목록을 돌려주거나 `OutboundRefused`.
        fake 스위치에서는 모양만 보고 이름을 풀지 않는다(빈 목록)."""

        host, port = self._split(url)
        if self._offline():
            literal = self._literal(host)
            if literal is not None:
                self._require_allowed([literal])
            return []
        return self._resolve_allowed(host, port)

    # --- 요청 ----------------------------------------------------------------------------

    def post_json(self, url: str, body: Any, *, headers: dict[str, str], timeout: float) -> requests.Response:
        return self.request("POST", url, headers=headers, json=body, timeout=timeout)

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> requests.Response:
        return self.request("GET", url, headers=headers, timeout=timeout)

    def request(
        self, method: str, url: str, *, headers: dict[str, str], timeout: float, json: Any = None
    ) -> requests.Response:
        """한 번 풀어 확인한 IP 로 직접 보낸다. 3xx 는 `REDIRECT`, 그 밖의 상태는 응답 그대로."""

        host, port = self._split(url)
        if self._offline():
            raise OutboundRefused(OutboundReason.OFFLINE, "dev·CI 는 강사 주소로 나가지 않는다")
        address = self._resolve_allowed(host, port)[0]

        parts = urlsplit(url)
        pinned_netloc = f"[{address}]" if address.version == 6 else str(address)
        if parts.port is not None:
            pinned_netloc += f":{port}"
        pinned_url = urlunsplit(("https", pinned_netloc, parts.path or "/", parts.query, ""))
        host_header = host if parts.port is None else f"{host}:{port}"

        session = requests.Session()
        session.trust_env = False
        session.mount("https://", _PinnedHostAdapter(host))
        try:
            response = session.request(
                method,
                pinned_url,
                headers={**headers, "Host": host_header},
                json=json,
                timeout=timeout,
                allow_redirects=False,
                verify=self._verify,
            )
        except requests.exceptions.SSLError as exc:
            raise OutboundRefused(OutboundReason.CERTIFICATE, str(exc)) from None
        except requests.exceptions.ConnectionError as exc:
            # 연결 타임아웃(`ConnectTimeout`)도 여기다 — 연결 자체가 서지 않았다.
            raise OutboundRefused(OutboundReason.UNREACHABLE, type(exc).__name__) from None
        except requests.RequestException as exc:
            # 읽기 타임아웃·끊긴 몸통 — 연결은 섰고 서버가 요청을 받았다(#603).
            raise OutboundRefused(OutboundReason.RESPONSE_FAILED, type(exc).__name__) from None
        finally:
            session.close()

        if 300 <= response.status_code < 400:
            response.close()
            raise OutboundRefused(OutboundReason.REDIRECT, str(response.status_code))
        return response

    # --- 안쪽 ----------------------------------------------------------------------------

    @staticmethod
    def _offline() -> bool:
        return is_fake_adapter_binding(settings.CLASSROOM_SCORING_ADAPTER_MODE)

    @staticmethod
    def _split(url: str) -> tuple[str, int]:
        try:
            parts = urlsplit(url.strip())
            port = parts.port or 443
        except ValueError:
            raise OutboundRefused(OutboundReason.NOT_HTTPS, "주소 모양이 아니다") from None
        if parts.scheme.lower() != "https":
            raise OutboundRefused(OutboundReason.NOT_HTTPS, parts.scheme or "스킴 없음")
        host = (parts.hostname or "").rstrip(".").lower()
        if not host:
            raise OutboundRefused(OutboundReason.NOT_HTTPS, "호스트 없음")
        if parts.username is not None or parts.password is not None:
            raise OutboundRefused(OutboundReason.NOT_HTTPS, "주소에 계정 정보를 넣지 않는다")
        if SafeOutbound._literal(host) is None and (
            "." not in host or host == "localhost" or host.endswith(_INTERNAL_SUFFIXES)
        ):
            raise OutboundRefused(OutboundReason.NOT_PUBLIC, f"내부 이름 {host}")
        return host, port

    @staticmethod
    def _literal(host: str) -> IPAddress | None:
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None

    def _resolve_allowed(self, host: str, port: int) -> list[IPAddress]:
        literal = self._literal(host)
        if literal is not None:
            addresses = [literal]
        else:
            try:
                answers = self._resolve(host, port)
            except (OSError, UnicodeError) as exc:
                raise OutboundRefused(OutboundReason.DNS_FAILED, type(exc).__name__) from None
            if not answers:
                raise OutboundRefused(OutboundReason.DNS_FAILED, "응답 없음")
            addresses = [ipaddress.ip_address(answer) for answer in answers]
        self._require_allowed(addresses)
        return addresses

    def _require_allowed(self, addresses: list[IPAddress]) -> None:
        for address in addresses:
            if not self._is_allowed(address):
                raise OutboundRefused(OutboundReason.NOT_PUBLIC, str(address))
