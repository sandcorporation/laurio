"""강사 주소로 나가는 안전한 HTTP (#600, ADR-0058).

강사가 적은 호환 채점 서버 주소는 우리 채점 워커가 직접 부른다 — 워커는 docker 내부망에 있다.
그래서 이 모듈은 https 만, 공인 IP 로 풀리는 이름만 받고, **그 푼 IP 로 직접 붙는다**(확인과
연결 사이에 DNS 를 사설 주소로 되바꾸는 공격을 막는다). TLS 는 원래 호스트 이름으로 검증하고,
리다이렉트는 따라가지 않는다.

이 파일은 바깥 네트워크로 나가지 않는다 — 주소 풀기를 갈아끼우고, 성공 경로는 127.0.0.1 에 띄운
로컬 TLS 흉내 서버(이 파일에서만 만든 자체 CA)로 본다.
"""

from __future__ import annotations

import datetime
import http.server
import ipaddress
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from django.test import override_settings

from core.safe_outbound import (
    OutboundReason,
    OutboundRefused,
    SafeOutbound,
    is_public_address,
)

HOST = "scoring.example.test"
REAL_MODE = override_settings(CLASSROOM_SCORING_ADAPTER_MODE="classroom.scoring.OpenAIScoringAdapter")
LOOPBACK = ipaddress.ip_address("127.0.0.1")


def _resolver(*answers: str):
    def resolve(host: str, port: int) -> list[str]:
        return list(answers)

    return resolve


def _only_loopback_counts_as_public(address) -> bool:
    """성공 경로 시험에서만 — 흉내 서버가 127.0.0.1 에 있으니 그 주소 하나만 「공인」으로 본다."""
    return address == LOOPBACK


