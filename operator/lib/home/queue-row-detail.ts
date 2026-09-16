// 홈 큐 표의 「무엇을 기다리나」 열 문구 — 순수 함수(#427, 시안 `docs/design/
// operator/Home.dc.html`). 값 자체(오래 밀린 날짜 수·대기 구분별 건수)는 이미
// 다른 조회가 갖고 있으므로 여기서는 문구만 조립한다.
export function appealsDetail(pendingCount: number, oldestDays: number | null): string | null {
  if (pendingCount === 0) return null;
  if (oldestDays === null) return null;
  return `가장 오래 밀린 것 ${oldestDays}일`;
}

export function payoutsDetail(identity: number, seller: number, transfer: number): string {
  return `신원 ${identity} · 셀러 ${seller} · 이체 ${transfer}`;
}
