// 공모전 화면(목록·상세) 공통 표시 로직. 금액·기한은 「공모 게시판」 시안대로
// 모노스페이스로 렌더된다(FE-02, #27) — 값 자체의 포맷팅만 여기 모은다. 서버
// 컴포넌트·클라이언트 컴포넌트 양쪽에서 다 쓸 수 있도록 브라우저 전용 API에
// 기대지 않는다(Date, Intl 은 Node 에도 있다).

// 남은 시간 규칙(spec #444, #445) — 모든 화면이 이 함수 하나를 거친다. 예전에는
// 화면마다 따로 계산해 셋이 갈렸다: 목록·랜딩·상세는 날을 올림해 마감 뒤
// 24시간 동안도 「D-day」·「마감 임박」이 켜진 채였고(음수를 올림하면 -0이 돼
// 0과 같게 취급됐다), 제출 화면은 날을 내림해 목록과 다른 D-N을 보였다.
//
// **D-N은 "지금부터 몇 시간 뒤"가 아니라 서울 달력 날짜의 차이다.** 마감일이
// 오늘이면(서버 시간대와 무관하게) 0이고, 그 값을 화면은 "D-day"로 읽는다.
export type RemainingTimeStatus = "remaining" | "imminent" | "closed";

export type RemainingTime = {
  // 남음: 마감 24시간 밖. 임박: 마감 24시간 안쪽이지만 아직 전. 마감: 지났다.
  status: RemainingTimeStatus;
  // 서울 달력 기준 D-N. 마감을 지나면 음수일 수 있지만, 화면은 status가
  // "closed"일 때 이 값을 절대 쓰지 않는다 — 그래서 마감 뒤에도 "D-day"가
  // 보이던 옛 버그가 구조적으로 재발할 수 없다.
  dDay: number;
  // 마감 24시간 안쪽(status === "imminent")에서만 값이 있다. 그 밖에는 null.
  hoursLabel: string | null;
};

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

// UTC 자정 기준 "그 날의 타임스탬프" — 시각을 서울 달력 날짜로 뭉갠 값이다.
// Intl 의 timeZone 옵션은 프로세스의 TZ 환경변수와 무관하게 늘 서울로
// 계산하므로, 서버가 어느 시간대에서 돌든(배포 컨테이너는 UTC) 같은 값이 나온다.
function seoulCalendarDayMs(date: Date): number {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return Date.UTC(get("year"), get("month") - 1, get("day"));
}

export function remainingTime(deadlineAt: string, now: Date = new Date()): RemainingTime {
  const deadline = new Date(deadlineAt);
  const diffMs = deadline.getTime() - now.getTime();
  const dDay = Math.round((seoulCalendarDayMs(deadline) - seoulCalendarDayMs(now)) / DAY_MS);

  // 마감 시각과 정확히 같은 순간도 "마감"이다 — 1분 전은 아직 남은 시간이 있고,
  // 1분 후(또는 정확히 그 순간)는 더 이상 없다.
  if (diffMs <= 0) {
    return { status: "closed", dDay, hoursLabel: null };
  }

  // 「임박」은 마감 전 24시간 안쪽에서만 켜진다 — 예전의 "D-3 이하" 규칙을
  // 대체한다(#444 스펙: 마감 임박 배지는 시간 단위 강조와 같은 경계를 써야
  // "마감까지 3일" 같은 여유 있는 상태를 임박으로 잘못 강조하지 않는다).
  if (diffMs <= DAY_MS) {
    const hours = Math.max(Math.ceil(diffMs / HOUR_MS), 1);
    return { status: "imminent", dDay, hoursLabel: `${hours}시간 남음` };
  }

  return { status: "remaining", dDay, hoursLabel: null };
}

// 목록·랜딩·상세가 보이는 한 줄 문구 — "D-N" 또는 "N시간 남음" 또는 "마감".
export function remainingTimeLabel(deadlineAt: string, now: Date = new Date()): string {
  const remaining = remainingTime(deadlineAt, now);
  if (remaining.status === "closed") return "마감";
  if (remaining.hoursLabel !== null) return remaining.hoursLabel;
  return remaining.dDay === 0 ? "D-day" : `D-${remaining.dDay}`;
}

