"use client";

// 문제 설명을 쓰는 툴바 에디터(#317). 툴바는 **마크다운을 써 넣을 뿐**이다 —
// HTML을 만들었다가 다시 마크다운으로 되돌리는 왕복이 없다. 저장되는 값은
// 여전히 사람이 읽을 수 있는 원문이고, 마크다운을 직접 칠 수도 있다 — 이
// textarea가 유일한 입력 자리이고 툴바는 그 자리에 문자열을 밀어 넣을 뿐이다.
//
// 미리보기는 #313의 그 렌더러(ProblemDescription)를 그대로 쓴다 — 쓰면서 본
// 것과 참여자가 보는 것이 갈리면 미리보기의 뜻이 없다.
import { useRef } from "react";
import type { ChangeEvent, ReactNode } from "react";

import { ProblemDescription } from "@/app/components/ProblemDescription";
import { EmptyState, INPUT_CLASS } from "@/app/components/ui";

interface Selection {
  start: number;
  end: number;
  selected: string;
}

function readSelection(el: HTMLTextAreaElement, value: string): Selection {
  const start = el.selectionStart ?? value.length;
  const end = el.selectionEnd ?? value.length;
  return { start, end, selected: value.slice(start, end) };
}

const TOOLBAR_BUTTON_CLASS =
  "border border-rule bg-surface px-2.5 py-1 text-[12.5px] text-ink hover:bg-paper " +
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ink";

function ToolbarButton({
  label,
  testId,
  onClick,
}: {
  label: string;
  testId: string;
  onClick: () => void;
}) {
  return (
    <button type="button" data-testid={testId} className={TOOLBAR_BUTTON_CLASS} onClick={onClick}>
      {label}
    </button>
  );
}

