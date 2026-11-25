// 확인창·시트가 닫힐 때 초점이 돌아갈 곳을 고른다 — react·DOM 없이 도는 순수 함수(ADR-0026).
// 연 단추(클릭의 currentTarget)를 알면 그것이 열릴 때의 activeElement 보다 앞선다. 낭독기 활성화·일부 터치는
// 초점을 옮기지 않아 activeElement 가 body 이기 때문이다.
export type FocusTarget = { readonly isConnected: boolean };

export function pickOpener<T>(given: T | null | undefined, active: T | null): T | null {
  return given ?? active;
}

// 돌아갈 곳: 닫힌 뒤에도 문서에 있고 body 가 아닌 연 단추 → 아니면 fallback(머리글 등) → 아니면 없음.
export function pickReturnTarget<T extends FocusTarget>(
  opener: T | null,
  body: T | null,
  fallback: (() => T | null) | undefined,
): T | null {
  const back = opener && opener.isConnected && opener !== body ? opener : null;
  return back ?? fallback?.() ?? null;
}
