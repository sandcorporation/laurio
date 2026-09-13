"use client";

// AI grill 대화 패널 — 왼쪽 컬럼 (FE-12, #37, design/Brief.dc.html).
//
// AI는 제안만 하고 Sponsor가 결정한다: 이번 턴의 제안(`proposals`)은 그 자체로
// 체크리스트에 들어가지 않는다. Sponsor가 "추가" 버튼을 눌러야 비로소
// requirement-draft-panel의 체크리스트로 넘어간다.
import { useState } from "react";

import { ErrorNote, PageHeader, buttonClass } from "@/app/components/ui";
import type { ChatProposal, ParsedChatTurn } from "@/lib/contests/chat-response";
import { CHAT_MESSAGE_MAX_LENGTH } from "@/lib/contests/grill-types";

export interface GrillChatPanelProps {
  messages: ParsedChatTurn[];
  proposals: ChatProposal[];
  onSend: (text: string) => Promise<void>;
  onAddProposal: (proposal: ChatProposal) => void;
  sending: boolean;
  chatError: string | null;
  turnLimitReached: boolean;
}

export function GrillChatPanel({
  messages,
  proposals,
  onSend,
  onAddProposal,
  sending,
  chatError,
  turnLimitReached,
}: GrillChatPanelProps) {
  const [draft, setDraft] = useState("");

  const trimmed = draft.trim();
  const canSend = !sending && !turnLimitReached && trimmed.length > 0 && trimmed.length <= CHAT_MESSAGE_MAX_LENGTH;

  async function handleSubmit() {
    if (!canSend) return;
    const text = trimmed;
    setDraft("");
    await onSend(text);
  }

  return (
    <section className="flex flex-col gap-5 border-r border-rule p-8" data-testid="grill-chat-panel">
      <PageHeader
        eyebrow="AI와 함께 정리하기"
        title="무엇을 만들어야 하는지 같이 좁혀봅시다"
        titleTestId="grill-heading"
        description={
          <>
            여기서 만들어지는 체크리스트가 개발자의 자가 응답, 심사, AI 채점의{" "}
            <strong className="font-semibold text-ink">공통 기준</strong>이 됩니다. 모호하게 적으면 심사 때
            분쟁이 됩니다.
          </>
        }
      />

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto" data-testid="grill-chat-history">
        {messages.length === 0 && (
          <p className="text-sm text-ink/60" data-testid="grill-chat-empty">
            무엇을 만들고 싶은지 편하게 적어보세요 — 막연해도 괜찮습니다, AI가 질문으로 좁혀줍니다.
          </p>
        )}
        {messages.map((message, index) => (
          <div
            key={index}
            data-testid={`grill-chat-message-${index}`}
            data-role={message.role}
            className={`flex gap-3 ${message.role === "sponsor" ? "justify-end" : "justify-start"}`}
          >
            {message.role === "assistant" && (
              <div className="flex h-7 w-7 shrink-0 items-center justify-center border border-ink text-[11px] font-semibold">
                AI
              </div>
            )}
            <div
              data-testid={`grill-chat-message-${index}-content`}
              className={`max-w-[520px] whitespace-pre-wrap break-words text-sm leading-relaxed ${
                message.role === "sponsor"
                  ? "border border-rule bg-surface px-4 py-3"
                  : "pt-1"
              }`}
            >
              {message.content}
            </div>
          </div>
        ))}
      </div>

      {proposals.length > 0 && (
        <div className="flex flex-col gap-2 border border-rule bg-surface p-4" data-testid="grill-proposals">
          <p className="text-xs tracking-wide text-ink/60">AI 제안 — 그대로 추가하거나 체크리스트에서 고쳐 쓰세요</p>
          <ul className="flex flex-col gap-2">
            {proposals.map((proposal, index) => (
              <li
                key={`${proposal.text}-${index}`}
                data-testid={`grill-proposal-${index}`}
                className="flex items-start justify-between gap-3 border-t border-rule pt-2 first:border-t-0 first:pt-0"
              >
                <div className="flex flex-col gap-1">
                  <span
                    className={`w-fit text-[10.5px] font-semibold ${
                      proposal.grade === "required" ? "text-attention" : "text-ink/60"
                    }`}
                  >
                    {proposal.grade === "required" ? "필수" : "선택"}
                  </span>
                  <span className="text-sm">{proposal.text}</span>
                </div>
                <button
                  type="button"
                  onClick={() => onAddProposal(proposal)}
                  data-testid={`grill-proposal-${index}-add`}
                  className={`shrink-0 ${buttonClass("secondary", "sm")}`}
                >
                  체크리스트에 추가
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {chatError && (
        <ErrorNote>
          <span data-testid="grill-chat-error">{chatError}</span>
        </ErrorNote>
      )}

      {turnLimitReached && (
        <p className="text-sm text-attention" data-testid="grill-chat-turn-limit">
          이 공모전의 AI 대화가 너무 길어졌습니다. 지금까지 나온 체크리스트로 진행해 주세요.
        </p>
      )}

      {/* 포커스 표시는 **이 상자**가 낸다. 안의 textarea 는 테두리 없는 작성칸이라
          자기 링을 그리면 상자 안쪽에 이중선이 생겨 `outline-none` 을 걸어 뒀는데,
          그러면 키보드 사용자가 지금 어디에 있는지를 통째로 잃는다 — 저장소 전체에서
          `outline` 을 언급하는 유일한 자리가 그 제거 한 줄이었다. 링을 없애는 대신
          한 단계 바깥으로 옮긴다. */}
      <div className="flex items-end gap-3 border border-ink bg-surface p-3 focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ink">
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void handleSubmit();
            }
          }}
          maxLength={CHAT_MESSAGE_MAX_LENGTH}
          disabled={sending || turnLimitReached}
          placeholder="무엇을 만들고 싶은지 알려주세요"
          rows={2}
          data-testid="grill-chat-input"
          // `outline-none` 은 표시를 없애려는 것이 아니라 위 상자로 옮겼기 때문이다
          // (상자의 `focus-within:outline-*`).
          className="flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-ink/40"
        />
        <span className="pb-1 font-mono text-[11px] text-ink/40" data-testid="grill-chat-length">
          {draft.length}/{CHAT_MESSAGE_MAX_LENGTH}
        </span>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={!canSend}
          data-testid="grill-chat-send"
          className="flex h-9 w-9 shrink-0 items-center justify-center bg-ink text-paper disabled:opacity-50"
        >
          {sending ? "…" : "↑"}
        </button>
      </div>
    </section>
  );
}
