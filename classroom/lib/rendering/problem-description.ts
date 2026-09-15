// 문제 설명 마크다운을 안전하게 그릴 수 있는 트리로 바꾸는 순수 함수다(#313,
// ADR-0012 개정 → ADR-0041, 렌더러 교체 ADR-0047).
//
// **저장되는 값은 언제나 마크다운 원문이다** — 백엔드는 그 값을 sanitize 하지
// 않는다(태그를 걷어내면 코드블록 안의 예시 HTML 이 함께 사라진다). 안전은
// 저장이 아니라 이 함수가 그릴 때 보장한다.
//
// **허용 목록 방식이다** — remark(+GFM)로 원문을 문법 트리로 만들고, 원문 속
// raw HTML 은 HTML 트리로 옮기지 않으며(`remark-rehype` 의 기본값), 마지막에
// `rehype-sanitize` 의 **허용 목록 스키마**가 태그·속성·주소 스킴을 한 번 더
// 거른다. 결과는 HTML 문자열이 아니라 트리이고, 화면(`ProblemDescription`)은
// 그 트리를 React 요소로 옮길 뿐 dangerouslySetInnerHTML 을 쓰지 않는다.
//
// 예전에는 `marked` 렉서 토큰을 손으로 허용 목록 타입으로 옮겼는데, 제목 크기·
// 표·취소선·체크박스 목록을 강사가 쓰는 에디터(Toast UI)와 맞추려면 그 목록을
// 계속 손으로 늘려야 했다(2026-09-15). 지금은 그 목록이 아래 스키마 한 곳에 있다.
import type { Element, Root } from "hast";
import rehypeSanitize, { defaultSchema, type Options as SanitizeSchema } from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";
import { visit } from "unist-util-visit";

//: 설명 안에서 그릴 수 있는 태그 전부. 여기에 없는 것은 트리에서 사라진다.
//: `h1` 이 없는 이유: 화면의 h1 은 문제 제목 하나뿐이어야 해서 설명의 제목은 한
//: 단계씩 내려 h2 부터 쓴다(아래 `shiftHeadings`).
const ALLOWED_TAGS = [
  "h2", "h3", "h4", "h5", "h6",
  "p", "br", "hr",
  "strong", "em", "del", "code", "pre",
  "blockquote",
  "ul", "ol", "li", "input",
  "a", "img",
  "table", "thead", "tbody", "tr", "th", "td",
];

const SCHEMA: SanitizeSchema = {
  ...defaultSchema,
  tagNames: ALLOWED_TAGS,
  attributes: {
    a: ["href"],
    img: ["src", "alt"],
    // 체크박스 목록(- [ ] / - [x])은 보여주기만 한다 — 누를 수 없다.
    input: [["type", "checkbox"], ["disabled", true], "checked"],
    li: [["className", "task-list-item"]],
    ul: [["className", "contains-task-list"]],
    ol: [["className", "contains-task-list"]],
    code: [["className", /^language-[\w-]+$/]],
    th: ["align"],
    td: ["align"],
  },
  // 링크·이미지 주소는 http/https 만 — `javascript:`·`data:` 는 여기서 떨어진다.
  protocols: { href: ["http", "https"], src: ["http", "https"] },
  // 스키마가 떨어뜨린 태그의 **내용**은 남기되(글자는 읽힌다), 아래 둘은 내용째 버린다.
  strip: ["script", "style"],
  clobberPrefix: "",
  required: { input: { type: "checkbox", disabled: true } },
};

/** `# 제목` 을 h2 로 — 설명의 제목 단계를 한 칸씩 내린다(h6 에서 멈춘다). */
function shiftHeadings() {
  return (tree: Root) => {
    visit(tree, "element", (node: Element) => {
      const match = /^h([1-6])$/.exec(node.tagName);
      if (match) node.tagName = `h${Math.min(Number(match[1]) + 1, 6)}`;
    });
  };
}

/** 링크 주소가 허용되지 않아 `href` 가 떨어진 `<a>` 는 링크가 아니라 글자로 낮춘다. */
function unwrapDeadLinks() {
  return (tree: Root) => {
    visit(tree, "element", (node: Element, index, parent) => {
      if (node.tagName !== "a" || node.properties?.href || !parent || index === undefined) return;
      parent.children.splice(index, 1, ...node.children);
      return index;
    });
  };
}

/** 주소가 떨어진 `<img>` 는 남길 것이 없다 — 통째로 뺀다. */
function dropDeadImages() {
  return (tree: Root) => {
    visit(tree, "element", (node: Element, index, parent) => {
      if (node.tagName !== "img" || node.properties?.src || !parent || index === undefined) return;
      parent.children.splice(index, 1);
      return index;
    });
  };
}

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  // 한 줄 바꿈도 줄바꿈으로 — 예전 순수 텍스트 설명이 줄 단위로 적혀 있다.
  .use(remarkBreaks)
  .use(remarkRehype)
  .use(shiftHeadings)
  .use(rehypeSanitize, SCHEMA)
  .use(unwrapDeadLinks)
  .use(dropDeadImages);

/** 마크다운 원문 → 걸러진 HTML 트리(hast). 빈 설명이면 자식이 없는 트리다. */
export function parseProblemDescription(markdown: string): Root {
  const source = markdown ?? "";
  if (source.trim() === "") return { type: "root", children: [] };
  return processor.runSync(processor.parse(source)) as Root;
}
