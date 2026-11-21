"""공모전 상장 한 장을 A4 가로 PDF 로 만든다(#1126, 스펙 #1071).

틀은 하나다 — 금색 두 줄 테(스펙 「틀」 다안). 글꼴은 이 앱의 `fonts/` 에 담긴 것만 쓰고
바깥 글꼴 서버에 기대지 않는다(#743 과 같은 이유). WeasyPrint 가 PDF 에 서브셋으로 넣는다.

WeasyPrint 는 `word-break: keep-all` 을 따르지 않는다 — 그대로 두면 「뛰어/난」처럼 어절
가운데서 줄이 바뀐다. 그래서 본문은 어절마다 줄바꿈 없는 span 으로 감싼다(`_keep_words`).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import segno
from django.conf import settings

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

#: 확인 주소의 바탕 — 운영은 `CODEMIT_WEB_ORIGIN`, 비어 있으면(dev·시험) 서비스 주소.
DEFAULT_PUBLIC_ORIGIN = "https://codemit.kr"


@dataclass(frozen=True)
class CertificateText:
    """개최자가 칸마다 입력하는 문구(스펙 결정 3)."""

    award_name: str
    recipient_name: str
    body: str
    giver_name: str
    giver_title: str
    award_date: date


@dataclass(frozen=True)
class CertificateSheet:
    """한 장을 그리는 데 드는 전부 — 입력 문구와 고칠 수 없는 자동 칸."""

    text: CertificateText
    contest_title: str
    number: str
    verify_url: str
    preview: bool = False


def public_origin() -> str:
    return getattr(settings, "PUBLIC_WEB_ORIGIN", "") or DEFAULT_PUBLIC_ORIGIN


def verify_url(token: str) -> str:
    return f"{public_origin()}/c/{token}"


def format_korean_date(value: date) -> str:
    return f"{value.year}년 {value.month}월 {value.day}일"


def _keep_words(text: str) -> str:
    words = text.split()
    return " ".join(f'<span class="w">{html.escape(word)}</span>' for word in words)


def _qr_data_uri(url: str) -> str:
    return segno.make(url, error="m").svg_data_uri(dark="#1d2421", border=0)


def _display_url(url: str) -> str:
    return url.split("://", 1)[-1]


_GOLD = "#7d5f1c"

_CSS = f"""
@font-face {{ font-family: "Certificate Serif"; font-weight: 400;
  src: url("{(FONTS_DIR / 'GowunBatang-Regular.woff').as_uri()}"); }}
@font-face {{ font-family: "Certificate Serif"; font-weight: 700;
  src: url("{(FONTS_DIR / 'GowunBatang-Bold.woff').as_uri()}"); }}
@page {{ size: 297mm 210mm; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: "Certificate Serif"; color: #1d2421; }}
.sheet {{ position: relative; width: 297mm; height: 210mm; overflow: hidden; background: #fffdf8; }}
.outer {{ position: absolute; top: 9.5mm; left: 9.5mm; right: 9.5mm; bottom: 9.5mm;
  border: 0.75mm solid {_GOLD}; }}
.inner-line {{ position: absolute; top: 11.6mm; left: 11.6mm; right: 11.6mm; bottom: 11.6mm;
  border: 0.25mm solid {_GOLD}; }}
.no {{ position: absolute; top: 18mm; left: 24mm; font-size: 10.5pt; letter-spacing: 0.05em; }}
.title {{ position: absolute; top: 25mm; left: 0; right: 0; text-align: center;
  font-weight: 700; font-size: 52pt; letter-spacing: 13pt; padding-left: 13pt; }}
.mid {{ position: absolute; top: 66mm; left: 24mm; right: 24mm; height: 88mm; text-align: center; }}
.award {{ font-weight: 700; font-size: 22pt; letter-spacing: 3pt; margin: 0 0 5mm; }}
.who {{ font-size: 17.5pt; margin: 0 0 3mm; }}
.who b {{ font-weight: 700; font-size: 24.5pt; letter-spacing: 2.5pt; margin-left: 2mm; }}
.contest {{ font-family: "Certificate Serif"; font-size: 11pt; color: #4b544f; margin: 0 0 6mm; }}
.body {{ font-size: 14.5pt; line-height: 1.9; width: 178mm; margin: 0 auto; }}
.w {{ white-space: nowrap; }}
.date {{ position: absolute; left: 24mm; bottom: 31mm; font-size: 14pt; }}
.giver {{ position: absolute; left: 0; right: 0; bottom: 30mm; text-align: center;
  font-weight: 700; font-size: 17.5pt; letter-spacing: 1.5pt; }}
.giver small {{ display: block; font-size: 11.5pt; font-weight: 400; letter-spacing: 0; margin-bottom: 1mm; }}
.qr {{ position: absolute; right: 24mm; bottom: 27mm; width: 22mm; height: 22mm; }}
.qr img {{ width: 22mm; height: 22mm; }}
.qr-caption {{ position: absolute; right: 24mm; bottom: 21.5mm; width: 60mm; text-align: right;
  font-family: "Certificate Serif"; font-size: 7pt; color: #4b544f; }}
.issuer {{ position: absolute; left: 0; right: 0; bottom: 15mm; text-align: center;
  font-family: "Certificate Serif"; font-size: 8pt; color: #6b736f; letter-spacing: 0.05em; }}
.preview-mark {{ position: absolute; top: 80mm; left: 0; right: 0; text-align: center;
  font-family: "Certificate Serif"; font-weight: 700; font-size: 96pt; color: rgba(162, 53, 43, 0.14);
  transform: rotate(-18deg); letter-spacing: 12pt; }}
"""


def certificate_html(sheet: CertificateSheet) -> str:
    text = sheet.text
    giver_title = (
        f"<small>{html.escape(text.giver_title)}</small>" if text.giver_title.strip() else ""
    )
    body = f'<p class="body">{_keep_words(text.body)}</p>' if text.body.strip() else ""
    preview = '<div class="preview-mark">미리보기</div>' if sheet.preview else ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>상장 {html.escape(sheet.number)}</title>
<style>{_CSS}</style></head>
<body><div class="sheet">
<div class="outer"></div><div class="inner-line"></div>
<div class="no">제 {html.escape(sheet.number)} 호</div>
<div class="title">상장</div>
<div class="mid">
<p class="award">{html.escape(text.award_name)}</p>
<p class="who">성명<b>{html.escape(text.recipient_name)}</b></p>
<p class="contest">{html.escape(sheet.contest_title)}</p>
{body}
</div>
<div class="date">{format_korean_date(text.award_date)}</div>
<div class="giver">{giver_title}{html.escape(text.giver_name)}</div>
<div class="qr"><img src="{_qr_data_uri(sheet.verify_url)}" alt=""></div>
<div class="qr-caption">{html.escape(_display_url(sheet.verify_url))}</div>
<div class="issuer">codemit에서 발급</div>
{preview}
</div></body></html>"""


def render_certificate_pdf(sheet: CertificateSheet) -> bytes:
    # WeasyPrint 는 시스템 라이브러리(pango)를 불러 무겁다 — 상장을 그릴 때만 불러온다.
    from weasyprint import HTML

    return HTML(string=certificate_html(sheet), base_url=str(FONTS_DIR)).write_pdf()