# --- 막을 대역: `is_global` 만으로는 빠지는 것까지 못 박는다 --------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",  # 사설
        "172.16.3.4",
        "192.168.0.1",
        "127.0.0.1",  # 루프백
        "169.254.169.254",  # 링크로컬 — 클라우드 메타데이터
        "100.64.0.1",  # CGNAT
        "100.100.100.200",  # CGNAT 안의 메타데이터(알리바바)
        "0.0.0.0",  # 미지정
        "240.0.0.1",  # 예약
        "255.255.255.255",  # 브로드캐스트
        "224.0.0.251",  # 멀티캐스트
        "239.255.255.250",
        "198.18.0.1",  # 벤치마크
        "192.0.2.1",  # 문서용
        "::1",  # IPv6 루프백
        "::",  # IPv6 미지정
        "fe80::1",  # IPv6 링크로컬
        "fc00::1",  # IPv6 ULA
        "fd00:ec2::254",  # IPv6 ULA — AWS 메타데이터
        "ff02::1",  # IPv6 멀티캐스트
        "ff0e::1",  # IPv6 전역 범위 멀티캐스트 — is_global 이 참이어도 막는다
        "::ffff:127.0.0.1",  # IPv4-mapped 루프백
        "::ffff:10.0.0.1",  # IPv4-mapped 사설
        "::ffff:169.254.169.254",  # IPv4-mapped 메타데이터
        "64:ff9b::a00:1",  # NAT64 로 감싼 10.0.0.1
        "2002:a00:1::1",  # 6to4 로 감싼 10.0.0.1
        "2001:db8::1",  # 문서용
    ],
)
def test_non_public_addresses_are_refused(address):
    assert not is_public_address(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_addresses_pass(address):
    assert is_public_address(ipaddress.ip_address(address))


# --- 주소 자체를 거부한다 --------------------------------------------------------------------


@REAL_MODE
def test_http_is_refused_before_resolving():
    def must_not_resolve(host, port):  # pragma: no cover - 불리면 실패
        raise AssertionError("http 는 풀기 전에 거부한다")

    with pytest.raises(OutboundRefused) as caught:
        SafeOutbound(resolver=must_not_resolve).check("http://scoring.example.com/v1")
    assert caught.value.reason is OutboundReason.NOT_HTTPS


@REAL_MODE
@pytest.mark.parametrize(
    "url",
    [
        "https://backend:8000/api",  # docker 내부 이름(점 없음)
        "https://db/",
        "https://localhost/",
        "https://metadata.google.internal/",
        "https://printer.local/",
        "https://evil.localhost/",
    ],
)
def test_internal_names_are_refused_without_resolving(url):
    def must_not_resolve(host, port):  # pragma: no cover - 불리면 실패
        raise AssertionError("내부 이름은 풀지 않는다")

    with pytest.raises(OutboundRefused) as caught:
        SafeOutbound(resolver=must_not_resolve).check(url)
    assert caught.value.reason is OutboundReason.NOT_PUBLIC


@REAL_MODE
@pytest.mark.parametrize(
    "answers",
    [
        ("10.1.2.3",),
        ("169.254.169.254",),
        ("fd12:3456::1",),
        ("::ffff:192.168.1.1",),
        ("100.64.1.1",),
        ("8.8.8.8", "10.0.0.1"),  # 여럿이면 모두 공인이어야 한다
    ],
)
def test_names_resolving_to_non_public_addresses_are_refused(answers):
    with pytest.raises(OutboundRefused) as caught:
        SafeOutbound(resolver=_resolver(*answers)).check("https://scoring.example.com/v1")
    assert caught.value.reason is OutboundReason.NOT_PUBLIC


@REAL_MODE
@pytest.mark.parametrize("url", ["https://10.0.0.1/v1", "https://[::1]/v1", "https://[::ffff:127.0.0.1]:8443/"])
def test_private_ip_literals_are_refused(url):
    with pytest.raises(OutboundRefused) as caught:
        SafeOutbound().check(url)
    assert caught.value.reason is OutboundReason.NOT_PUBLIC


@REAL_MODE
def test_dns_failure_is_its_own_reason():
    def fail(host, port):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    with pytest.raises(OutboundRefused) as caught:
        SafeOutbound(resolver=fail).check("https://nowhere.example.com/")
    assert caught.value.reason is OutboundReason.DNS_FAILED


@REAL_MODE
def test_public_name_passes_the_check():
    assert SafeOutbound(resolver=_resolver("8.8.8.8")).check("https://scoring.example.com/v1") == [
        ipaddress.ip_address("8.8.8.8")
    ]


# --- 되바꾸기: 저장 때 공인, 연결 때 사설 ------------------------------------------------------


@REAL_MODE
def test_rebinding_after_the_save_check_is_refused_at_connect_time():
    answers = iter([("8.8.8.8",), ("127.0.0.1",)])

    def rebinding(host, port):
        return list(next(answers))

    outbound = SafeOutbound(resolver=rebinding)
    outbound.check("https://scoring.example.com/v1")  # 저장할 때 — 공인으로 풀린다
    with pytest.raises(OutboundRefused) as caught:
        outbound.post_json("https://scoring.example.com/v1", {"x": 1}, headers={}, timeout=1)
    assert caught.value.reason is OutboundReason.NOT_PUBLIC


# --- fake 스위치(ADR-0043): dev·CI 에서는 나가지 않는다 ---------------------------------------


@override_settings(CLASSROOM_SCORING_ADAPTER_MODE="fake")
def test_fake_switch_never_touches_the_network():
    def must_not_resolve(host, port):  # pragma: no cover - 불리면 실패
        raise AssertionError("fake 에서는 이름도 풀지 않는다")

    with pytest.raises(OutboundRefused) as caught:
        SafeOutbound(resolver=must_not_resolve).post_json(
            "https://scoring.example.com/v1", {}, headers={}, timeout=1
        )
    assert caught.value.reason is OutboundReason.OFFLINE


# --- 로컬 TLS 흉내 서버 ----------------------------------------------------------------------


def _key():
    return ec.generate_private_key(ec.SECP256R1())


def _cert(subject_name, issuer_name, public_key, signing_key, *, ca: bool, san: list[str] | None = None):
    # Python 3.13 이후의 기본 검증(VERIFY_X509_STRICT)은 키 식별자·용도가 없는 인증서를 받지 않는다.
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_name)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_name)]))
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(signing_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=not ca, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
    )
    if not ca:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name) for name in san]), critical=False
        )
    return builder.sign(signing_key, hashes.SHA256())


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if self.path == "/slow":
            self.server.release.wait(2)  # 시험이 끝나면 풀린다 — 손님이 먼저 포기한다.
            return
        if self.path == "/big":
            # 상한(시험은 64KB)보다 훨씬 큰 본문을 그대로 흘린다 — 손님이 상한에서 끊어야 한다.
            size = 1_000_000
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            try:
                for _ in range(size // 10_000):
                    self.wfile.write(b"x" * 10_000)
            except OSError:
                pass  # 손님이 먼저 끊었다 — 기대한 일이다.
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "https://169.254.169.254/latest/meta-data/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = (
            b'{"host":"' + self.headers["Host"].encode() + b'","sni":"' + (self.server.last_sni or "").encode()
            + b'","body":' + body + b"}"
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _serve(cert_pem: bytes, key_pem: bytes, tmp_path, name: str):
    (tmp_path / f"{name}.crt").write_bytes(cert_pem)
    (tmp_path / f"{name}.key").write_bytes(key_pem)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / f"{name}.crt", tmp_path / f"{name}.key")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.last_sni = None
    server.release = threading.Event()

    def remember_sni(sock, server_name, ctx):
        server.last_sni = server_name

    context.sni_callback = remember_sni
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("tls")
    ca_key = _key()
    ca = _cert("Codemit test CA", "Codemit test CA", ca_key.public_key(), ca_key, ca=True)
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))

    def leaf(name: str):
        key = _key()
        cert = _cert(name, "Codemit test CA", key.public_key(), ca_key, ca=False, san=[name])
        return (
            cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
        )

    good = _serve(*leaf(HOST), tmp_path, "good")
    wrong = _serve(*leaf("someone-else.example.test"), tmp_path, "wrong")
    yield {"ca": str(ca_path), "good": good.server_address[1], "wrong": wrong.server_address[1]}
    good.release.set()
    good.shutdown()
    wrong.shutdown()


