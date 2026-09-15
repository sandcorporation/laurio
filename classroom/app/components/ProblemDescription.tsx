"use client";

// 문제 설명을 화면에 앉힌다(#313, ADR-0047). 안전 판단은 전부
// lib/rendering/problem-description.ts 의 순수 함수가 이미 끝냈다 — 여기는 그
// 걸러진 트리를 React 요소로 옮기며 모양만 입힌다. dangerouslySetInnerHTML 을 쓰지
// 않는다: 트리에 없는 태그는 애초에 그릴 수가 없다.
//
// Tailwind 의 기본 초기화가 제목·목록의 브라우저 기본 모양을 지우므로 태그마다 크기와
// 간격을 여기서 다시 준다 — 예전에는 제목에 굵기만 줘서 모든 제목이 본문과 같은
// 크기였다(2026-09-15).
import type { ComponentPropsWithoutRef } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { toJsxRuntime, type Components } from "hast-util-to-jsx-runtime";

import { parseProblemDescription } from "@/lib/rendering/problem-description";

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
  code: ({ className, ...props }: ComponentPropsWithoutRef<"code">) =>
    // 코드블록 안(`pre > code`)은 pre 가 모양을 맡는다 — 인라인 코드만 테두리를 준다.
    className?.startsWith("language-") ? (
      <code {...props} className={className} />
    ) : (
      <code {...props} className="border border-rule bg-paper px-1 py-0.5 font-mono text-[0.9em]" />
    ),
  pre: (props: ComponentPropsWithoutRef<"pre">) => (
    <pre
      {...props}
      className="my-2 overflow-x-auto border border-rule bg-paper p-3 font-mono text-[12.5px] leading-relaxed [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0"
    />
  ),
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

/** 문제 설명 마크다운을 그린다. 빈 설명이면 아무것도 그리지 않는다. */
export function ProblemDescription({ markdown }: { markdown: string }) {
  const tree = parseProblemDescription(markdown ?? "");
  if (tree.children.length === 0) return null;
  return (
    <div className="text-[13.5px] text-ink">
      {toJsxRuntime(tree, { Fragment, jsx, jsxs, components: COMPONENTS })}
    </div>
  );
}
