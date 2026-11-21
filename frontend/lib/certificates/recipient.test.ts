import { describe, expect, it } from "vitest";

import { certificatesBySubmission, describeCertificateLine, type MyCertificate } from "./recipient";

const base: MyCertificate = {
  id: 1,
  submission_id: 10,
  contest_id: 5,
  contest_title: "첫 공모전",
  number: "2026-0005-001",
  award_name: "최우수상",
  state: "valid",
  hidden: false,
  verify_url: "https://example.test/c/abc",
};

describe("받는 사람 상장 줄(#1130)", () => {
  it("유효하고 열린 상장은 받기와 「확인 페이지 닫기」", () => {
    expect(describeCertificateLine(base)).toEqual({
      stateLabel: "유효",
      tone: "verified",
      canDownload: true,
      visibilityAction: { label: "확인 페이지 닫기", hidden: true },
    });
  });

  it("닫은 상장은 「확인 페이지 열기」", () => {
    const line = describeCertificateLine({ ...base, hidden: true });
    expect(line.stateLabel).toBe("유효 · 확인 페이지 닫힘");
    expect(line.visibilityAction).toEqual({ label: "확인 페이지 열기", hidden: false });
  });

  it("취소된 상장은 받기도 닫기도 없다", () => {
    expect(describeCertificateLine({ ...base, state: "cancelled" })).toEqual({
      stateLabel: "취소됨",
      tone: "neutral",
      canDownload: false,
      visibilityAction: null,
    });
  });

  it("제출마다 묶는다", () => {
    const grouped = certificatesBySubmission([base, { ...base, id: 2, state: "cancelled" }, { ...base, id: 3, submission_id: 11 }]);
    expect(grouped.get(10)?.map((c) => c.id)).toEqual([1, 2]);
    expect(grouped.get(11)?.map((c) => c.id)).toEqual([3]);
  });
});
