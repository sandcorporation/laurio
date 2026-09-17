import { describe, expect, it } from "vitest";

import {
  formatDeadlineSeoul,
  formatSubmitCountdown,
  remainingTime,
  remainingTimeIsImminent,
  remainingTimeLabel,
} from "./contest-format";

describe("remainingTime", () => {
  it("서울 자정 경계 — 마감 하루 전날 23:59(서울)엔 아직 D-1, 자정을 넘으면 D-day", () => {
    // 마감: 2026-09-17 15:00 UTC(=2026-09-18 00:00 KST, 서울 자정)
    const deadline = "2026-09-17T15:00:00.000Z";
    // 지금: 2026-09-17 14:59:59.999Z = 2026-09-17 23:59:59.999 KST(마감 전날)
    const beforeMidnight = new Date("2026-09-17T14:59:59.999Z");
    expect(remainingTime(deadline, beforeMidnight).dDay).toBe(1);
    // 지금: 2026-09-17 15:00:00.001Z = 2026-09-18 00:00:00.001 KST(마감 당일로 넘어감)
    const afterMidnight = new Date("2026-09-17T15:00:00.001Z");
    expect(remainingTime(deadline, afterMidnight).dDay).toBe(0);
  });

  it("마감 1분 전엔 아직 남음(임박), 1분 후엔 마감", () => {
    const deadline = "2026-09-17T00:00:00.000Z";
    const oneMinuteBefore = new Date("2026-09-16T23:59:00.000Z");
    expect(remainingTime(deadline, oneMinuteBefore).status).toBe("imminent");

    const oneMinuteAfter = new Date("2026-09-17T00:01:00.000Z");
    expect(remainingTime(deadline, oneMinuteAfter).status).toBe("closed");

    // 정확히 마감 그 순간도 이미 "마감"이다.
    const exactly = new Date("2026-09-17T00:00:00.000Z");
    expect(remainingTime(deadline, exactly).status).toBe("closed");
  });

  it("24시간 경계 — 24시간 안쪽은 임박, 그 밖은 남음", () => {
    const deadline = "2026-09-20T00:00:00.000Z";
    const exactly24hBefore = new Date("2026-09-19T00:00:00.000Z");
    expect(remainingTime(deadline, exactly24hBefore).status).toBe("imminent");

    const justOver24hBefore = new Date("2026-09-18T23:59:59.000Z");
    expect(remainingTime(deadline, justOver24hBefore).status).toBe("remaining");
  });

  it("마감 뒤에는 D-day도 임박도 나오지 않는다 — 상태는 항상 closed", () => {
    const deadline = "2026-09-17T00:00:00.000Z";
    // 마감 뒤 몇 초, 몇 시간, 하루 넘게 지나도 모두 closed다(옛 버그: 올림 때문에
    // 마감 뒤 24시간 동안 D-day·임박이 켜진 채였다).
    for (const laterIso of [
      "2026-09-17T00:00:01.000Z",
      "2026-09-17T12:00:00.000Z",
      "2026-09-18T23:59:59.000Z",
      "2026-09-20T00:00:00.000Z",
    ]) {
      const result = remainingTime(deadline, new Date(laterIso));
      expect(result.status).toBe("closed");
      expect(remainingTimeLabel(deadline, new Date(laterIso))).toBe("마감");
      expect(remainingTimeIsImminent(deadline, new Date(laterIso))).toBe(false);
    }
  });

  it("임박은 마감 전 24시간 안쪽에서만 켜진다", () => {
    const deadline = "2026-09-20T00:00:00.000Z";
    const twoDaysBefore = new Date("2026-09-18T00:00:00.000Z");
    expect(remainingTimeIsImminent(deadline, twoDaysBefore)).toBe(false);

    const twelveHoursBefore = new Date("2026-09-19T12:00:00.000Z");
    expect(remainingTimeIsImminent(deadline, twelveHoursBefore)).toBe(true);
  });

  it("목록과 제출 화면의 D-N이 일치한다", () => {
    // 1.5일 남은 경우 — 옛 버그: 목록(올림)은 D-2, 제출 화면(내림)은 D-1로 갈렸다.
    const deadline = "2026-09-20T12:00:00.000Z";
    const now = new Date("2026-09-19T00:00:00.000Z");

    const listDDay = remainingTime(deadline, now).dDay;
    const submitLabel = formatSubmitCountdown(deadline, now);

    expect(submitLabel.startsWith(`D-${listDDay}`)).toBe(true);
    // 목록 쪽 라벨도 같은 D-N에서 파생된다.
    expect(remainingTimeLabel(deadline, now)).toBe(`D-${listDDay}`);
  });
});

describe("remainingTimeLabel", () => {
  it("24시간 밖은 D-N, 안쪽은 시간 단위 문구를 보인다", () => {
    const deadline = "2026-09-20T00:00:00.000Z";
    expect(remainingTimeLabel(deadline, new Date("2026-09-17T00:00:00.000Z"))).toBe("D-3");
    expect(remainingTimeLabel(deadline, new Date("2026-09-19T12:00:00.000Z"))).toBe("12시간 남음");
  });

  it("마감일 당일이면 D-day", () => {
    // 마감: 2026-09-19 23:00 KST = 2026-09-19 14:00 UTC. 지금: 같은 서울 달력
    // 날짜(9/19) 안이지만 24시간보다는 가까워 실제로는 hoursLabel이 뜬다 —
    // "오늘이 마감이면 D-day가 남은 시간 단위 문구보다 먼저 뜨는 일은 없다"는
    // 것을 이 케이스가 함께 고정한다(하루는 24시간을 넘지 않으므로 D-day는
    // 언제나 임박 판정과 같이 온다).
    const deadline = "2026-09-19T14:00:00.000Z";
    const now = new Date("2026-09-19T13:00:00.000Z");
    const result = remainingTime(deadline, now);
    expect(result.dDay).toBe(0);
    expect(remainingTimeLabel(deadline, now)).toBe("1시간 남음");
  });
});

describe("formatSubmitCountdown", () => {
  it("초 단위로 줄어드는 카운트다운을 D-N과 함께 보인다", () => {
    const deadline = "2026-09-20T00:00:00.000Z";
    const now = new Date("2026-09-17T23:59:58.000Z");
    expect(formatSubmitCountdown(deadline, now)).toBe("D-2 (48:00:02 남음)");

    const oneSecondLater = new Date("2026-09-17T23:59:59.000Z");
    expect(formatSubmitCountdown(deadline, oneSecondLater)).toBe("D-2 (48:00:01 남음)");
  });

  it("마감 뒤에는 마감을 보인다", () => {
    const deadline = "2026-09-17T00:00:00.000Z";
    expect(formatSubmitCountdown(deadline, new Date("2026-09-17T00:00:01.000Z"))).toBe("마감");
  });
});

describe("formatDeadlineSeoul", () => {
  it("서버 시간대와 무관하게 항상 서울 시간으로 적는다", () => {
    // UTC 자정은 서울로 오전 9시다 — 서버가 UTC로 떠 있어도(배포 컨테이너 기본)
    // 이 함수가 표시하는 값은 항상 서울 기준이어야 한다.
    const formatted = formatDeadlineSeoul("2026-09-17T00:00:00.000Z");
    expect(formatted).toContain("9:00");
    expect(formatted).not.toContain("12:00");
  });
});
