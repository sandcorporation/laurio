// 「사용 현황」의 기간은 주소(`?from=&to=`)에 산다(#492) — 그 주소를 공유하면 같은
// 화면이 열리고, 클래스 상세(#494)로 넘어갈 때도 이 쿼리를 그대로 들고 간다.
// 비어 있으면 백엔드가 기본값(오늘을 포함한 최근 30일, 서울 날짜)을 정한다 —
// 화면이 「오늘」을 따로 계산하지 않는다.

export interface UsagePeriod {
  from: string | null;
  to: string | null;
}

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function clean(raw: string | null): string | null {
  return raw && DAY_PATTERN.test(raw) ? raw : null;
}

export function periodFromSearchParams(params: { get(name: string): string | null }): UsagePeriod {
  return { from: clean(params.get("from")), to: clean(params.get("to")) };
}

/** 기간을 쿼리 문자열로 — 빈 값은 싣지 않는다. 앞에 `?` 를 붙여 돌려주고, 비면 "" 다. */
export function periodQuery(period: UsagePeriod): string {
  const search = new URLSearchParams();
  if (period.from) search.set("from", period.from);
  if (period.to) search.set("to", period.to);
  const text = search.toString();
  return text ? `?${text}` : "";
}
