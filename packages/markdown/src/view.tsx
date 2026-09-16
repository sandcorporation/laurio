// 걸러진 트리를 화면에 앉힌다(#313, ADR-0047). 안전 판단은 전부 `parse.ts` 의 순수
// 함수가 이미 끝냈다 — 여기는 모양만 입힌다. dangerouslySetInnerHTML 을 쓰지 않는다:
// 트리에 없는 태그는 애초에 그릴 수가 없다.
//
// **이 파일에는 `"use client"` 가 없다.** 공개 앱의 공모전 상세는 색인 대상이라 본문이
// 서버 HTML 에 있어야 한다(ADR-0015·0017) — 그래서 제목·문단·표·코드는 서버가 그리고,
// 손이 필요한 조각(복사·파일로 저장·눌러서 복사되는 인라인 코드)만 `./client` 의 작은
// 클라이언트 섬으로 내려간다. 강의실처럼 클라이언트 컴포넌트 안에서 써도 그대로 돈다.
//
// Tailwind 의 기본 초기화가 제목·목록의 브라우저 기본 모양을 지우므로 태그마다 크기와
// 간격을 여기서 다시 준다 — 예전에는 제목에 굵기만 줘서 모든 제목이 본문과 같은
// 크기였다(2026-09-15).
import type { Element, ElementContent, Root } from "hast";
import { toJsxRuntime, type Components } from "hast-util-to-jsx-runtime";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";

import { CodeBlockActions, InlineCode, RemoteImage } from "./client";
import { codeTextOf } from "./code-copy";
import { downloadNameFor } from "./code-files";
import { parseDescription } from "./parse";

type WithNode<T extends "pre" | "code"> = ComponentPropsWithoutRef<T> & { node?: Element };

/** 이 코드블록의 언어(`language-…` 클래스)와 정보 줄에 적힌 파일 이름. */
function codeInfoOf(node: Element | undefined): { language: string; meta: string } {
  const code = node?.children.find(
    (child): child is Element => child.type === "element" && child.tagName === "code",
  );
  const classNames = code?.properties?.className;
  const list = Array.isArray(classNames) ? classNames.map(String) : [];
  const language = list.find((name) => name.startsWith("language-"))?.slice("language-".length) ?? "";
  const meta = typeof code?.properties?.dataFilename === "string" ? code.properties.dataFilename : "";
  return { language, meta };
}

/**
 * 트리를 한 번 훑어 두 가지를 미리 정한다 — 렌더 순서에 기대지 않는다.
 *
 * - **코드블록의 순번**(1부터): 같은 설명에 블록이 여럿일 때 파일 이름이 겹치지 않게.
 * - **`pre` 안의 `code`**: 그 code 는 버튼을 달지 않는다(pre 가 맡는다). 클래스로는
 *   가를 수 없다 — 언어를 안 적은 코드블록은 `language-…` 클래스가 없어서 인라인
 *   코드와 구별되지 않는다. 강의실은 이 판정을 React 문맥으로 했지만(#313), 서버
 *   컴포넌트에는 문맥이 없어 트리를 훑는 쪽으로 옮겼다.
 */
function scanTree(tree: Root): { numbers: Map<Element, number>; blockCodes: Set<Element> } {
  const numbers = new Map<Element, number>();
  const blockCodes = new Set<Element>();
  let next = 1;
  const walk = (node: Root | ElementContent, insidePre: boolean) => {
    const isPre = node.type === "element" && node.tagName === "pre";
    if (isPre) numbers.set(node as Element, next++);
    if (insidePre && node.type === "element" && node.tagName === "code") blockCodes.add(node);
    for (const child of ("children" in node ? node.children : []) as ElementContent[]) {
      walk(child, insidePre || isPre);
    }
  };
  walk(tree, false);
  return { numbers, blockCodes };
}

