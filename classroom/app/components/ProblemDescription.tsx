"use client";

// 문제 설명을 화면에 앉힌다(#313, ADR-0047). 안전 판단은 전부
// lib/rendering/problem-description.ts 의 순수 함수가 이미 끝냈다 — 여기는 그
// 걸러진 트리를 React 요소로 옮기며 모양만 입힌다. dangerouslySetInnerHTML 을 쓰지
// 않는다: 트리에 없는 태그는 애초에 그릴 수가 없다.
//
// Tailwind 의 기본 초기화가 제목·목록의 브라우저 기본 모양을 지우므로 태그마다 크기와
// 간격을 여기서 다시 준다 — 예전에는 제목에 굵기만 줘서 모든 제목이 본문과 같은
// 크기였다(2026-09-15).
import type { Element } from "hast";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ComponentPropsWithoutRef, type KeyboardEvent } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { toJsxRuntime, type Components } from "hast-util-to-jsx-runtime";

import { codeTextOf, copyToClipboard } from "@/lib/rendering/code-copy";
import { downloadNameFor } from "@/lib/rendering/code-files";
import { parseProblemDescription } from "@/lib/rendering/problem-description";

// 문제 제목 — 파일로 받을 때 이름의 몸통이 된다(`lib/rendering/code-files.ts`).
const FileBaseName = createContext("");
//: 코드블록의 순번(1부터) — 같은 설명에 블록이 여럿일 때 파일 이름이 겹치지 않게
//: 한다. 트리를 미리 한 번 훑어 `pre` 노드마다 번호를 매겨 둔다(렌더 순서에
//: 기대지 않는다 — React 가 언제 무엇을 그리든 같은 번호가 나와야 한다).
const CodeBlockNumbers = createContext<Map<Element, number>>(new Map());

// 코드블록(`pre > code`) 안의 code 는 pre 가 복사 버튼을 맡는다 — 언어 표시가 없는
// 코드블록은 className 으로 인라인 코드와 가를 수 없어 이 문맥으로 가른다.
const InsideCodeBlock = createContext(false);

type CopyState = "idle" | "copied" | "failed";

/** 누르면 복사하고 2초 동안 결과를 보인 뒤 원래대로 돌아간다. */
function useCopy(text: string) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  async function copy() {
    const ok = await copyToClipboard(text);
    setState(ok ? "copied" : "failed");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  }
  return { state, copy };
}

type WithNode<T extends "pre" | "code"> = ComponentPropsWithoutRef<T> & { node?: Element };

/** 이 코드블록의 언어(`language-…` 클래스)와 강사가 적은 파일 이름. */
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

function CodeBlock({ node, ...props }: WithNode<"pre">) {
  const text = node ? codeTextOf(node) : "";
  const { state, copy } = useCopy(text);
  const title = useContext(FileBaseName);
  const numbers = useContext(CodeBlockNumbers);
  const index = (node && numbers.get(node)) ?? 1;
  const { language, meta } = codeInfoOf(node);
  const fileName = downloadNameFor({ language, meta, title, index });

  // 파일로 받기 — 블록 글자를 그대로 파일 하나로 내린다. 서버를 거치지 않는다.
  function download() {
    if (!fileName) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // 다음 순간에 거둔다 — 브라우저가 내려받기를 시작할 틈을 준다.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="relative my-2">
      <div className="absolute top-1.5 right-1.5 flex gap-1">
        {fileName && (
          <button
            type="button"
            onClick={download}
            data-testid="code-block-download"
            title={`${fileName} 으로 저장`}
            className="border border-rule bg-surface px-2 py-0.5 text-[11.5px] text-ink/70 hover:text-ink"
          >
            파일로 저장
          </button>
        )}
        <button
          type="button"
          onClick={() => void copy()}
          data-testid="code-block-copy"
          className="border border-rule bg-surface px-2 py-0.5 text-[11.5px] text-ink/70 hover:text-ink"
        >
          {state === "copied" ? "복사됨" : state === "failed" ? "복사 실패" : "복사"}
        </button>
      </div>
      <InsideCodeBlock.Provider value={true}>
        <pre
          {...props}
          className="overflow-x-auto border border-rule bg-paper px-3 pt-9 pb-3 font-mono text-[12.5px] leading-relaxed [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0"
        />
      </InsideCodeBlock.Provider>
    </div>
  );
}

function Code({ node, className, ...props }: WithNode<"code">) {
  const insideBlock = useContext(InsideCodeBlock);
  const text = node ? codeTextOf(node) : "";
  const { state, copy } = useCopy(text);
  if (insideBlock) return <code {...props} className={className} />;
  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      void copy();
    }
  }
  return (
    <span className="relative inline-block">
      <code
        {...props}
        role="button"
        tabIndex={0}
        title="눌러서 복사"
        aria-label={`${text} 복사`}
        onClick={() => void copy()}
        onKeyDown={onKeyDown}
        data-testid="inline-code-copy"
        className="cursor-pointer border border-rule bg-paper px-1 py-0.5 font-mono text-[0.9em] hover:border-ink/40"
      />
      {state !== "idle" && (
        <span
          role="status"
          className="pointer-events-none absolute bottom-full left-0 mb-1 whitespace-nowrap border border-rule bg-surface px-1.5 py-0.5 text-[11px] text-ink/70"
        >
          {state === "copied" ? "복사됨" : "복사 실패"}
        </span>
      )}
    </span>
  );
}

