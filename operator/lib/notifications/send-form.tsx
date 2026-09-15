"use client";

// 「운영팀 알림」 작성 화면(#418/#419) — 검색 → 작성(이미지 포함) → 확인 → 보내기.
// 한 번에 한 사람에게만 보낸다(CONTEXT.md 「운영자 알림」 User Story 10) — 그래서
// 받는 사람을 고르고 나면 검색창이 사라지고 그 한 사람만 남는다.
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { searchRecipients, sendOperatorNotice } from "./actions";
import { useOperatorNoticeImageUpload } from "./use-image-upload";
import type { Recipient } from "./types";

type Step = "search" | "compose" | "confirm";

export function SendOperatorNoticeForm({
  initialRecipient = null,
  onSent,
  onSessionExpired,
}: {
  // 무료 공모전 수상자 옆 「운영팀 알림 보내기」가 채워 보낸 받는 사람(#420) —
  // 있으면 검색을 건너뛰고 바로 작성 단계에서 시작한다.
  initialRecipient?: Recipient | null;
  onSent: () => void;
  onSessionExpired: () => void;
}) {
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<Recipient[]>([]);
  const [selected, setSelected] = useState<Recipient | null>(initialRecipient);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [imageObjectKey, setImageObjectKey] = useState<string | null>(null);
  const [imageFileName, setImageFileName] = useState<string | null>(null);
  const [step, setStep] = useState<Step>(initialRecipient ? "compose" : "search");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const { state: imageUploadState, upload: uploadImage } = useOperatorNoticeImageUpload();

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearchError(null);
    setSearching(true);
    const result = await searchRecipients(query);
    setSearching(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setSearchError(result.detail);
      return;
    }
    setResults(result.data);
  }

  function selectRecipient(recipient: Recipient) {
    setSelected(recipient);
    setResults([]);
    setStep("compose");
  }

  function resetToSearch() {
    setSelected(null);
    setTitle("");
    setBody("");
    setImageObjectKey(null);
    setImageFileName(null);
    setStep("search");
  }

  function handleConfirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStep("confirm");
  }

  async function handleImageChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const objectKey = await uploadImage(file);
      setImageObjectKey(objectKey);
      setImageFileName(file.name);
    } catch {
      // 오류 문구는 imageUploadState.error 가 이미 들고 있다.
    }
  }

  function removeImage() {
    setImageObjectKey(null);
    setImageFileName(null);
  }

  async function handleSend() {
    if (!selected) return;
    setSendError(null);
    setSending(true);
    const result = await sendOperatorNotice({
      recipientId: selected.id,
      title,
      body,
      imageObjectKey: imageObjectKey ?? undefined,
    });
    setSending(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setSendError(result.detail);
      return;
    }

    resetToSearch();
    onSent();
  }

  return (
    <section data-testid="send-operator-notice-section">
      <h2>운영팀 알림 보내기</h2>

      {step === "search" && (
        <form onSubmit={handleSearch} data-testid="operator-notice-search-form">
          <label>
            받는 사람 검색(이메일 또는 이름)
            <input
              data-testid="operator-notice-search-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <button type="submit" data-testid="operator-notice-search-submit" disabled={searching}>
            {searching ? "검색 중..." : "검색"}
          </button>
          {searchError && (
            <p role="alert" data-testid="operator-notice-search-error">
              {searchError}
            </p>
          )}
          {results.length > 0 && (
            <ul data-testid="operator-notice-search-results">
              {results.map((recipient) => (
                <li key={recipient.id}>
                  {recipient.display_name} ({recipient.email})
                  <button
                    type="button"
                    data-testid={`operator-notice-select-${recipient.id}`}
                    onClick={() => selectRecipient(recipient)}
                  >
                    선택
                  </button>
                </li>
              ))}
            </ul>
          )}
        </form>
      )}

      {step === "compose" && selected && (
        <form onSubmit={handleConfirm} data-testid="operator-notice-compose-form">
          <p data-testid="operator-notice-selected-recipient">
            받는 사람: {selected.display_name} ({selected.email})
          </p>
          <button type="button" data-testid="operator-notice-change-recipient" onClick={resetToSearch}>
            다른 사람 선택
          </button>
          <label>
            제목
            <input
              data-testid="operator-notice-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label>
            본문
            <textarea
              data-testid="operator-notice-body"
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <label>
            이미지(선택, png·jpeg·webp)
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              data-testid="operator-notice-image-input"
              disabled={imageUploadState.status === "uploading" || imageUploadState.status === "requesting"}
              onChange={handleImageChange}
            />
          </label>
          {(imageUploadState.status === "requesting" || imageUploadState.status === "uploading") && (
            <p data-testid="operator-notice-image-uploading">이미지 업로드 중...</p>
          )}
          {imageUploadState.status === "error" && imageUploadState.error && (
            <p role="alert" data-testid="operator-notice-image-error">
              {imageUploadState.error}
            </p>
          )}
          {imageObjectKey && (
            <p data-testid="operator-notice-image-attached">
              첨부됨: {imageFileName}
              <button type="button" data-testid="operator-notice-image-remove" onClick={removeImage}>
                제거
              </button>
            </p>
          )}
          <button type="submit" data-testid="operator-notice-review" disabled={title.trim() === ""}>
            확인
          </button>
        </form>
      )}

      {step === "confirm" && selected && (
        <div data-testid="operator-notice-confirm">
          <p>다음 내용으로 보냅니다 — 보낸 뒤에는 고칠 수 없습니다.</p>
          <p data-testid="operator-notice-confirm-recipient">
            받는 사람: {selected.display_name} ({selected.email})
          </p>
          <p data-testid="operator-notice-confirm-title">제목: {title}</p>
          {body && <p data-testid="operator-notice-confirm-body">본문: {body}</p>}
          {imageFileName && (
            <p data-testid="operator-notice-confirm-image">이미지 첨부됨: {imageFileName}</p>
          )}
          <button type="button" data-testid="operator-notice-back-to-compose" onClick={() => setStep("compose")}>
            수정
          </button>
          <button
            type="button"
            data-testid="operator-notice-send"
            onClick={handleSend}
            disabled={sending}
          >
            {sending ? "보내는 중..." : "보내기"}
          </button>
          {sendError && (
            <p role="alert" data-testid="operator-notice-send-error">
              {sendError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