// 마감 임박 강조(액센트 색) 여부. 마감 뒤에는 절대 켜지지 않는다 — status가
// "imminent"인 경우만 켜지고, "closed"는 별도 상태다.
export function remainingTimeIsImminent(deadlineAt: string, now: Date = new Date()): boolean {
  return remainingTime(deadlineAt, now).status === "imminent";
}

// 상세의 마감 시각. 서버가 어느 시간대에서 돌든(배포 컨테이너는 UTC) 항상
// 서울 시간으로 적는다 — 예전에는 `toLocaleString("ko-KR")`만 써서 서버
// 시간대에 따라 한국 시간과 어긋날 수 있었다.
export function formatDeadlineSeoul(deadlineAt: string): string {
  return new Date(deadlineAt).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
}

// 제출 화면 전용 — 목록·랜딩·상세와 같은 D-N에 초 단위로 줄어드는 시계를
// 붙인다(#445). 마감 24시간 안쪽이어도 D-N 배지 대신 문구를 바꾸지 않는다 —
// 이 화면의 존재 이유가 "정확히 몇 초 남았는가"이므로, 임박 여부는 시계 자체가
// 이미 보여준다.
export function formatSubmitCountdown(deadlineAt: string, now: Date = new Date()): string {
  const remaining = remainingTime(deadlineAt, now);
  if (remaining.status === "closed") return "마감";

  const diffMs = new Date(deadlineAt).getTime() - now.getTime();
  const totalSeconds = Math.floor(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  const clock = `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
  const dLabel = remaining.dDay === 0 ? "D-day" : `D-${remaining.dDay}`;

  return `${dLabel} (${clock} 남음)`;
}

export function formatPrize(amount: number): string {
  return amount.toLocaleString("ko-KR");
}

// 끝난 공모전의 배지 문구(#227 인수조건 — "끝난 공모전이 목록에 나올 때는
// 끝났다는 것이 보인다. 선정완료·심사종료도 마찬가지다"). 예전에는 목록 행이
// `status === "closed"`일 때만 배지를 그렸다 — AWARDED·JUDGING_ENDED는 기본
// 목록에 아예 안 보였으니 드러나지 않았던 격차인데, `closed=true`로 그 둘도
// 목록에 나오게 되면서 배지 없이 섞이면 방문자가 그것이 끝난 공모전인 줄
// 모른다. 라벨은 백엔드 `Contest.Status` 선택지의 한글 이름과 맞춘다
// (backend/contests/models.py) — 같은 상태를 두 화면이 다른 말로 부르지
// 않는다.
const FINISHED_STATUS_LABELS: Record<string, string> = {
  closed: "마감",
  awarded: "선정 완료",
  judging_ended: "심사기간 종료",
};

export function finishedStatusLabel(status: string): string | null {
  return FINISHED_STATUS_LABELS[status] ?? null;
}

// 참가작 수 문구(#106, spec #105). 백엔드(`ContestOut.submission_count`)는 숫자
// 0을 그대로 보낸다 — 그것을 "아직 참가작이 없습니다"로 읽히게 바꾸는 것은
// 화면의 몫이다. 숫자와 문구가 **다른 층**에서 결정된다는 것이 #106 인수조건
// 이고, 이 함수가 그 경계선이다 — 화면은 이 함수 말고 다시 세지 않는다.
export function formatSubmissionCount(count: number): string {
  if (count === 0) return "아직 참가작이 없습니다";
  return `참가작 ${count}건`;
}

// 공개 상세 머리의 개최자 조각(#908). 이름이 비어 있으면(null·공백) 조각 자체를 그리지
// 않는다 — 빈 「개최 ·」 이 남지 않게 하는 경계가 이 함수다.
export function sponsorLine(displayName: string | null | undefined): string | null {
  const name = displayName?.trim();
  return name ? `개최 · ${name}` : null;
}