function buildComponents(options: {
  numbers: Map<Element, number>;
  blockCodes: Set<Element>;
  fileBaseName: string;
}): Partial<Components> {
  const { numbers, blockCodes, fileBaseName } = options;

  const CodeBlock = ({ node, ...props }: WithNode<"pre">) => {
    const text = node ? codeTextOf(node) : "";
    const { language, meta } = codeInfoOf(node);
    const fileName = downloadNameFor({
      language,
      meta,
      title: fileBaseName,
      index: (node && numbers.get(node)) ?? 1,
    });
    return (
      <div className="relative my-2">
        <CodeBlockActions text={text} fileName={fileName} />
        <pre
          {...props}
          className="overflow-x-auto border border-rule bg-paper px-3 pt-9 pb-3 font-mono text-[12.5px] leading-relaxed [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0"
        />
      </div>
    );
  };

  const Code = ({ node, children, ...props }: WithNode<"code">) => {
    if (!node || blockCodes.has(node)) return <code {...props}>{children}</code>;
    return <InlineCode text={codeTextOf(node)}>{children as ReactNode}</InlineCode>;
  };

  return {
    h2: (props: ComponentPropsWithoutRef<"h2">) => (
      <h2
        {...props}
        className="mt-5 mb-2 text-[20px] font-semibold leading-snug tracking-[-0.01em] first:mt-0"
      />
    ),
    h3: (props: ComponentPropsWithoutRef<"h3">) => (
      <h3 {...props} className="mt-4 mb-1.5 text-[17px] font-semibold leading-snug first:mt-0" />
    ),
    h4: (props: ComponentPropsWithoutRef<"h4">) => (
      <h4 {...props} className="mt-3.5 mb-1 text-[15px] font-semibold first:mt-0" />
    ),
    h5: (props: ComponentPropsWithoutRef<"h5">) => (
      <h5 {...props} className="mt-3 mb-1 text-[14px] font-semibold first:mt-0" />
    ),
    h6: (props: ComponentPropsWithoutRef<"h6">) => (
      <h6 {...props} className="mt-3 mb-1 text-[13.5px] font-semibold text-ink/70 first:mt-0" />
    ),
    p: (props: ComponentPropsWithoutRef<"p">) => (
      <p {...props} className="my-1.5 leading-relaxed first:mt-0" />
    ),
    strong: (props: ComponentPropsWithoutRef<"strong">) => (
      <strong {...props} className="font-semibold" />
    ),
    del: (props: ComponentPropsWithoutRef<"del">) => <del {...props} className="text-ink/55" />,
    // 코드블록은 오른쪽 위 버튼, 인라인 코드는 눌러서 복사한다(2026-09-15/16).
    code: Code,
    pre: CodeBlock,
    blockquote: (props: ComponentPropsWithoutRef<"blockquote">) => (
      <blockquote {...props} className="my-2 border-l-2 border-rule pl-3 text-ink/75" />
    ),
    // 체크박스 항목과 일반 항목이 섞일 수 있다 — 목록은 글머리 점을 유지하고 체크박스
    // 항목만 점을 지워 체크박스를 그 자리에 앉힌다(아래 li).
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ul: ({ className, ...props }: ComponentPropsWithoutRef<"ul">) => (
      <ul {...props} className="my-1.5 list-disc space-y-0.5 pl-5" />
    ),
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ol: ({ className, ...props }: ComponentPropsWithoutRef<"ol">) => (
      <ol {...props} className="my-1.5 list-decimal space-y-0.5 pl-5" />
    ),
    li: ({ className, ...props }: ComponentPropsWithoutRef<"li">) => (
      <li
        {...props}
        className={
          className === "task-list-item"
            ? "-ml-5 flex list-none items-baseline gap-2"
            : "leading-relaxed"
        }
      />
    ),
    input: (props: ComponentPropsWithoutRef<"input">) => (
      <input {...props} disabled readOnly className="translate-y-[1px] accent-ink" />
    ),
    hr: (props: ComponentPropsWithoutRef<"hr">) => <hr {...props} className="my-3 border-rule" />,
    a: (props: ComponentPropsWithoutRef<"a">) => (
      <a
        {...props}
        target="_blank"
        rel="noreferrer"
        className="text-attention underline underline-offset-2"
      />
    ),
    // 주소가 죽은 이미지는 그 자리만 비운다 — 설명의 나머지는 읽힌다.
    img: RemoteImage,
    table: (props: ComponentPropsWithoutRef<"table">) => (
      <div className="my-2 overflow-x-auto">
        <table {...props} className="w-full border-collapse text-[13px]" />
      </div>
    ),
    // 표 칸 정렬(`:---`·`---:`)은 변환기가 이미 `style` 의 text-align 으로 넣어 준다 —
    // 그 style 을 덮어쓰지 않도록 props 를 그대로 넘긴다.
    th: (props: ComponentPropsWithoutRef<"th">) => (
      <th {...props} className="border border-rule bg-paper px-2.5 py-1.5 text-left font-semibold" />
    ),
    td: (props: ComponentPropsWithoutRef<"td">) => (
      <td {...props} className="border border-rule px-2.5 py-1.5 align-top" />
    ),
  };
}

/**
 * 설명 마크다운을 그린다. 빈 설명이면 아무것도 그리지 않는다.
 *
 * `fileBaseName` 은 코드블록을 **파일로 받을 때** 이름의 몸통이 된다(정보 줄에 이름이
 * 적혀 있으면 그것이 이긴다). 넘기지 않으면 `code-1.py` 처럼 떨어진다 — 강의실은 문제
 * 제목을, 공개 앱은 공모전 제목을 넘긴다.
 */
export function MarkdownView({
  markdown,
  fileBaseName = "",
}: {
  markdown: string;
  fileBaseName?: string;
}) {
  const tree = parseDescription(markdown ?? "");
  if (tree.children.length === 0) return null;
  const { numbers, blockCodes } = scanTree(tree);
  const components = buildComponents({ numbers, blockCodes, fileBaseName });
  return (
    <div className="text-[13.5px] text-ink">
      {toJsxRuntime(tree, { Fragment, jsx, jsxs, components, passNode: true })}
    </div>
  );
}
