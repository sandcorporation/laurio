import { describe, expect, it } from "vitest";

import { appealsDetail, payoutsDetail } from "./queue-row-detail";

describe("홈 큐 표의 설명 문구 (#427)", () => {
  it("밀린 이의가 없으면 설명이 없다", () => {
    expect(appealsDetail(0, null)).toBeNull();
  });

  it("건수가 있는데 오래된 날짜를 모르면(조회 실패 등) 설명을 비운다 — 틀린 숫자를 보이지 않는다", () => {
    expect(appealsDetail(4, null)).toBeNull();
  });

  it("건수와 날짜가 있으면 가장 오래 밀린 날짜 수를 말한다", () => {
    expect(appealsDetail(4, 3)).toBe("가장 오래 밀린 것 3일");
  });

  it("지급 대기는 신원·셀러·이체 셋을 가운뎃점으로 가른다", () => {
    expect(payoutsDetail(2, 3, 2)).toBe("신원 2 · 셀러 3 · 이체 2");
  });

  it("셋 다 0이어도 문구 자체는 그대로다 — 줄이 사라지지 않는다", () => {
    expect(payoutsDetail(0, 0, 0)).toBe("신원 0 · 셀러 0 · 이체 0");
  });
});
