// 문제 설명 마크다운을 안전하게 그릴 수 있는 트리로 바꾸는 순수 함수다(#313,
// ADR-0012 개정).
//
// **저장되는 값은 언제나 마크다운 원문이다** — 백엔드는 그 값을 sanitize 하지
// 않는다(태그를 걷어내면 코드블록 안의 예시 HTML 이 함께 사라진다). 안전은
// 저장이 아니라 이 함수가 그릴 때 보장한다.
//
// **허용 목록 방식이다** — 무엇을 막을지가 아니라 무엇을 통과시킬지를 이
// 모듈이 아는 타입(`DescriptionBlock`/`DescriptionInline`)으로 정한다.
// `<script>`나 `onerror=` 같은 원문 속 HTML 은 `marked` 의 렉서가 "html"
// 토큰으로 넘기는데, 이 모듈에는 그 타입을 다루는 자리가 없어 트리에 아예
// 나타나지 않는다 — dangerouslySetInnerHTML 을 쓰지 않으므로 걸러내야 할
// 문자열을 나열할 필요도 없다. 링크·이미지 주소는 `http`/`https` 만
// 통과한다(`javascript:`·`data:` 는 여기서 막힌다). 표는 허용 목록에 없어
// 그려지지 않는다 — 깨진 화면 대신 빈 자리다.
import { marked } from "marked";

export type DescriptionInline =
  | { type: "text"; value: string }
  | { type: "strong"; children: DescriptionInline[] }
  | { type: "em"; children: DescriptionInline[] }
  | { type: "code"; value: string }
  | { type: "link"; href: string; children: DescriptionInline[] }
  | { type: "image"; src: string; alt: string }
  | { type: "break" };

export type DescriptionBlock =
  | { type: "heading"; depth: 1 | 2 | 3 | 4 | 5 | 6; children: DescriptionInline[] }
  | { type: "paragraph"; children: DescriptionInline[] }
  | { type: "code_block"; language: string | null; code: string }
  | { type: "blockquote"; children: DescriptionBlock[] }
  | { type: "list"; ordered: boolean; items: DescriptionBlock[][] }
  | { type: "hr" };

// `marked` 의 렉서 토큰은 공개 타입이 우리가 다루는 필드만 좁혀 쓰기엔
// 번거로워 여기서만 느슨하게 받는다 — 바깥으로는 위 두 타입만 나간다.
type RawToken = { type: string; [key: string]: unknown };

const SAFE_URL = /^https?:\/\//i;

function isSafeUrl(href: unknown): href is string {
  return typeof href === "string" && SAFE_URL.test(href.trim());
}

function tokenChildren(token: RawToken): RawToken[] {
  const tokens = token.tokens;
  return Array.isArray(tokens) ? (tokens as RawToken[]) : [];
}

function convertInlineChildren(token: RawToken, fallbackToOwnText = false): DescriptionInline[] {
  const nested = tokenChildren(token);
  if (nested.length > 0) return nested.flatMap(convertInline);
  if (fallbackToOwnText && typeof token.text === "string" && token.text) {
    return [{ type: "text", value: token.text }];
  }
  return [];
}

function convertInline(token: RawToken): DescriptionInline[] {
  switch (token.type) {
    case "text":
    case "escape": {
      const nested = tokenChildren(token);
      if (nested.length > 0) return nested.flatMap(convertInline);
      return typeof token.text === "string" && token.text ? [{ type: "text", value: token.text }] : [];
    }
    case "strong":
      return [{ type: "strong", children: convertInlineChildren(token) }];
    case "em":
      return [{ type: "em", children: convertInlineChildren(token) }];
    case "codespan":
      return typeof token.text === "string" && token.text ? [{ type: "code", value: token.text }] : [];
    case "br":
      return [{ type: "break" }];
    case "link": {
      const children = convertInlineChildren(token);
      return isSafeUrl(token.href) ? [{ type: "link", href: token.href, children }] : children;
    }
    case "image":
      return isSafeUrl(token.href)
        ? [{ type: "image", src: token.href, alt: typeof token.text === "string" ? token.text : "" }]
        : [];
    case "html":
      // 원문에 있던 태그 그대로는 어디에도 나가지 않는다 — <script>도 onerror= 도 여기서 끝난다.
      return [];
    default:
      // 모르는 인라인 서식(취소선 등)은 평문으로 낮춘다 — 화면을 깨뜨리지 않는다.
      return convertInlineChildren(token, true);
  }
}

function convertListItem(item: RawToken): DescriptionBlock[] {
  const blocks: DescriptionBlock[] = [];
  for (const child of tokenChildren(item)) {
    if (child.type === "text") {
      const children = convertInline(child);
      if (children.length > 0) blocks.push({ type: "paragraph", children });
      continue;
    }
    const block = convertBlock(child);
    if (block) blocks.push(block);
  }
  return blocks;
}

function convertBlock(token: RawToken): DescriptionBlock | null {
  switch (token.type) {
    case "heading": {
      const depth = Math.min(6, Math.max(1, Number(token.depth) || 1)) as 1 | 2 | 3 | 4 | 5 | 6;
      return { type: "heading", depth, children: convertInlineChildren(token) };
    }
    case "paragraph":
      return { type: "paragraph", children: convertInlineChildren(token) };
    case "text":
      return { type: "paragraph", children: convertInline(token) };
    case "code":
      return {
        type: "code_block",
        language:
          typeof token.lang === "string" && token.lang.trim() ? token.lang.trim().split(/\s+/)[0] : null,
        code: typeof token.text === "string" ? token.text : "",
      };
    case "blockquote":
      return {
        type: "blockquote",
        children: tokenChildren(token)
          .map(convertBlock)
          .filter((b): b is DescriptionBlock => b !== null),
      };
    case "hr":
      return { type: "hr" };
    case "list": {
      const items = token.items;
      return {
        type: "list",
        ordered: Boolean(token.ordered),
        items: (Array.isArray(items) ? (items as RawToken[]) : []).map(convertListItem),
      };
    }
    default:
      // 표·원문 그대로의 HTML 블록·정의 등은 허용 목록에 없다 — 그리지 않되 나머지는 그대로 읽힌다.
      return null;
  }
}

/** 문제 설명 마크다운 원문을 안전한 블록 트리로 바꾼다. 저장은 여전히 원문이다. */
export function parseProblemDescription(markdown: string): DescriptionBlock[] {
  const tokens = marked.lexer(markdown ?? "", { gfm: true, breaks: true }) as unknown as RawToken[];
  return tokens.map(convertBlock).filter((b): b is DescriptionBlock => b !== null);
}
