// 참여자 문제 화면의 「내 시도」는 가장 최근 시도 하나만 펼쳐 둔다 — 고쳐서
// 다시 내는 것이 정상적인 쓰임이라 시도가 수십 개 쌓이면 화면이 판정 목록으로
// 끝없이 길어진다. 방금 낸 시도의 채점 상태는 늘 보여야 하므로 최근 것은
// 접지 않는다.
//
// 채점 완료 알림(#329)은 `#submission-{id}` 앵커로 특정 시도를 가리킨다 —
// 그것이 지난 시도면 화면이 스스로 펼쳐야 링크가 제자리에 닿는다.

type Attempt = { id: number; attempt_number: number };

export function splitAttempts<T extends Attempt>(submissions: T[]): { latest: T | null; older: T[] } {
  const sorted = [...submissions].sort((a, b) => b.attempt_number - a.attempt_number);
  const [latest = null, ...older] = sorted;
  return { latest, older };
}

export function attemptIdFromHash(hash: string): number | null {
  const match = /^#submission-(\d+)$/.exec(hash);
  return match ? Number(match[1]) : null;
}
