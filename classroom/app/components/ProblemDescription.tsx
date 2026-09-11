"use client";

// 문제 설명을 화면에 앉힌다(#313). 안전 판단은 전부
// lib/rendering/problem-description.ts 의 순수 함수가 이미 끝냈다 — 여기는 그
// 결과 트리를 그리기만 한다. dangerouslySetInnerHTML 을 쓰지 않는다: 이 모듈이
// 아는 노드 타입만 JSX 로 옮기므로, 트리에 없는 것은 애초에 그릴 수가 없다.
import { createElement } from "react";
import type { ReactNode } from "react";

import {
  parseProblemDescription,
  type DescriptionBlock,
  type DescriptionInline,
} from "@/lib/rendering/problem-description";

function renderInline(nodes: DescriptionInline[]): ReactNode {
  return nodes.map((node, index) => {
    switch (node.type) {
      case "text":
        return node.value;
      case "break":
        return <br key={index} />;
      case "strong":
        return <strong key={index}>{renderInline(node.children)}</strong>;
      case "em":
        return <em key={index}>{renderInline(node.children)}</em>;
      case "code":
        return (
          <code key={index} className="border border-rule bg-paper px-1 py-0.5 font-mono text-[0.9em]">
            {node.value}
          </code>
        );
      case "link":
        return (
          <a
            key={index}
            href={node.href}
            target="_blank"
            rel="noreferrer"
            className="text-attention underline underline-offset-2"
          >
            {renderInline(node.children)}
          </a>
        );
      case "image":
        return (
          // referrerPolicy="no-referrer" — 이 이미지를 불러올 때 어느 페이지에서 왔는지를
          // 이미지가 사는 서버에 붙이지 않는다. 접속한 인터넷 주소까지 숨기지는 못한다.
          <img
            key={index}
            src={node.src}
            alt={node.alt}
            referrerPolicy="no-referrer"
            className="my-1 max-w-full border border-rule"
            onError={(event) => {
              // 주소가 죽어도 설명의 나머지는 읽힌다 — 깨진 아이콘 대신 그 자리만 비운다.
              event.currentTarget.style.display = "none";
            }}
          />
        );
      default:
        return null;
    }
  });
}

function renderListItem(item: DescriptionBlock[], key: string): ReactNode {
  if (item.length === 1 && item[0].type === "paragraph") {
    return <li key={key}>{renderInline(item[0].children)}</li>;
  }
  // <li> 자체의 display를 바꾸면 불릿/번호 마커가 사라진다 — 안쪽에 한 겹 더 둔다.
  return (
    <li key={key}>
      <div className="flex flex-col gap-1">
        {item.map((block, index) => renderBlock(block, `${key}-${index}`))}
      </div>
    </li>
  );
}

function renderBlock(block: DescriptionBlock, key: string): ReactNode {
  switch (block.type) {
    case "heading": {
      // 화면의 h1 은 문제 제목 하나뿐이어야 한다(app/components/ui.tsx) — 설명의 헤딩은 h2부터 시작한다.
      const tag = `h${Math.min(block.depth + 1, 6)}`;
      return createElement(
        tag,
        { key, className: "mt-4 mb-1.5 font-semibold tracking-[-0.005em] first:mt-0" },
        renderInline(block.children),
      );
    }
    case "paragraph":
      return (
        <p key={key} className="leading-relaxed">
          {renderInline(block.children)}
        </p>
      );
    case "code_block":
      return (
        <pre
          key={key}
          className="overflow-x-auto border border-rule bg-paper p-3 font-mono text-[12.5px] leading-relaxed"
        >
          <code>{block.code}</code>
        </pre>
      );
    case "blockquote":
      return (
        <blockquote key={key} className="flex flex-col gap-1 border-l-2 border-rule pl-3 text-ink/75">
          {block.children.map((child, index) => renderBlock(child, `${key}-${index}`))}
        </blockquote>
      );
    case "list": {
      const tag = block.ordered ? "ol" : "ul";
      return createElement(
        tag,
        { key, className: block.ordered ? "list-decimal space-y-0.5 pl-5" : "list-disc space-y-0.5 pl-5" },
        block.items.map((item, index) => renderListItem(item, `${key}-${index}`)),
      );
    }
    case "hr":
      return <hr key={key} className="border-rule" />;
    default:
      return null;
  }
}

/** 문제 설명 마크다운을 그린다. 빈 설명이면 아무것도 그리지 않는다. */
export function ProblemDescription({ markdown }: { markdown: string }) {
  const blocks = parseProblemDescription(markdown ?? "");
  if (blocks.length === 0) return null;
  return (
    <div className="flex flex-col gap-1 text-[13.5px] text-ink">
      {blocks.map((block, index) => renderBlock(block, `b-${index}`))}
    </div>
  );
}
