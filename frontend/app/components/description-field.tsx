"use client";

// 공모전 설명을 적는 칸(2026-09-16). 개최(유료·무료)와 초안 편집 셋이 이 한 벌을
// 쓴다 — 같은 값을 받아 같은 렌더러가 그리므로 칸도 하나여야 한다.
//
// **미리보기가 이 컴포넌트의 존재 이유다.** 설명은 이제 마크다운으로 그려지는데
// (`@codemit/markdown`, ADR-0047), 적는 자리가 맨 textarea 뿐이면 `##` 이나 표가
// 실제로 어떻게 보일지를 **개최한 뒤에야** 알게 된다. 강의실이 문제를 만들 때
// 「미리보기」 탭으로 같은 문제를 이미 풀어 뒀다(#325) — 여기서는 에디터를 들이지
// 않고 탭 둘만 둔다: 개최 폼은 한 화면에 열 칸이 넘게 있어, 칸 하나가 에디터
// 라이브러리를 들고 오면 화면의 무게가 통째로 달라진다.
//
// 미리보기는 **참여자가 실제로 볼 그 렌더러**로 그린다 — 다른 길로 그리면 미리보기가
// 미리보기가 아니다(#325 body 가 강의실에서 같은 말을 한다).
import { useState } from "react";

import { MarkdownView } from "@codemit/markdown";

import { INPUT_CLASS } from "@/app/components/ui";

type Tab = "write" | "preview";

function tabClass(active: boolean): string {
  return `border-b-2 px-2 pb-1 text-xs ${
    active ? "border-ink font-medium text-ink" : "border-transparent text-ink/55 hover:text-ink"
  }`;
}

export function DescriptionField({
  label,
  value,
  onChange,
  title = "",
  rows = 8,
  placeholder,
  testId,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  /** 코드블록을 파일로 받을 때 이름의 몸통 — 공모전 제목을 넘긴다. */
  title?: string;
  rows?: number;
  placeholder?: string;
  /** 쓰는 칸의 testid. 미리보기 쪽은 `${testId}-preview` 로 붙는다. */
  testId: string;
}) {
  const [tab, setTab] = useState<Tab>("write");

  return (
    <div className="flex flex-col gap-1 text-sm">
      <div className="flex items-end justify-between gap-3">
        <span>{label}</span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setTab("write")}
            aria-pressed={tab === "write"}
            data-testid={`${testId}-tab-write`}
            className={tabClass(tab === "write")}
          >
            쓰기
          </button>
          <button
            type="button"
            onClick={() => setTab("preview")}
            aria-pressed={tab === "preview"}
            data-testid={`${testId}-tab-preview`}
            className={tabClass(tab === "preview")}
          >
            미리보기
          </button>
        </div>
      </div>

      {/* 두 탭을 갈아 끼우는 대신 **감춘다** — textarea 를 지웠다 놓으면 커서 자리와
          되돌리기(undo) 이력이 사라진다. */}
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={rows}
        placeholder={placeholder}
        data-testid={testId}
        hidden={tab === "preview"}
        className={`${INPUT_CLASS} font-mono text-[12.5px] leading-relaxed`}
      />

      {tab === "preview" && (
        <div
          data-testid={`${testId}-preview`}
          className="min-h-[7rem] border border-rule bg-paper px-3 py-2"
        >
          {value.trim() === "" ? (
            <p className="text-xs text-ink/50">아직 적은 것이 없습니다.</p>
          ) : (
            <MarkdownView markdown={value} fileBaseName={title} />
          )}
        </div>
      )}

      <p className="text-xs text-ink/50">
        마크다운으로 적을 수 있습니다 — 제목(##), 목록, 표, 코드블록(```).
      </p>
    </div>
  );
}
