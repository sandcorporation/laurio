// 공모전 화면(목록·상세) 공통 표시 로직. 금액·기한은 「공모 게시판」 시안대로
// 모노스페이스로 렌더된다(FE-02, #27) — 값 자체의 포맷팅만 여기 모은다. 서버
// 컴포넌트·클라이언트 컴포넌트 양쪽에서 다 쓸 수 있도록 브라우저 전용 API에
// 기대지 않는다(Date, Intl 은 Node 에도 있다).

// 마감까지 남은 일수. 자정 기준이 아니라 "지금부터 몇 시간 뒤"를 올림한 값이라,
// 마감 당일에도 D-0 이 아니라 D-1 로 보일 수 있다 — 사용자가 손해 보는 방향으로
// 반올림해 "아직 하루 남았다"는 착각을 주지 않는다.
export function daysUntil(deadlineAt: string, now: Date = new Date()): number {
  const diffMs = new Date(deadlineAt).getTime() - now.getTime();
  return Math.ceil(diffMs / (1000 * 60 * 60 * 24));
}

export function formatDday(deadlineAt: string, now: Date = new Date()): string {
  const days = daysUntil(deadlineAt, now);
  if (days < 0) return "마감";
  if (days === 0) return "D-day";
  return `D-${days}`;
}

// 마감 임박의 기준선. 「공모 게시판」 시안(design/Main.dc.html)이 D-3·D-2 행을
// 액센트 색으로 구분한 것을 그대로 따라 3일 이하를 임박으로 잡는다.
export const IMMINENT_DEADLINE_DAYS = 3;

export function isImminent(deadlineAt: string, now: Date = new Date()): boolean {
  const days = daysUntil(deadlineAt, now);
  return days >= 0 && days <= IMMINENT_DEADLINE_DAYS;
}

export function formatPrize(amount: number): string {
  return amount.toLocaleString("ko-KR");
}

// 참가작 수 문구(#106, spec #105). 백엔드(`ContestOut.submission_count`)는 숫자
// 0을 그대로 보낸다 — 그것을 "아직 참가작이 없습니다"로 읽히게 바꾸는 것은
// 화면의 몫이다. 숫자와 문구가 **다른 층**에서 결정된다는 것이 #106 인수조건
// 이고, 이 함수가 그 경계선이다 — 화면은 이 함수 말고 다시 세지 않는다.
export function formatSubmissionCount(count: number): string {
  if (count === 0) return "아직 참가작이 없습니다";
  return `참가작 ${count}건`;
}
