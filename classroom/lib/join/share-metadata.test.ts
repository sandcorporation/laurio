import { describe, expect, it } from "vitest";

import { LANDING_DESCRIPTION } from "../landing-copy";

import {
  GENERIC_JOIN_TITLE,
  MAX_CLASS_NAME_LENGTH,
  joinShareMetadata,
} from "./share-metadata";

const base = { class_name: "알고리즘 스터디", open_problem_count: 3, archived: false };

describe("joinShareMetadata", () => {
  it("열린 문제가 있으면 이름과 문제 수·AI 채점을 한 줄로 싣는다", () => {
    const m = joinShareMetadata(base);
    expect(m.title).toBe("알고리즘 스터디 — Codemit 클래스");
    expect(m.description).toBe(
      "열린 문제 3개 · 제출할 때마다 AI가 체크리스트 항목별로 채점합니다",
    );
    expect(m.openGraph?.title).toBe(m.title);
    expect(m.openGraph?.description).toBe(m.description);
    expect(m.twitter?.title).toBe(m.title);
    expect(m.twitter?.description).toBe(m.description);
    expect((m.openGraph as { type?: string }).type).toBe("website");
    expect((m.twitter as { card?: string }).card).toBe("summary_large_image");
  });

  it("열린 문제가 0개면 문제 수 조각을 뺀다", () => {
    const m = joinShareMetadata({ ...base, open_problem_count: 0 });
    expect(m.description).toBe("제출할 때마다 AI가 체크리스트 항목별로 채점합니다");
  });

  it("긴 이름은 상한에서 줄임표로 자르고 접미사는 남긴다", () => {
    const long = "가".repeat(MAX_CLASS_NAME_LENGTH + 30);
    const title = joinShareMetadata({ ...base, class_name: long }).title as string;
    expect(title).toBe(`${"가".repeat(MAX_CLASS_NAME_LENGTH)}… — Codemit 클래스`);
    const exact = "나".repeat(MAX_CLASS_NAME_LENGTH);
    expect(joinShareMetadata({ ...base, class_name: exact }).title).toBe(
      `${exact} — Codemit 클래스`,
    );
  });

  it("미리보기가 없거나 보관된 클래스면 일반 카드다", () => {
    for (const m of [joinShareMetadata(null), joinShareMetadata({ ...base, archived: true })]) {
      expect(m.title).toBe(GENERIC_JOIN_TITLE);
      expect(m.description).toBe(LANDING_DESCRIPTION);
      expect(m.openGraph?.title).toBe(GENERIC_JOIN_TITLE);
      expect(m.twitter?.description).toBe(LANDING_DESCRIPTION);
    }
  });

  it("참여자 수와 강사 이름은 어느 문자열에도 없다", () => {
    const full = {
      ...base,
      class_id: 1,
      member_count: 4242,
      instructor_display_name: "김비밀강사",
      instructor_display_names: ["김비밀강사", "이공동"],
      already_joined: true,
    };
    const text = JSON.stringify(joinShareMetadata(full));
    expect(text).not.toContain("4242");
    expect(text).not.toContain("김비밀강사");
    expect(text).not.toContain("이공동");
    expect(text).not.toContain("already_joined");
  });
});
