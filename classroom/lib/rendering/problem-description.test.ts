// 문제 설명 렌더러의 순수 함수 시임(#313) — 공격 문자열은 e2e 로 여러 개 돌릴
// 수 없으니 여기서 돈다(부모 스펙 #312 「Testing Decisions」).
import { describe, expect, it } from "vitest";

import { parseProblemDescription } from "./problem-description";
import type { DescriptionBlock, DescriptionInline } from "./problem-description";

/** 트리 전체에서 text/code 노드의 값을 모아 이어 붙인다 — "어딘가에 남아
 *  있는가"를 문자열 하나로 확인할 때 쓴다. */
function collectText(nodes: (DescriptionBlock | DescriptionInline)[]): string {
  return nodes
    .map((node) => {
      switch (node.type) {
        case "text":
          return node.value;
        case "code":
          return node.value;
        case "code_block":
          return node.code;
        case "strong":
        case "em":
        case "link":
        case "blockquote":
          return collectText(node.children as (DescriptionBlock | DescriptionInline)[]);
        case "heading":
        case "paragraph":
          return collectText(node.children);
        case "list":
          return node.items.map((item) => collectText(item)).join("");
        case "image":
          return node.alt;
        default:
          return "";
      }
    })
    .join("");
}

describe("허용 목록을 통과하는 서식", () => {
  it("제목·굵기·기울임·인라인 코드를 그린다", () => {
    const tree = parseProblemDescription("# 제목\n\n**굵게** 그리고 *기울여* 그리고 `코드`");
    expect(tree[0]).toEqual({ type: "heading", depth: 1, children: [{ type: "text", value: "제목" }] });
    const paragraph = tree[1] as Extract<DescriptionBlock, { type: "paragraph" }>;
    expect(paragraph.children).toEqual([
      { type: "strong", children: [{ type: "text", value: "굵게" }] },
      { type: "text", value: " 그리고 " },
      { type: "em", children: [{ type: "text", value: "기울여" }] },
      { type: "text", value: " 그리고 " },
      { type: "code", value: "코드" },
    ]);
  });

  it("순서 없는 목록과 순서 있는 목록을 그린다", () => {
    const tree = parseProblemDescription("- 하나\n- 둘\n\n1. 첫째\n2. 둘째");
    expect(tree[0]).toMatchObject({ type: "list", ordered: false });
    expect(tree[1]).toMatchObject({ type: "list", ordered: true });
    const unordered = tree[0] as Extract<DescriptionBlock, { type: "list" }>;
    expect(collectText(unordered.items[0])).toBe("하나");
  });

  it("중첩된 목록도 그린다", () => {
    const tree = parseProblemDescription("- 항목\n  - 중첩1\n  - 중첩2");
    const list = tree[0] as Extract<DescriptionBlock, { type: "list" }>;
    const nested = list.items[0].find((b) => b.type === "list") as Extract<DescriptionBlock, { type: "list" }>;
    expect(nested).toBeDefined();
    expect(nested.items.map((item) => collectText(item))).toEqual(["중첩1", "중첩2"]);
  });

  it("코드블록이 언어와 원문 그대로의 코드를 보존한다", () => {
    const tree = parseProblemDescription("```js\nconsole.log('<b>안 굵음</b>')\n```");
    expect(tree[0]).toEqual({
      type: "code_block",
      language: "js",
      code: "console.log('<b>안 굵음</b>')",
    });
  });

  it("인용과 수평선을 그린다", () => {
    const tree = parseProblemDescription("> 인용문\n\n---");
    expect(tree[0]).toMatchObject({ type: "blockquote" });
    expect(tree[1]).toEqual({ type: "hr" });
  });

  it("http/https 링크와 이미지를 통과시킨다", () => {
    const tree = parseProblemDescription("[문서](https://codemit.example/doc) 그리고 ![그림](http://codemit.example/a.png)");
    const paragraph = tree[0] as Extract<DescriptionBlock, { type: "paragraph" }>;
    expect(paragraph.children[0]).toEqual({
      type: "link",
      href: "https://codemit.example/doc",
      children: [{ type: "text", value: "문서" }],
    });
    expect(paragraph.children[2]).toEqual({ type: "image", src: "http://codemit.example/a.png", alt: "그림" });
  });

  it("표는 그려지지 않는다 — 깨지지 않고 그 자리만 빈다", () => {
    const tree = parseProblemDescription("| a | b |\n|---|---|\n| 1 | 2 |\n\n뒤 문단은 그대로");
    expect(tree.some((b) => (b as { type: string }).type === "table")).toBe(false);
    expect(collectText(tree)).toContain("뒤 문단은 그대로");
  });

  it("기존 순수 텍스트 설명이 줄바꿈을 유지한 채 그대로 읽힌다", () => {
    const tree = parseProblemDescription("첫 줄\n둘째 줄\n\n다음 문단");
    const first = tree[0] as Extract<DescriptionBlock, { type: "paragraph" }>;
    expect(first.children).toEqual([
      { type: "text", value: "첫 줄" },
      { type: "break" },
      { type: "text", value: "둘째 줄" },
    ]);
    expect(collectText(tree)).toContain("다음 문단");
  });

  it("빈 설명은 빈 트리를 낸다", () => {
    expect(parseProblemDescription("")).toEqual([]);
  });
});

