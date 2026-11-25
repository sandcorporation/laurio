"use client";

// 확인창(role=alertdialog)의 초점 규약 — 열리면 안전한 쪽으로, Tab 은 창 안에 갇히고, Escape 로 닫히며,
// 닫히면 연 단추로 돌아온다. 연 단추가 닫히며 사라졌으면 `fallbackFocus` 가 돌려주는 자리(머리글 등)로 간다.
// 가장자리 셈은 순수 함수(`lib/dom/focus-trap`)가 진다.
import { useEffect, useId, useRef, type RefObject } from "react";

import { trapTabTarget } from "@/lib/dom/focus-trap";

const FOCUSABLE =
  'button:not([disabled]), a[href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useDialogFocus(
  dialogRef: RefObject<HTMLElement | null>,
  options: {
    onEscape: () => void;
    /** 열릴 때 초점을 받을 곳(안전한 쪽) — 없으면 창 안 첫 초점 대상. */
    initialFocus?: RefObject<HTMLElement | null>;
    /** 연 단추가 닫히며 사라졌을 때 초점을 받을 곳. */
    fallbackFocus?: () => HTMLElement | null;
  },
) {
  const { onEscape, initialFocus, fallbackFocus } = options;
  // 창 본문(질문·결과·금액)을 가리키는 id — 창 요소의 aria-describedby 와 본문 요소의 id 에 같이 건다.
  const descriptionId = useId();
  const opener = useRef<HTMLElement | null>(null);
  const fallback = useRef(fallbackFocus);
  fallback.current = fallbackFocus;

  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    (initialFocus?.current ?? dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE))?.focus();
    return () => {
      const back = opener.current?.isConnected && opener.current !== document.body ? opener.current : null;
      const target = back ?? fallback.current?.() ?? null;
      if (!document.activeElement || document.activeElement === document.body) target?.focus();
    };
    // 열릴 때 한 번만.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 창 안을 눌러 초점이 body 로 빠져도 Escape·Tab 이 먹도록 문서에서 듣는다.
  const onEscapeRef = useRef(onEscape);
  onEscapeRef.current = onEscape;
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onEscapeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
      const target = trapTabTarget(event.shiftKey, items.indexOf(document.activeElement as HTMLElement), items.length);
      if (target === null) return;
      event.preventDefault();
      items[target]?.focus();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [dialogRef]);
  return { descriptionId };
}
