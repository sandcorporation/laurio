// 약관 시행일 표시(#892) — 시행일 전에는 「개정 예정 · 시행일 …」, 시행일부터는 「시행일 …」.
// 서버 렌더링 시점의 날짜(KST)와 시행일을 견줘 저절로 넘어간다(루트 레이아웃이 force-dynamic 이라
// 다시 배포하지 않아도 된다). 날짜는 주입할 수 있어 시험이 시계를 만지지 않는다.

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/** 지금(UTC 순간)이 한국 날짜로 며칠인지 `YYYY-MM-DD` 로. */
export function kstDate(now: Date): string {
  return new Date(now.getTime() + KST_OFFSET_MS).toISOString().slice(0, 10);
}

/** `YYYY-MM-DD` → 「2026년 11월 12일」. */
export function koreanDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

/** 시행일(`YYYY-MM-DD`) 당일부터 시행 중이다. 문자열 비교가 날짜 순서와 같다. */
export function isInForce(effectiveIso: string, now: Date): boolean {
  return kstDate(now) >= effectiveIso;
}

export function effectiveNotice(effectiveIso: string, now: Date): string {
  const label = `시행일 ${koreanDate(effectiveIso)}`;
  return isInForce(effectiveIso, now) ? label : `개정 예정 · ${label}`;
}
