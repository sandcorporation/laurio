"use client";

// WAI-ARIA 탭 규약 한 곳(#1478 1번) — 고른 탭만 tabIndex 0, ←/→·Home/End 로 이동(고르는 즉시 활성),
// 탭 `aria-controls` ↔ 패널 `aria-labelledby`. 탭마다 패널이 따로 있으면 `panels: "each"`,
// 한 패널의 내용이 바뀌면 기본값(`"shared"`). 탭 목록은 그려진 `[role=tab]` 에서 읽는다(보이는 탭만 오간다).
import { useId, useRef, type KeyboardEvent } from "react";

import { nextTabIndex } from "@/lib/dom/tab-keys";

export function useTablist<K extends string>(
  active: K,
  options: { panels?: "shared" | "each"; id?: string } = {},
) {
  const generated = useId();
  const base = options.id ?? generated;
  const listRef = useRef<HTMLDivElement>(null);
  const each = options.panels === "each";
  const tabId = (key: K) => `${base}-tab-${key}`;
  const panelId = (key: K) => (each ? `${base}-panel-${key}` : `${base}-panel`);

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    const tabs = Array.from(
      listRef.current?.querySelectorAll<HTMLElement>("[role=tab]") ?? [],
    );
    // 눌린 탭을 기준으로 — 고른 탭이 바뀌어 다시 그려지기 전에 키가 연달아 와도 어긋나지 않는다.
    const from = tabs.findIndex((tab) => tab.contains(event.target as Node));
    const next = nextTabIndex(
      event.key,
      from >= 0 ? from : tabs.findIndex((tab) => tab.id === tabId(active)),
      tabs.length,
    );
    if (next === null) return;
    event.preventDefault();
    // 고르는 즉시 활성 — 단추든 링크든 클릭이 전환을 맡는다.
    tabs[next].focus();
    tabs[next].click();
  }

  return {
    listProps: { ref: listRef, role: "tablist" as const, onKeyDown },
    tabProps: (key: K) => ({
      id: tabId(key),
      role: "tab" as const,
      "aria-selected": active === key,
      "aria-controls": panelId(key),
      tabIndex: active === key ? 0 : -1,
    }),
    panelProps: (key: K = active) => ({
      id: panelId(key),
      role: "tabpanel" as const,
      "aria-labelledby": tabId(each ? key : active),
    }),
  };
}