export function MarkdownEditor({
  id,
  value,
  onChange,
  rows = 8,
  placeholder,
  testId,
  hint,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
  testId: string;
  hint?: ReactNode;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  /** 커서(또는 선택 범위) 뒤에 텍스트를 밀어 넣고, 그 텍스트만큼 선택해 되돌려 준다. */
  function replaceSelection(next: string, selectFrom: number, selectTo: number) {
    onChange(next);
    const el = textareaRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(selectFrom, selectTo);
    });
  }

  /** 굵게·기울임·인라인 코드 — 선택한 글자를 앞뒤 기호로 감싼다. 선택이 없으면 자리표시 글자를 넣고 그것을 선택해 둔다. */
  function wrapSelection(before: string, after: string, placeholderText: string) {
    const el = textareaRef.current;
    if (!el) return;
    const { start, end, selected } = readSelection(el, value);
    const body = selected || placeholderText;
    const next = value.slice(0, start) + before + body + after + value.slice(end);
    replaceSelection(next, start + before.length, start + before.length + body.length);
  }

  /** 제목·목록·인용 — 선택한 줄마다 앞에 기호를 붙인다. 선택이 없으면 그 줄에 자리표시 글자를 넣는다. */
  function prefixLines(prefix: string, placeholderText: string) {
    const el = textareaRef.current;
    if (!el) return;
    const { start, end, selected } = readSelection(el, value);
    const body = selected || placeholderText;
    const prefixed = body
      .split("\n")
      .map((line) => `${prefix}${line}`)
      .join("\n");
    const next = value.slice(0, start) + prefixed + value.slice(end);
    replaceSelection(next, start, start + prefixed.length);
  }

  /** 코드블록 — 선택한 내용을 독립된 문단으로 세 개의 백틱 사이에 둔다. */
  function insertCodeBlock() {
    const el = textareaRef.current;
    if (!el) return;
    const { start, end, selected } = readSelection(el, value);
    const body = selected || "코드";
    const needsLeadingBreak = start > 0 && value[start - 1] !== "\n";
    const needsTrailingBreak = end < value.length && value[end] !== "\n";
    const block = `${needsLeadingBreak ? "\n" : ""}\`\`\`\n${body}\n\`\`\`${needsTrailingBreak ? "\n" : ""}`;
    const next = value.slice(0, start) + block + value.slice(end);
    const selectFrom = start + (needsLeadingBreak ? 1 : 0) + 4;
    replaceSelection(next, selectFrom, selectFrom + body.length);
  }

  function insertLink() {
    const el = textareaRef.current;
    if (!el) return;
    const { start, end, selected } = readSelection(el, value);
    const url = window.prompt("연결할 주소를 입력하세요 (http 또는 https로 시작해야 합니다)");
    if (url === null || url.trim() === "") return;
    const label = selected || "링크";
    const markdown = `[${label}](${url.trim()})`;
    const next = value.slice(0, start) + markdown + value.slice(end);
    replaceSelection(next, start + markdown.length, start + markdown.length);
  }

  function insertImage() {
    const el = textareaRef.current;
    if (!el) return;
    const { start, end } = readSelection(el, value);
    const url = window.prompt(
      "이미지의 바깥 주소를 입력하세요 (http 또는 https로 시작해야 합니다). " +
        "이 주소가 사는 서버는 누군가 열어봤다는 사실을 알 수 있습니다 — 어느 문제에서 " +
        "봤는지는 알리지 않지만, 접속한 인터넷 주소까지 숨기지는 못합니다.",
    );
    if (url === null || url.trim() === "") return;
    const alt = window.prompt("대체 텍스트(무엇을 보여주는 이미지인지)를 입력하세요", "이미지") ?? "이미지";
    const markdown = `![${alt}](${url.trim()})`;
    const next = value.slice(0, start) + markdown + value.slice(end);
    replaceSelection(next, start + markdown.length, start + markdown.length);
  }

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>) {
    onChange(event.target.value);
  }

  return (
    <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div role="toolbar" aria-label="마크다운 서식" className="flex flex-wrap gap-1">
          <ToolbarButton label="굵게" testId={`${testId}-bold`} onClick={() => wrapSelection("**", "**", "굵은 텍스트")} />
          <ToolbarButton
            label="기울임"
            testId={`${testId}-italic`}
            onClick={() => wrapSelection("*", "*", "기울임 텍스트")}
          />
          <ToolbarButton label="제목" testId={`${testId}-heading`} onClick={() => prefixLines("# ", "제목")} />
          <ToolbarButton label="목록" testId={`${testId}-list`} onClick={() => prefixLines("- ", "목록 항목")} />
          <ToolbarButton label="코드블록" testId={`${testId}-code-block`} onClick={insertCodeBlock} />
          <ToolbarButton
            label="인라인 코드"
            testId={`${testId}-inline-code`}
            onClick={() => wrapSelection("`", "`", "코드")}
          />
          <ToolbarButton label="인용" testId={`${testId}-quote`} onClick={() => prefixLines("> ", "인용문")} />
          <ToolbarButton label="링크" testId={`${testId}-link`} onClick={insertLink} />
          <ToolbarButton label="이미지" testId={`${testId}-image`} onClick={insertImage} />
        </div>
        <textarea
          ref={textareaRef}
          id={id}
          data-testid={testId}
          value={value}
          onChange={handleChange}
          rows={rows}
          placeholder={placeholder}
          className={`${INPUT_CLASS} resize-y leading-relaxed`}
        />
        {hint}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="text-[12px] text-ink/60">미리보기 — 참여자가 보는 것과 같은 방식으로 그립니다</span>
        <div className="border border-rule bg-surface p-4" data-testid={`${testId}-preview`}>
          {value.trim() === "" ? (
            <EmptyState>
              <span data-testid={`${testId}-preview-empty`}>아직 설명이 없습니다.</span>
            </EmptyState>
          ) : (
            <ProblemDescription markdown={value} />
          )}
        </div>
      </div>
    </div>
  );
}
