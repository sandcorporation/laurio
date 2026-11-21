import { describe, expect, it } from "vitest";

import { describeVerification, formatKoreanDate, type CertificateVerification } from "./verify";

const base: CertificateVerification = {
  state: "valid",
  number: "2026-0002-001",
  contest_title: "실시간 동영상 스트리밍 플랫폼 만들기",
  award_name: "최우수상",
  recipient_name: "홍길동",
  giver_name: "김예시",
  giver_title: "예시스튜디오 대표",
  issued_on: "2026-12-01",
  cancelled_on: null,
  reissued: false,
};

describe("describeVerification", () => {
  it("유효한 상장은 여섯 줄을 순서대로", () => {
    const view = describeVerification(base);
    expect(view.stateLabel).toBe("✓ 유효한 상장");
    expect(view.tone).toBe("valid");
    expect(view.rows.map((r) => [r.label, r.value])).toEqual([
      ["상장 번호", "2026-0002-001"],
      ["공모전", "실시간 동영상 스트리밍 플랫폼 만들기"],
      ["상", "최우수상"],
      ["받는 사람", "홍길동"],
      ["수여자", "김예시 · 예시스튜디오 대표"],
      ["발급일", "2026년 12월 1일"],
    ]);
  });

  it("직함이 없으면 수여자 이름만", () => {
    const view = describeVerification({ ...base, giver_title: "" });
    expect(view.rows.find((r) => r.label === "수여자")?.value).toBe("김예시");
  });

  it("취소됨은 번호·공모전·취소일만, 다시 발급됐으면 이름표가 다르다", () => {
    const cancelled: CertificateVerification = {
      state: "cancelled",
      number: "2026-0002-001",
      contest_title: "실시간 동영상 스트리밍 플랫폼 만들기",
      cancelled_on: "2026-12-03",
      reissued: false,
    };
    expect(describeVerification(cancelled).stateLabel).toBe("취소됨");
    const view = describeVerification({ ...cancelled, reissued: true });
    expect(view.stateLabel).toBe("취소됨 — 다시 발급됨");
    expect(view.tone).toBe("void");
    expect(view.rows.map((r) => r.label)).toEqual(["상장 번호", "공모전", "취소일"]);
    expect(view.rows[2].value).toBe("2026년 12월 3일");
  });

  it("받는 사람이 닫은 상장은 번호만", () => {
    const view = describeVerification({ state: "hidden", number: "2026-0002-001", reissued: false });
    expect(view.stateLabel).toBe("확인할 수 없는 상장");
    expect(view.rows).toEqual([{ label: "상장 번호", value: "2026-0002-001", mono: true }]);
  });
});

describe("formatKoreanDate", () => {
  it("앞자리 0 을 떼고 쓴다", () => {
    expect(formatKoreanDate("2027-01-09")).toBe("2027년 1월 9일");
  });
});
