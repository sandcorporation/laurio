// 코드블록·인라인 코드의 복사 버튼이 클립보드에 넣을 글자(2026-09-15). 렌더된 트리에서
// 뽑으므로 화면에 보이는 코드와 복사되는 코드가 갈리지 않는다.
import type { Element } from "hast";
import { describe, expect, it } from "vitest";

import { codeTextOf } from "./code-copy";
import { parseDescription } from "./parse";

function firstElement(markdown: string, tagName: string): Element {
  const found: Element[] = [];
  const walk = (node: { type: string; tagName?: string; children?: unknown[] }) => {
    if (node.type === "element" && node.tagName === tagName) found.push(node as Element);
    for (const child of (node.children ?? []) as (typeof node)[]) walk(child);
  };
  walk(parseDescription(markdown));
  if (!found[0]) throw new Error(`${tagName} 없음`);
  return found[0];
}

describe("복사할 글자", () => {
  it("코드블록은 원문 그대로, 끝의 줄바꿈 하나만 뺀다", () => {
    const pre = firstElement("```\n####\n#S.G#\n\n####\n```", "pre");
    expect(codeTextOf(pre)).toBe("####\n#S.G#\n\n####");
  });

  it("언어가 붙은 코드블록도 같은 글자를 낸다 — 안의 HTML 은 글자로 남는다", () => {
    const pre = firstElement("```csv\nid,title\n1,<b>별빛</b>\n```", "pre");
    expect(codeTextOf(pre)).toBe("id,title\n1,<b>별빛</b>");
  });

  it("인라인 코드는 그 글자만 낸다", () => {
    const code = firstElement("실행은 `java -jar app.jar map3.txt` 로 한다", "code");
    expect(codeTextOf(code)).toBe("java -jar app.jar map3.txt");
  });
});
