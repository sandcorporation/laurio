"""Packet Tracer `.pkt` 해독부 — Unpacket 에서 들여왔다 (#497).

출처: https://github.com/Punkcake21/Unpacket (MIT, 저작권 고지는 같은 디렉터리의
`LICENSE`), 커밋 `54cb6d6a9b46c6b4973356258cb8df6ae58b2ec7`. PyPI 패키지가 아니고
Twofish 가 표준 암호 라이브러리(`cryptography`)에 없어 소스째 들여온다 — 런타임에
외부에서 받는 것은 없다.

- `twofish.py`·`cmac.py`·`ctr.py` — 원본 `Decipher/` 그대로다. `twofish.py` 머리의
  Gladman·Edstrom 고지는 지우지 않는다(그 고지가 요구하는 조건이다).
- `eax.py` — 원본 `Decipher/eax.py` 에서 **복호화 전에 태그를 먼저 검증**하도록
  순서만 바꿨다. 원본은 파일 전체를 CTR 로 푼 뒤에야 태그를 비교해, Packet Tracer
  파일이 아닌 바이너리에도 순수 파이썬 Twofish 를 두 번 돌렸다.
- `crypto.py` — 원본 `Decipher/pt_crypto.py`(해독)와 `repacket.py`(역방향, 테스트
  픽스처용)를 합쳤다. 압축 해제에 상한을 걸고, 실패를 `PacketTracerDecodeError`
  하나로 모았다.
"""
