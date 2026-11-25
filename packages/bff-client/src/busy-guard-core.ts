// 진행 중 단추는 `disabled` 가 아니라 `aria-disabled` 로 둔다 — `disabled` 는 눌린 단추의 초점을
// BODY 로 떨군다. 대신 `aria-disabled="true"` 단추의 누름(마우스·터치·Enter·Space·폼 암묵 제출)을
// 문서 한 곳에서 막는다.

type Closest = { closest(selector: string): unknown };

export const BUSY_BUTTON_SELECTOR = 'button[aria-disabled="true"], [role="button"][aria-disabled="true"]';

/** 누른 자리가 `aria-disabled="true"` 단추 안이면 참 — 그 누름은 버려야 한다. */
export function isBlockedByBusyButton(target: unknown): boolean {
  if (!target || typeof (target as Closest).closest !== "function") return false;
  return (target as Closest).closest(BUSY_BUTTON_SELECTOR) !== null;
}
