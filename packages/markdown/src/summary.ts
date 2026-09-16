// 마크다운 설명을 **글자만 남은 한 줄**로 줄인다(2026-09-16).
//
// 왜 필요한가: 공모전 상세의 `<meta name="description">` 과 OG 설명이 설명 원문을
// 그대로 실었다. 설명이 순수 텍스트였을 때는 맞는 값이었지만 마크다운이 된 뒤로는
// 검색 결과와 링크 미리보기에 `## 제목`·`| 표 |`·백틱이 그대로 나온다 —
// CI 가 그것을 잡았다(`## 알림 앱 리디자인` 이 head 에 남아 있었다).
//
// **허용 목록을 통과한 트리에서 글자를 모은다.** 정규식으로 기호를 지우는 쪽이 짧지만
// 그러면 원문의 raw HTML 이 메타 태그로 새는 길이 남는다 — 그릴 때와 같은 문(`parse.ts`)
// 을 지나게 해서 그 길 자체를 없앤다.
import type { Nodes } from "hast";

import { parseDescription } from "./parse";

/** 문단·제목처럼 줄이 갈리는 태그 — 글자를 이어 붙일 때 사이에 공백을 넣는다. */
const BLOCK_TAGS = new Set([
  "h1", "h2", "h3", "h4", "h5", "h6",
  "p", "li", "blockquote", "pre", "hr", "br",
  "tr", "th", "td", "table", "thead", "tbody",
]);

function collect(node: Nodes, out: string[]): void {
  if (node.type === "text") {
    out.push(node.value);
    return;
  }
  const isBlock = node.type === "element" && BLOCK_TAGS.has(node.tagName);
  if (isBlock) out.push(" ");
  for (const child of ("children" in node ? node.children : []) as Nodes[]) collect(child, out);
  if (isBlock) out.push(" ");
}

/**
 * 설명 마크다운에서 글자만 뽑아 한 줄로 만든다. `maxLength` 를 넘으면 낱말 경계에서
 * 자르고 `…` 를 붙인다(0 이나 음수를 주면 자르지 않는다).
 *
 * 빈 설명이면 빈 문자열이다 — 호출부가 다른 문장으로 갈아 끼울 수 있게.
 */
export function plainTextSummary(markdown: string, maxLength = 0): string {
  const out: string[] = [];
  collect(parseDescription(markdown ?? "") as Nodes, out);
  const text = out.join("").replace(/\s+/g, " ").trim();
  if (maxLength <= 0 || text.length <= maxLength) return text;
  const cut = text.slice(0, maxLength);
  const lastSpace = cut.lastIndexOf(" ");
  // 공백이 없는 긴 낱말(한 문장이 통째로 붙은 한국어 등)은 글자 수로 자른다.
  return `${(lastSpace > maxLength * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
