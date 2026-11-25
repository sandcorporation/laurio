"use client";

import { useEffect } from "react";

import { isBlockedByBusyButton } from "./busy-guard-core";

/** 앱 루트에 한 번 둔다 — 캡처 단계라 React 핸들러·폼 제출보다 먼저 닿는다. */
export function BusyGuard() {
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!isBlockedByBusyButton(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);
  return null;
}