def _local(tls) -> SafeOutbound:
    return SafeOutbound(
        resolver=_resolver("127.0.0.1"), is_allowed=_only_loopback_counts_as_public, ca_bundle=tls["ca"]
    )


@REAL_MODE
def test_request_goes_to_the_resolved_ip_and_verifies_the_original_name(tls, monkeypatch):
    # requests·urllib3 가 이름을 다시 풀면 되바꾸기를 못 막는다 — 다시 풀면 여기서 터진다.
    real_getaddrinfo = socket.getaddrinfo

    def no_second_lookup(host, *args, **kwargs):
        assert host != HOST, "푼 IP 로 붙어야 한다 — 이름을 다시 풀었다"
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", no_second_lookup)

    response = _local(tls).post_json(
        f"https://{HOST}:{tls['good']}/v1/chat", {"q": "안녕"}, headers={"Authorization": "Bearer t"}, timeout=2
    )

    assert response.status_code == 200
    assert response.json() == {"host": f"{HOST}:{tls['good']}", "sni": HOST, "body": {"q": "안녕"}}


@REAL_MODE
def test_certificate_for_another_name_is_refused(tls):
    with pytest.raises(OutboundRefused) as caught:
        _local(tls).post_json(f"https://{HOST}:{tls['wrong']}/v1", {}, headers={}, timeout=2)
    assert caught.value.reason is OutboundReason.CERTIFICATE


@REAL_MODE
def test_untrusted_certificate_is_refused(tls):
    outbound = SafeOutbound(resolver=_resolver("127.0.0.1"), is_allowed=_only_loopback_counts_as_public)
    with pytest.raises(OutboundRefused) as caught:
        outbound.post_json(f"https://{HOST}:{tls['good']}/v1", {}, headers={}, timeout=2)
    assert caught.value.reason is OutboundReason.CERTIFICATE


@REAL_MODE
def test_redirects_are_not_followed(tls):
    with pytest.raises(OutboundRefused) as caught:
        _local(tls).post_json(f"https://{HOST}:{tls['good']}/redirect", {}, headers={}, timeout=2)
    assert caught.value.reason is OutboundReason.REDIRECT


