import { describe, expect, it } from "vitest";

import {
  dueDraftFromIso,
  dueDraftToIso,
  dueOrderViolated,
  describeDue,
  formatDueDateTime,
  formatDueDay,
  pickDueDate,
  withLate,
  lateLabel,
} from "./due-dates";

// 브라우저 로컬 시각 기준이라 시험도 로컬 생성자로 만든다 — 호스트 시간대가 달라도 같은 결과다.
const local = (y: number, m: number, d: number, h = 23, mi = 59) => new Date(y, m - 1, d, h, mi);
const NOW = local(2026, 10, 21, 12, 0).getTime();
const iso = (y: number, m: number, d: number) => local(y, m, d).toISOString();

describe("formatDueDay / formatDueDateTime", () => {
  it("표·격자·목록은 「M/D」, 제출 카드는 요일과 시각까지", () => {
    expect(formatDueDay(iso(2026, 10, 27))).toBe("10/27");
    expect(formatDueDateTime(iso(2026, 10, 27))).toBe("10/27 (화) 23:59");
    expect(formatDueDateTime(local(2026, 10, 24, 9, 5).toISOString())).toBe("10/24 (토) 09:05");
  });
});

describe("describeDue", () => {
  it("둘 다 없으면 둘 다 null", () => {
    expect(describeDue({ recommended_due_at: null, due_at: null }, { passed: false, now: NOW })).toEqual({
      recommended: null,
      due: null,
    });
  });

  it("권장은 흐리고(dim), 지났거나 통과했으면 더 흐리다(faint)", () => {
    const ahead = describeDue({ recommended_due_at: iso(2026, 10, 24), due_at: null }, { passed: false, now: NOW });
    expect(ahead.recommended).toEqual({ label: "권장", text: "10/24", tone: "dim", passed: false });
    const behind = describeDue({ recommended_due_at: iso(2026, 10, 17), due_at: null }, { passed: false, now: NOW });
    expect(behind.recommended?.tone).toBe("faint");
    expect(behind.recommended?.passed).toBe(true);
    const done = describeDue({ recommended_due_at: iso(2026, 10, 24), due_at: null }, { passed: true, now: NOW });
    expect(done.recommended?.tone).toBe("faint");
  });

  it("마감은 보통 글자, 지난 마감은 참여자가 아직 통과하지 못했을 때만 붉다", () => {
    const ahead = describeDue({ recommended_due_at: null, due_at: iso(2026, 10, 27) }, { passed: false, now: NOW });
    expect(ahead.due).toEqual({ label: "마감", text: "10/27", tone: "normal", passed: false });
    const behindNotPassed = describeDue({ recommended_due_at: null, due_at: iso(2026, 10, 20) }, { passed: false, now: NOW });
    expect(behindNotPassed.due).toEqual({ label: "마감 지남", text: "10/20", tone: "attention", passed: true });
    const behindPassed = describeDue({ recommended_due_at: null, due_at: iso(2026, 10, 20) }, { passed: true, now: NOW });
    expect(behindPassed.due?.tone).toBe("faint");
    expect(behindPassed.due?.label).toBe("마감");
  });

  it("강사 화면(참여자가 없다, passed: null)의 지난 마감은 붉지 않고 흐리다", () => {
    const behind = describeDue({ recommended_due_at: null, due_at: iso(2026, 10, 20) }, { passed: null, now: NOW });
    expect(behind.due).toEqual({ label: "마감", text: "10/20", tone: "faint", passed: true });
    const ahead = describeDue({ recommended_due_at: null, due_at: iso(2026, 10, 27) }, { passed: null, now: NOW });
    expect(ahead.due?.tone).toBe("normal");
  });
});

describe("withLate", () => {
  it("늦음 두 단계를 배지 글자로 나눈다", () => {
    expect(withLate("통과", "recommended")).toBe("통과 · 권장 기한 뒤");
    expect(withLate("미통과", "deadline")).toBe("미통과 · 마감 기한 뒤");
    expect(withLate("미통과", null)).toBe("미통과");
  });
});

describe("격자 늦음 설명", () => {
  it("셀과 범례에 쓸 두 단계 이름을 구분한다", () => {
    expect(lateLabel("recommended")).toBe("권장 기한 뒤 제출");
    expect(lateLabel("deadline")).toBe("마감 기한 뒤 제출");
    expect(lateLabel(null)).toBeNull();
  });
});

describe("due draft", () => {
  it("ISO ↔ 날짜·시각 칸(로컬)", () => {
    expect(dueDraftFromIso(null)).toEqual({ date: "", time: "" });
    expect(dueDraftFromIso(local(2026, 10, 27, 23, 59).toISOString())).toEqual({ date: "2026-10-27", time: "23:59" });
    expect(dueDraftFromIso(local(2026, 3, 5, 9, 5).toISOString())).toEqual({ date: "2026-03-05", time: "09:05" });
  });

  it("보낼 때는 로컬 → 오프셋이 붙은 ISO, 비어 있으면 null", () => {
    expect(dueDraftToIso({ date: "", time: "" })).toBeNull();
    const out = dueDraftToIso({ date: "2026-10-27", time: "23:59" });
    expect(out).toMatch(/[+-]\d{2}:\d{2}$|Z$/);
    expect(Date.parse(out ?? "")).toBe(local(2026, 10, 27, 23, 59).getTime());
    // 시각이 비어 있으면 23:59 로 친다.
    expect(Date.parse(dueDraftToIso({ date: "2026-10-27", time: "" }) ?? "")).toBe(local(2026, 10, 27, 23, 59).getTime());
  });

  it("날짜를 고르면 시각은 23:59 로 채워지고, 날짜를 비우면 시각도 비운다", () => {
    expect(pickDueDate({ date: "", time: "" }, "2026-10-27")).toEqual({ date: "2026-10-27", time: "23:59" });
    expect(pickDueDate({ date: "2026-10-20", time: "09:00" }, "2026-10-27")).toEqual({ date: "2026-10-27", time: "09:00" });
    expect(pickDueDate({ date: "2026-10-20", time: "09:00" }, "")).toEqual({ date: "", time: "" });
  });

  it("권장이 마감보다 늦으면 순서 위반이다 — 같은 시각은 허용, 한쪽이 비면 위반이 아니다", () => {
    const rec = { date: "2026-10-28", time: "00:00" };
    const due = { date: "2026-10-27", time: "23:59" };
    expect(dueOrderViolated(rec, due)).toBe(true);
    expect(dueOrderViolated(due, due)).toBe(false);
    expect(dueOrderViolated({ date: "2026-10-24", time: "23:59" }, due)).toBe(false);
    expect(dueOrderViolated(rec, { date: "", time: "" })).toBe(false);
  });
});
