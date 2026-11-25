"use client";

// 메뉴(role=menu)의 초점 규약 — 열리면 첫 항목으로, ↑↓ 는 끝에서 돌아가고 Home/End 는 처음·끝,
// Escape 는 닫고 여는 단추로 돌아온다. 항목을 골라 닫을 때도 여는 단추로 돌아온다(`closeToTrigger`).
import { useCallback, useEffect, useRef, type KeyboardEvent, type RefObject } from "react";

import { nextMenuIndex } from "@/lib/dom/menu-keys";

const ITEMS = '[role^="menuitem"]';

export function useMenuFocus(
  open: boolean,
  menuRef: RefObject<HTMLElement | null>,
  triggerRef: RefObject<HTMLElement | null>,
  close: () => void,
) {
  useEffect(() => {
    if (open) menuRef.current?.querySelector<HTMLElement>(ITEMS)?.focus();
  }, [open, menuRef]);

  const closeToTrigger = useCallback(() => {
    close();
    triggerRef.current?.focus();
  }, [close, triggerRef]);
  const closeRef = useRef(closeToTrigger);
  closeRef.current = closeToTrigger;

  // 초점이 메뉴 밖으로 빠져도(빈 곳을 눌러) Escape 가 먹도록 문서에서 듣는다.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeRef.current();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const onMenuKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>(ITEMS) ?? []);
      const next = nextMenuIndex(event.key, items.indexOf(document.activeElement as HTMLElement), items.length);
      if (next === null) return;
      event.preventDefault();
      items[next]?.focus();
    },
    [menuRef],
  );

  return { onMenuKeyDown, closeToTrigger };
}