describe("공격 문자열이 어느 것도 통과하지 않는다", () => {
  it("script 태그가 트리 어디에도 남지 않는다", () => {
    const tree = parseProblemDescription("설명 앞\n\n<script>alert(document.cookie)</script>\n\n설명 뒤");
    const json = JSON.stringify(tree);
    expect(json).not.toContain("script");
    expect(json).not.toContain("alert");
    expect(collectText(tree)).toContain("설명 앞");
    expect(collectText(tree)).toContain("설명 뒤");
  });

  it("인라인 이벤트 핸들러 속성이 있는 raw 태그가 통과하지 않는다", () => {
    const tree = parseProblemDescription('본문 중간에 <img src=x onerror="alert(1)"> 섞여 있다');
    const json = JSON.stringify(tree);
    expect(json).not.toContain("onerror");
    expect(json).not.toContain("<img");
  });

  it("javascript: 링크는 링크가 아니라 평문으로 낮아진다", () => {
    const tree = parseProblemDescription("[누르지마](javascript:alert(document.cookie))");
    const paragraph = tree[0] as Extract<DescriptionBlock, { type: "paragraph" }>;
    expect(paragraph.children.some((n) => n.type === "link")).toBe(false);
    expect(collectText(tree)).toContain("누르지마");
    expect(JSON.stringify(tree)).not.toContain("javascript:");
  });

  it("data: 이미지는 어느 노드로도 나타나지 않는다", () => {
    const tree = parseProblemDescription("![덫](data:image/png;base64,AAAA)");
    expect(JSON.stringify(tree)).not.toContain("data:");
    expect(tree.some((b) => JSON.stringify(b).includes("\"image\""))).toBe(false);
  });

  it("javascript: 스킴을 대문자·공백으로 우회해도 막힌다", () => {
    const tree = parseProblemDescription("[클릭](  JaVaScRiPt:alert(1))");
    const json = JSON.stringify(tree);
    // http(s) 로 시작하지 않는 스킴은 모두 막는다 — 대소문자 우회를 따로 나열하지 않는다.
    expect(json).not.toMatch(/"type":"link"/);
  });

  it("중첩되고 깨진 마크업을 넣어도 트리가 만들어지고 실행 가능한 조각이 남지 않는다", () => {
    const tree = parseProblemDescription(
      "<div><script>alert(1)</script><img src=x onerror=alert(2)>\n\n**안 닫힌 굵기\n\n<svg onload=alert(3)>",
    );
    const json = JSON.stringify(tree);
    expect(json).not.toContain("script");
    expect(json).not.toContain("onerror");
    expect(json).not.toContain("onload");
    expect(() => parseProblemDescription("<div><script>alert(1)</script>")).not.toThrow();
  });

  it("스타일 태그로 실려 오는 서식도 통과하지 않는다 — 뒤따르는 문단은 그대로 읽힌다", () => {
    const tree = parseProblemDescription("<style>body{display:none}</style>\n\n일반 텍스트");
    expect(JSON.stringify(tree)).not.toContain("style");
    expect(collectText(tree)).toContain("일반 텍스트");
  });
});