const COMPONENTS: Partial<Components> = {
  h2: (props: ComponentPropsWithoutRef<"h2">) => (
    <h2 {...props} className="mt-5 mb-2 text-[20px] font-semibold leading-snug tracking-[-0.01em] first:mt-0" />
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
  p: (props: ComponentPropsWithoutRef<"p">) => <p {...props} className="my-1.5 leading-relaxed first:mt-0" />,
  strong: (props: ComponentPropsWithoutRef<"strong">) => <strong {...props} className="font-semibold" />,
  del: (props: ComponentPropsWithoutRef<"del">) => <del {...props} className="text-ink/55" />,
  // 코드블록은 오른쪽 위 「복사」 버튼, 인라인 코드는 눌러서 복사한다(2026-09-15).
  code: Code,
  pre: CodeBlock,
  blockquote: (props: ComponentPropsWithoutRef<"blockquote">) => (
    <blockquote {...props} className="my-2 border-l-2 border-rule pl-3 text-ink/75" />
  ),
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  ul: ({ className, ...props }: ComponentPropsWithoutRef<"ul">) => (
    <ul
      {...props}
      // 체크박스 항목과 일반 항목이 섞일 수 있다 — 목록은 글머리 점을 유지하고 체크박스
      // 항목만 점을 지워 체크박스를 그 자리에 앉힌다(아래 li).
      className="my-1.5 list-disc space-y-0.5 pl-5"
    />
  ),
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  ol: ({ className, ...props }: ComponentPropsWithoutRef<"ol">) => (
    <ol
      {...props}
      className="my-1.5 list-decimal space-y-0.5 pl-5"
    />
  ),
  li: ({ className, ...props }: ComponentPropsWithoutRef<"li">) => (
    <li {...props} className={className === "task-list-item" ? "-ml-5 flex list-none items-baseline gap-2" : "leading-relaxed"} />
  ),
  input: (props: ComponentPropsWithoutRef<"input">) => (
    <input {...props} disabled readOnly className="translate-y-[1px] accent-ink" />
  ),
  hr: (props: ComponentPropsWithoutRef<"hr">) => <hr {...props} className="my-3 border-rule" />,
  a: (props: ComponentPropsWithoutRef<"a">) => (
    <a {...props} target="_blank" rel="noreferrer" className="text-attention underline underline-offset-2" />
  ),
  img: (props: ComponentPropsWithoutRef<"img">) => (
    // referrerPolicy="no-referrer" — 이 이미지를 불러올 때 어느 페이지에서 왔는지를
    // 이미지가 사는 서버에 붙이지 않는다. 접속한 인터넷 주소까지 숨기지는 못한다.
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    <img
      {...props}
      referrerPolicy="no-referrer"
      className="my-1 max-w-full border border-rule"
      onError={(event) => {
        // 주소가 죽어도 설명의 나머지는 읽힌다 — 깨진 아이콘 대신 그 자리만 비운다.
        event.currentTarget.style.display = "none";
      }}
    />
  ),
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

/**
 * 문제 설명 마크다운을 그린다. 빈 설명이면 아무것도 그리지 않는다.
 *
 * `title` 은 코드블록을 **파일로 받을 때** 이름의 몸통이 된다(강사가 정보 줄에 이름을
 * 적었으면 그것이 이긴다). 넘기지 않으면 `code-1.py` 처럼 떨어진다.
 */
export function ProblemDescription({ markdown, title = "" }: { markdown: string; title?: string }) {
  const tree = useMemo(() => parseProblemDescription(markdown ?? ""), [markdown]);
  const numbers = useMemo(() => {
    const map = new Map<Element, number>();
    let next = 1;
    const walk = (node: { type: string; tagName?: string; children?: unknown[] }) => {
      if (node.type === "element" && node.tagName === "pre") map.set(node as Element, next++);
      for (const child of (node.children ?? []) as (typeof node)[]) walk(child);
    };
    walk(tree);
    return map;
  }, [tree]);
  if (tree.children.length === 0) return null;
  return (
    <FileBaseName.Provider value={title}>
      <CodeBlockNumbers.Provider value={numbers}>
        <div className="text-[13.5px] text-ink">
          {toJsxRuntime(tree, { Fragment, jsx, jsxs, components: COMPONENTS, passNode: true })}
        </div>
      </CodeBlockNumbers.Provider>
    </FileBaseName.Provider>
  );
}
