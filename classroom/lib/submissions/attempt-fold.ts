// 채점 완료 알림(#329)은 `#submission-{id}` 앵커로 특정 시도를 가리킨다 —
// 「내 시도」는 한 줄씩이고 판정은 접혀 있으니(#640) 그 줄의 판정을 펼치고 그 줄로 옮긴다.

export function attemptIdFromHash(hash: string): number | null {
  const match = /^#submission-(\d+)$/.exec(hash);
  return match ? Number(match[1]) : null;
}
