// 메타 설명·링크 미리보기에 들어가는 요약(2026-09-16). CI 가 잡은 실패가 계기다 —
// 공모전 상세의 `<meta name="description">` 이 마크다운 원문을 그대로 실었다.
import { describe, expect, it } from "vitest";

import { plainTextSummary } from "./summary";

describe("plainTextSummary", () => {
  it("제목 기호를 지우고 글자만 남긴다", () => {
    expect(plainTextSummary("## 알림 앱 리디자인\n\n본문입니다.")).toBe(
      "알림 앱 리디자인 본문입니다.",
    );
  });

  it("목록·인용·강조 기호도 남지 않는다", () => {
    const text = plainTextSummary("- 첫째\n- **둘째**\n\n> 인용\n");
    expect(text).toBe("첫째 둘째 인용");
  });

  it("표는 칸의 글자만 이어 붙인다 — 막대가 남지 않는다", () => {
    const text = plainTextSummary("| 항목 | 필수 |\n| --- | --- |\n| 게시글 | 예 |\n");
    expect(text).not.toContain("|");
    expect(text).toContain("항목");
    expect(text).toContain("게시글");
  });

  it("코드블록은 백틱 없이 코드 글자만 남는다", () => {
    const text = plainTextSummary('설명\n\n```ts\nconst a = 1;\n```\n');
    expect(text).not.toContain("```");
    expect(text).toContain("const a = 1;");
  });

  it("인라인 코드의 백틱도 사라진다", () => {
    expect(plainTextSummary("실행은 `pnpm dev` 한 줄입니다.")).toBe(
      "실행은 pnpm dev 한 줄입니다.",
    );
  });

  it("원문의 HTML 은 애초에 트리에 없다 — 태그가 요약에 새지 않는다", () => {
    // 같은 줄에 이어 쓴 글자는 그 HTML 덩이의 일부로 함께 사라진다(remark 의
    // HTML 블록 규칙) — 그래서 남는 글자는 다음 문단에 둔다.
    const text = plainTextSummary("<script>alert(1)</script>\n\n남은 글자");
    expect(text).not.toContain("<script>");
    expect(text).not.toContain("alert");
    expect(text).toBe("남은 글자");
  });

  it("빈 설명은 빈 문자열이다 — 호출부가 다른 문장으로 갈아 끼울 수 있다", () => {
    expect(plainTextSummary("")).toBe("");
    expect(plainTextSummary("   \n\n  ")).toBe("");
  });

  it("maxLength 를 넘으면 낱말 경계에서 자르고 … 을 붙인다", () => {
    const text = plainTextSummary("하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열", 12);
    expect(text.endsWith("…")).toBe(true);
    expect(text.length).toBeLessThanOrEqual(13);
    // 낱말이 반 토막 나지 않는다 — 남은 글자가 전부 원문의 온전한 낱말이다.
    const words = text.slice(0, -1).trim().split(" ");
    const original = "하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열".split(" ");
    expect(words.every((word) => original.includes(word))).toBe(true);
  });

  it("공백 없는 긴 낱말은 글자 수로 자른다 — 통째로 버리지 않는다", () => {
    const text = plainTextSummary("가".repeat(40), 10);
    expect(text).toBe(`${"가".repeat(10)}…`);
  });

  it("maxLength 이하면 그대로 둔다 — … 을 붙이지 않는다", () => {
    expect(plainTextSummary("짧은 설명", 160)).toBe("짧은 설명");
  });
});
