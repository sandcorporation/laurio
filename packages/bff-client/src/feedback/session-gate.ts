// 제보 창의 열기 요청 번호(#1503 ⑤) — 캡처처럼 기다리는 일이 끝났을 때 그 사이 창이 닫혔거나 다시 열렸다면 늦은 결과를 버린다.
// 닫을 때 `invalidate()` 로 번호를 올리면 진행 중이던 요청은 `isCurrent()` 가 거짓이다.

export type SessionGate = {
  /** 새 요청을 시작하고 그 번호를 돌려준다 — 앞선 요청은 모두 낡은 것이 된다. */
  begin: () => number;
  /** 진행 중인 요청을 모두 낡은 것으로 만든다. */
  invalidate: () => void;
  isCurrent: (ticket: number) => boolean;
};

export function createSessionGate(): SessionGate {
  let current = 0;
  return {
    begin: () => ++current,
    invalidate: () => {
      current += 1;
    },
    isCurrent: (ticket) => ticket === current,
  };
}
