"use client";

// 클래스 상세의 가입 링크 띠(#633, 시안 v2) — 라벨·주소·복사·「다시 뽑기」 글자 링크가 한 줄이다.
// 보관된 클래스는 새 가입을 받지 않으므로(#351) 주소를 보이지 않고 배지만 둔다 — 되돌리기는 설정의 「보관과 삭제」(#636).
import { useState } from "react";

import { Badge, ErrorNote, buttonClass } from "@/app/components/ui";

function joinLinkUrl(joinCode: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/join/${joinCode}`;
}

const STRIP = "flex flex-wrap items-center gap-x-4 gap-y-2 border border-rule bg-surface px-4 py-2.5";
const LABEL = "whitespace-nowrap text-[11px] tracking-[0.06em] text-ink/45";

export function JoinLinkStrip({
  joinCode,
  archived,
  regenerateError,
  onRegenerate,
}: {
  joinCode: string;
  archived: boolean;
  regenerateError: boolean;
  onRegenerate: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const url = joinLinkUrl(joinCode);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  if (archived) {
    return (
      <div className={STRIP}>
        <span className={LABEL}>가입 링크</span>
        <span data-testid="classroom-archived-banner" className="flex-1">
          <span data-testid="join-link-archived-note">
            <Badge>보관됨</Badge>
          </span>
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className={STRIP}>
        <span className={LABEL}>가입 링크</span>
        <span
          data-testid="join-link"
          className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[13px]"
        >
          {url}
        </span>
        {copied ? (
          <span data-testid="join-link-copied" className="text-[12px] text-verified">
            복사됨
          </span>
        ) : null}
        <button type="button" data-testid="join-link-copy" onClick={copy} className={buttonClass("secondary", "sm")}>
          복사
        </button>
        <button
          type="button"
          data-testid="join-link-regenerate"
          onClick={onRegenerate}
          className="whitespace-nowrap px-1 py-1.5 text-xs text-ink/60 underline underline-offset-[3px] hover:text-ink"
        >
          다시 뽑기
        </button>
      </div>
      {regenerateError ? (
        <ErrorNote>
          <span data-testid="join-link-regenerate-error">다시 뽑지 못했습니다. 다시 시도해주세요.</span>
        </ErrorNote>
      ) : null}
    </div>
  );
}
