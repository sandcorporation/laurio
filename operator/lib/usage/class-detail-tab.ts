// 클래스 사용 현황(#494)의 탭은 주소에 산다(`?tab=problems|days`) — 기간(`from`·`to`)과
// 함께 실려서, 주소를 공유하거나 새로고침해도 같은 탭이 같은 기간으로 열린다. 모르는
// 값이나 빈 값은 첫 탭(문제별)이다 — 그 경우 주소에 `tab` 을 싣지 않는다.
import type { UsagePeriod } from "./period";

export type ClassDetailTab = "problems" | "days";

export const CLASS_DETAIL_TABS: readonly { key: ClassDetailTab; label: string }[] = [
  { key: "problems", label: "문제별" },
  { key: "days", label: "날짜 × 문제" },
];

const DEFAULT_TAB: ClassDetailTab = "problems";

export function tabFromSearchParams(params: { get(name: string): string | null }): ClassDetailTab {
  const raw = params.get("tab");
  return CLASS_DETAIL_TABS.some((tab) => tab.key === raw) ? (raw as ClassDetailTab) : DEFAULT_TAB;
}

/** 탭과 기간을 쿼리 문자열로 — 빈 값과 기본 탭은 싣지 않는다. 앞에 `?` 를 붙이고, 비면 "" 다. */
export function classDetailQuery(period: UsagePeriod, tab: ClassDetailTab): string {
  const search = new URLSearchParams();
  if (period.from) search.set("from", period.from);
  if (period.to) search.set("to", period.to);
  if (tab !== DEFAULT_TAB) search.set("tab", tab);
  const text = search.toString();
  return text ? `?${text}` : "";
}
