"use client";

// 메뉴 단추의 초점 규약(#1471 ⑥, WAI-ARIA menu button) — 열면 첫 항목으로, ↑↓·Home/End 로 오가고, Escape 는 닫고
// 여는 단추로, Tab 은 닫고 여는 단추에서 이어 간다. 키 셈은 순수 함수(`lib/dom/menu-keys`)가 진다.
// 꺼진 항목은 초점을 받지 못하니 건너뛴다(눌리지 않는 단추에 초점이 서면 낭독기가 막힌다).
import { useCallback, useEffect, type KeyboardEvent, type RefObject } from "react";

import { nextMenuIndex } from "@/lib/dom/menu-keys";

const ITEMS = '[role^="menuitem"]:not([disabled])';

export function useMenuFocus({
  open,
  setOpen,
  triggerRef,
  menuRef,
  containerRef,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: RefObject<HTMLElement | null>;
  menuRef: RefObject<HTMLElement | null>;
  /** 주면 이 밖을 눌러도 닫는다. */
  containerRef?: RefObject<HTMLElement | null>;
}) {
  useEffect(() => {
    if (open) menuRef.current?.querySelector<HTMLElement>(ITEMS)?.focus();
  }, [open, menuRef]);

  useEffect(() => {
    if (!open || !containerRef) return;
    const close = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, containerRef, setOpen]);

  /** 항목을 눌러 닫을 때 — 사라질 항목에 있던 초점을 여는 단추로 돌린다. */
  const closeToTrigger = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, [setOpen, triggerRef]);

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      if (event.key === "Escape" || event.key === "Tab") {
        if (event.key === "Escape") event.preventDefault();
        closeToTrigger();
        return;
      }
      const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>(ITEMS) ?? []);
      const next = nextMenuIndex(event.key, items.indexOf(document.activeElement as HTMLElement), items.length);
      if (next === null) return;
      event.preventDefault();
      items[next]?.focus();
    },
    [menuRef, closeToTrigger],
  );

  return { onKeyDown, closeToTrigger };
}