@REAL_MODE
def test_closed_port_is_unreachable():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    outbound = SafeOutbound(resolver=_resolver("127.0.0.1"), is_allowed=_only_loopback_counts_as_public)
    with pytest.raises(OutboundRefused) as caught:
        outbound.post_json(f"https://{HOST}:{port}/v1", {}, headers={}, timeout=1)
    assert caught.value.reason is OutboundReason.UNREACHABLE
    assert caught.value.reached is False


@REAL_MODE
def test_a_server_that_takes_the_request_but_answers_too_late_is_reached(tls):
    # 연결은 섰다 — 「닿지 않음」(연결 거부·연결 타임아웃)과 갈라야 강의실이 실패로 센다(#603).
    with pytest.raises(OutboundRefused) as caught:
        _local(tls).post_json(f"https://{HOST}:{tls['good']}/slow", {}, headers={}, timeout=0.2)
    assert caught.value.reason is OutboundReason.RESPONSE_FAILED
    assert caught.value.reached is True


@override_settings(CLASSROOM_SCORING_ADAPTER_MODE="fake")
def test_fake_switch_checks_the_shape_without_resolving():
    def must_not_resolve(host, port):  # pragma: no cover - 불리면 실패
        raise AssertionError("fake 에서는 이름도 풀지 않는다")

    outbound = SafeOutbound(resolver=must_not_resolve)
    assert outbound.check("https://scoring.example.com/v1") == []
    for url, reason in [
        ("http://scoring.example.com/", OutboundReason.NOT_HTTPS),
        ("https://backend:8000/", OutboundReason.NOT_PUBLIC),
        ("https://10.0.0.1/", OutboundReason.NOT_PUBLIC),
    ]:
        with pytest.raises(OutboundRefused) as caught:
            outbound.check(url)
        assert caught.value.reason is reason


# --- 비동기 길(`arequest`, #584) — grader 가 쓴다. 같은 보장을 같은 이유로 ----------------------


def _arun(outbound: SafeOutbound, url: str, *, timeout: float = 2, body=None):
    import asyncio

    return asyncio.run(outbound.arequest("POST", url, headers={"X-T": "1"}, timeout=timeout, json=body))


@REAL_MODE
def test_async_request_goes_to_the_resolved_ip_and_verifies_the_original_name(tls, monkeypatch):
    real_getaddrinfo = socket.getaddrinfo

    def no_second_lookup(host, *args, **kwargs):
        assert host != HOST, "푼 IP 로 붙어야 한다 — 이름을 다시 풀었다"
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", no_second_lookup)

    response = _arun(_local(tls), f"https://{HOST}:{tls['good']}/v1/chat", body={"q": "안녕"})

    assert response.status_code == 200
    assert response.json() == {"host": f"{HOST}:{tls['good']}", "sni": HOST, "body": {"q": "안녕"}}


@REAL_MODE
def test_async_certificate_for_another_name_is_refused(tls):
    with pytest.raises(OutboundRefused) as caught:
        _arun(_local(tls), f"https://{HOST}:{tls['wrong']}/v1", body={})
    assert caught.value.reason is OutboundReason.CERTIFICATE


@REAL_MODE
def test_async_untrusted_certificate_is_refused(tls):
    outbound = SafeOutbound(resolver=_resolver("127.0.0.1"), is_allowed=_only_loopback_counts_as_public)
    with pytest.raises(OutboundRefused) as caught:
        _arun(outbound, f"https://{HOST}:{tls['good']}/v1", body={})
    assert caught.value.reason is OutboundReason.CERTIFICATE


@REAL_MODE
def test_async_redirects_are_not_followed(tls):
    with pytest.raises(OutboundRefused) as caught:
        _arun(_local(tls), f"https://{HOST}:{tls['good']}/redirect", body={})
    assert caught.value.reason is OutboundReason.REDIRECT


@REAL_MODE
def test_async_rebinding_to_a_private_address_is_refused_at_connect_time():
    outbound = SafeOutbound(resolver=_resolver("10.0.0.5"))
    with pytest.raises(OutboundRefused) as caught:
        _arun(outbound, f"https://{HOST}/v1", body={})
    assert caught.value.reason is OutboundReason.NOT_PUBLIC


