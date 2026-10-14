// 「3분 전」 같은 짧은 상대 시각 — 클래스 상세의 문제 표 「최근 제출」 칸과 「최근 제출」 카드가
// 같은 말로 적는다. 하루를 넘으면 「어제」·「n일 전」, 한 달을 넘으면 날짜다. 값이 없으면 「—」.
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function formatRelativeTime(iso: string | null, now: number = Date.now()): string {
  if (iso === null) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const diff = Math.max(0, now - then);
  if (diff < MINUTE) return "방금";
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}분 전`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}시간 전`;
  const days = Math.floor(diff / DAY);
  if (days === 1) return "어제";
  if (days < 30) return `${days}일 전`;
  return new Date(then).toLocaleDateString("ko-KR");
}
