import { describe, expect, it } from "vitest";

import {
  categoryChangesToEntries,
  deliverableTypeChangesToEntries,
  hostingPermissionChangesToEntries,
  mergeRecentChanges,
  policyChangesToEntries,
} from "./recent-changes";

describe("홈의 최근 변경 이력 — 네 출처를 합친다 (#427)", () => {
  it("정책 변경은 필드 한글 라벨로 before → after를 말한다", () => {
    const [entry] = policyChangesToEntries([
      {
        id: 1,
        before: { platform_fee_bps: 300 },
        after: { platform_fee_bps: 280 },
        operator_username: "codemit-op",
        changed_at: "2026-09-16T04:12:00Z",
        reason: "수수료 인하",
      },
    ]);
    expect(entry.what).toBe("플랫폼 정책");
    expect(entry.summary).toContain("플랫폼 수수료율 300 → 280");
    expect(entry.operatorUsername).toBe("codemit-op");
  });

  it("카테고리·산출물 종류 변경은 대상 id와 동작을 말한다", () => {
    const [category] = categoryChangesToEntries([
      {
        id: 5,
        category_id: 12,
        action: "updated",
        before: { name: "웹" },
        after: { name: "웹서비스" },
        operator_username: "codemit-op",
        changed_at: "2026-09-15T21:40:00Z",
        reason: "이름 정리",
      },
    ]);
    expect(category.what).toBe("카테고리");
    expect(category.summary).toContain("수정 #12");

    const [deliverable] = deliverableTypeChangesToEntries([
      {
        id: 7,
        deliverable_type_id: 3,
        action: "created",
        before: {},
        after: { name: "관리자 페이지" },
        operator_username: "codemit-op",
        changed_at: "2026-09-15T20:00:00Z",
        reason: "신설",
      },
    ]);
    expect(deliverable.what).toBe("산출물 종류");
    expect(deliverable.summary).toContain("생성 #3");
  });

  it("개최 권한 변경은 대상 계정 이메일을 말한다", () => {
    const [entry] = hostingPermissionChangesToEntries([
      {
        id: 9,
        user_id: 12,
        user_email: "host@example.test",
        action: "granted",
        operator_username: "codemit-op",
        changed_at: "2026-09-15T18:03:00Z",
        reason: "사내 스터디 운영",
      },
    ]);
    expect(entry.summary).toBe("부여 — host@example.test");
  });

  it("네 출처를 최신순으로 합치고 한도로 자른다", () => {
    const older = { key: "a", what: "x", summary: "s", operatorUsername: "op", changedAt: "2026-09-01T00:00:00Z" };
    const newer = { key: "b", what: "x", summary: "s", operatorUsername: "op", changedAt: "2026-09-10T00:00:00Z" };
    const newest = { key: "c", what: "x", summary: "s", operatorUsername: "op", changedAt: "2026-09-16T00:00:00Z" };

    const merged = mergeRecentChanges([[older], [newer, newest]], 2);
    expect(merged.map((e) => e.key)).toEqual(["c", "b"]);
  });
});