@REAL_MODE
def test_async_closed_port_is_unreachable():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    outbound = SafeOutbound(resolver=_resolver("127.0.0.1"), is_allowed=_only_loopback_counts_as_public)
    with pytest.raises(OutboundRefused) as caught:
        _arun(outbound, f"https://{HOST}:{port}/v1", timeout=1, body={})
    assert caught.value.reason is OutboundReason.UNREACHABLE
    assert caught.value.reached is False


@REAL_MODE
def test_async_a_server_that_answers_too_late_is_reached(tls):
    with pytest.raises(OutboundRefused) as caught:
        _arun(_local(tls), f"https://{HOST}:{tls['good']}/slow", timeout=0.2, body={})
    assert caught.value.reason is OutboundReason.RESPONSE_FAILED
    assert caught.value.reached is True


@override_settings(CLASSROOM_SCORING_ADAPTER_MODE="fake")
def test_async_fake_switch_never_touches_the_network():
    with pytest.raises(OutboundRefused) as caught:
        _arun(SafeOutbound(), "https://scoring.example.com/v1", body={})
    assert caught.value.reason is OutboundReason.OFFLINE


# --- 응답 본문 상한 (#584 점검) — 강사 서버가 끝없이 흘려도 메모리가 마르지 않는다 ------------------

SMALL_LIMIT = override_settings(SAFE_OUTBOUND_RESPONSE_MAX_BYTES=65_536)


@REAL_MODE
@SMALL_LIMIT
def test_a_body_over_the_limit_is_cut_as_a_response_failure_on_the_sync_path(tls):
    with pytest.raises(OutboundRefused) as caught:
        _local(tls).post_json(f"https://{HOST}:{tls['good']}/big", {}, headers={}, timeout=5)
    assert caught.value.reason is OutboundReason.RESPONSE_FAILED
    assert caught.value.reached is True


@REAL_MODE
@SMALL_LIMIT
def test_a_body_over_the_limit_is_cut_as_a_response_failure_on_the_async_path(tls):
    with pytest.raises(OutboundRefused) as caught:
        _arun(_local(tls), f"https://{HOST}:{tls['good']}/big", timeout=5, body={})
    assert caught.value.reason is OutboundReason.RESPONSE_FAILED
    assert caught.value.reached is True


@REAL_MODE
@SMALL_LIMIT
def test_a_body_under_the_limit_still_comes_through_on_both_paths(tls):
    url = f"https://{HOST}:{tls['good']}/v1/chat"
    sync = _local(tls).post_json(url, {"q": "안녕"}, headers={}, timeout=2)
    asynchronous = _arun(_local(tls), url, body={"q": "안녕"})
    assert sync.json() == asynchronous.json()


# --- 연결 타임아웃은 전체 타임아웃과 따로다 — 응답 없는 서버가 슬롯을 오래 쥐지 않는다 ------------------


@REAL_MODE
@override_settings(SAFE_OUTBOUND_CONNECT_TIMEOUT_SECONDS=0.3)
def test_connecting_gives_up_at_the_connect_timeout_not_the_total_one(monkeypatch):
    import time

    # 어디에도 응답하지 않는 주소(TEST-NET-1) — 연결 단계에서 멈춘다. 샌드박스에 라우트가 없으면
    # 바로 UNREACHABLE 로 끝나므로, 어느 쪽이든 전체 타임아웃(30초)을 기다리지 않는다는 것만 못 박는다.
    outbound = SafeOutbound(resolver=_resolver("192.0.2.1"), is_allowed=lambda address: True)
    started = time.monotonic()
    with pytest.raises(OutboundRefused) as caught:
        outbound.post_json(f"https://{HOST}/v1", {}, headers={}, timeout=30)
    assert caught.value.reason is OutboundReason.UNREACHABLE
    assert time.monotonic() - started < 3

    started = time.monotonic()
    with pytest.raises(OutboundRefused) as caught:
        _arun(outbound, f"https://{HOST}/v1", timeout=30, body={})
    assert caught.value.reason is OutboundReason.UNREACHABLE
    assert time.monotonic() - started < 3
