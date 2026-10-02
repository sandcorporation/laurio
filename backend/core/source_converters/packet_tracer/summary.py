"""해독된 Packet Tracer XML 에서 채점에 쓸 사실만 텍스트로 뽑는다 (#497).

XML 은 파일당 약 1MB 인데 그 대부분이 화면 배치(`PHYSICALWORKSPACE` 등)라 그대로
실을 수 없다. 장비(이름·종류·모델), 라우터·스위치의 running-config 원문, 그 밖의
장비(PC·서버·노트북)의 포트 주소·게이트웨이·DNS, 그리고 결선만 옮긴다. 화면
배치·아이콘·명령 로그·옵션은 싣지 않는다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter

#: 포트 종류(`PORT/TYPE`)에서 Packet Tracer 가 화면에 쓰는 포트 이름의 머리로.
#: running-config 가 없는 장비(PC·서버)는 포트 이름이 XML 에 따로 없어, 종류별로
#: 0 부터 세어 붙인다 — PC 의 `FastEthernet0` 이 그렇게 나온다.
_PORT_NAME_BY_TYPE = {
    "eCopperFastEthernet": "FastEthernet",
    "eFiberFastEthernet": "FastEthernet",
    "eCopperGigabitEthernet": "GigabitEthernet",
    "eFiberGigabitEthernet": "GigabitEthernet",
    "eCopperEthernet": "Ethernet",
    "eSerial": "Serial",
    "eHostWireless": "Wireless",
    "eBluetooth": "Bluetooth",
}

_CABLE_NAMES = {
    "eStraightThrough": "스트레이트",
    "eCrossOver": "크로스오버",
    "eFiber": "광",
    "eSerialDCE": "시리얼(DCE)",
    "eSerialDTE": "시리얼(DTE)",
    "eConsole": "콘솔",
    "eRollOver": "롤오버",
    "eCoaxial": "동축",
    "ePhone": "전화선",
    "eOctal": "옥탈",
    "eUsb": "USB",
}


def _text(element: ET.Element | None, path: str) -> str:
    return ((element.findtext(path) if element is not None else None) or "").strip()


def _running_config(engine: ET.Element) -> list[str]:
    """빈 줄과 연속된 `!` 를 하나로 줄인다 — 설정의 뜻은 그대로고 예산만 아낀다."""

    lines: list[str] = []
    for line in engine.findall("RUNNINGCONFIG/LINE"):
        text = (line.text or "").rstrip()
        if not text:
            continue
        if text == "!" and lines and lines[-1] == "!":
            continue
        lines.append(text)
    return lines


def _host_ports(engine: ET.Element) -> list[str]:
    seen: Counter[str] = Counter()
    out: list[str] = []
    for port in engine.iter("PORT"):
        port_type = _text(port, "TYPE")
        if not port_type:
            continue  # 결선(LINK)의 PORT 처럼 이름만 든 요소다.
        head = _PORT_NAME_BY_TYPE.get(port_type, port_type.removeprefix("e"))
        name = f"{head}{seen[head]}"
        seen[head] += 1
        ip, subnet = _text(port, "IP"), _text(port, "SUBNET")
        dhcp = _text(port, "PORT_DHCP_ENABLE") == "true"
        if dhcp:
            address = f"DHCP 로 받음(지금 값 {ip}/{subnet})" if ip else "DHCP 로 받음"
        elif ip:
            address = f"{ip}/{subnet}"
        else:
            continue
        out.append(f"  {name}: {address}")
    return out


def summarize(xml: bytes) -> str:
    root = ET.fromstring(xml)
    network = root.find("NETWORK")
    version = _text(root, "VERSION")
    lines = [f"Packet Tracer 파일 요약(버전 {version or '알 수 없음'}) — 장비·설정·주소·결선만 옮겼다."]

    names_by_ref: dict[str, str] = {}
    device_blocks: list[list[str]] = []
    for device in network.findall("DEVICES/DEVICE") if network is not None else []:
        engine = device.find("ENGINE")
        if engine is None:
            continue
        name = _text(engine, "NAME")
        kind_element = engine.find("TYPE")
        kind = (kind_element.text or "").strip() if kind_element is not None else ""
        model = kind_element.get("model", "") if kind_element is not None else ""
        names_by_ref[_text(engine, "SAVE_REF_ID")] = name

        block = [f"[{name}] {kind}" + (f" (모델 {model})" if model and model != kind else "")]
        config = _running_config(engine)
        if config:
            block.append("  running-config:")
            block.extend(f"    {line}" for line in config)
        else:
            block.extend(_host_ports(engine))
            gateway = _text(engine, "GATEWAY")
            if gateway:
                block.append(f"  기본 게이트웨이: {gateway}")
            dns = _text(engine, "DNS_CLIENT/SERVER_IP")
            if dns:
                block.append(f"  DNS 서버: {dns}")
        device_blocks.append(block)

    lines.append("")
    lines.append(f"== 장비 {len(device_blocks)}대 ==")
    for block in device_blocks:
        lines.extend(block)

    links = network.findall("LINKS/LINK") if network is not None else []
    lines.append("")
    lines.append(f"== 결선 {len(links)}개 ==")
    for link in links:
        cable = link.find("CABLE")
        if cable is None:
            continue
        ports = [(p.text or "").strip() for p in cable.findall("PORT")]
        a_port, b_port = (ports + ["", ""])[:2]
        a = names_by_ref.get(_text(cable, "FROM"), "?")
        b = names_by_ref.get(_text(cable, "TO"), "?")
        cable_type = _text(cable, "TYPE")
        kind = _CABLE_NAMES.get(cable_type, cable_type.removeprefix("e") or "?")
        lines.append(f"  {a} {a_port} ↔ {b} {b_port} ({kind})")

    return "\n".join(lines) + "\n"
