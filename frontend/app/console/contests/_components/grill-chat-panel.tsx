"use client";

// AI grill 대화 패널 — 왼쪽 컬럼 (FE-12, #37, design/Brief.dc.html).
//
// AI는 제안만 하고 Sponsor가 결정한다: 이번 턴의 제안(`proposals`)은 그 자체로
// 체크리스트에 들어가지 않는다. Sponsor가 "추가" 버튼을 눌러야 비로소
// requirement-draft-panel의 체크리스트로 넘어간다.
import { useState } from "react";

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
      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium tracking-widest text-ink/60">AI와 함께 정리하기</p>
        <h1 className="text-2xl font-semibold" data-testid="grill-heading">
          무엇을 만들어야 하는지 같이 좁혀봅시다
        </h1>
        <p className="text-sm leading-relaxed text-ink/70">
          여기서 만들어지는 체크리스트가 개발자의 자가 응답, 심사, AI 채점의{" "}
          <strong className="font-semibold text-ink">공통 기준</strong>이 됩니다. 모호하게 적으면 심사 때
          분쟁이 됩니다.
        </p>
      </div>

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
                  className="shrink-0 border border-ink px-3 py-1 text-xs hover:bg-ink hover:text-paper"
                >
                  체크리스트에 추가
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {chatError && (
        <p role="alert" data-testid="grill-chat-error" className="text-sm text-attention">
          {chatError}
        </p>
      )}

      {turnLimitReached && (
        <p className="text-sm text-attention" data-testid="grill-chat-turn-limit">
          이 공모전의 AI 대화가 너무 길어졌습니다. 지금까지 나온 체크리스트로 진행해 주세요.
        </p>
      )}

      <div className="flex items-end gap-3 border border-ink bg-surface p-3">
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
          className="flex h-9 w-9 shrink-0 items-center justify-center bg-ink text-paper disabled:opacity-40"
        >
          {sending ? "…" : "↑"}
        </button>
      </div>
    </section>
  );
}
