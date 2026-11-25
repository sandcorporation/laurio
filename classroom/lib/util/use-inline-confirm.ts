// 줄 안에서 한 번 더 묻는 확인의 초점·Esc (#1400). 열면 「그대로 두기」 쪽(안전한 단추)에 초점이 가고,
// Esc 는 닫는다. 닫혀서 초점을 쥔 단추가 사라지면(초점이 `body`) 확인을 연 단추로 돌려준다 —
// 초점이 이미 다른 곳에 있으면(다른 줄의 확인을 연 경우) 빼앗지 않는다.
import { useEffect, useRef, type KeyboardEvent } from "react";

export function useInlineConfirm(open: boolean, close: () => void) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open) {
      keepRef.current?.focus();
    } else if (wasOpen.current && (document.activeElement === null || document.activeElement === document.body)) {
      triggerRef.current?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  function onKeyDown(event: KeyboardEvent) {
    // 요청이 가는 동안에는 「그대로 두기」가 disabled 라 Esc 도 닫지 않는다.
    if (!open || event.key !== "Escape" || keepRef.current?.disabled) return;
    event.stopPropagation();
    close();
  }

  return { triggerRef, keepRef, onKeyDown };
}
