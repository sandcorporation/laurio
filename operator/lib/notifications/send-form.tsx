"use client";

// 「운영팀 알림」 작성 화면(#418/#419, #424 — 골간으로 옮긴다) — 검색 → 작성(이미지
// 포함) → 확인 → 보내기. 한 번에 한 사람에게만 보낸다(CONTEXT.md 「운영자 알림」
// User Story 10) — 그래서 받는 사람을 고르고 나면 검색창이 사라지고 그 한 사람만
// 남는다. 시안 `docs/design/operator/OperatorNotice.dc.html`의 단계 표시·카드
// 골간을 쓴다 — 픽셀이 아니라 조각을 옮긴다.
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { Panel } from "@/app/components/panel";

import { searchRecipients, sendOperatorNotice } from "./actions";
import { useOperatorNoticeImageUpload } from "./use-image-upload";
import { formatFileSize } from "./image-constraints";
import type { Recipient } from "./types";

type Step = "search" | "compose" | "confirm";

const STEP_ORDER: readonly Step[] = ["search", "compose", "confirm"];
const STEP_LABELS: Record<Step, string> = {
  search: "1. 받는 사람",
  compose: "2. 작성",
  confirm: "3. 확인",
};

const PRIMARY_BUTTON = "bg-ink px-4 py-2.5 text-[13.5px] font-medium text-paper disabled:opacity-50";
const SECONDARY_BUTTON =
  "border border-rule bg-surface px-3 py-1.5 text-[12.5px] text-ink whitespace-nowrap disabled:opacity-50";

function StepIndicator({ current }: { current: Step }) {
  const currentIndex = STEP_ORDER.indexOf(current);
  return (
    <div data-testid="operator-notice-steps" className="flex items-end gap-[26px]">
      {STEP_ORDER.map((step, index) => {
        const isCurrent = step === current;
        const isPast = index < currentIndex;
        return (
          <div
            key={step}
            data-testid={`operator-notice-step-${step}`}
            aria-current={isCurrent ? "step" : undefined}
            className={`pb-1 text-[13px] ${
              isCurrent
                ? "border-b-2 border-attention font-semibold text-ink"
                : isPast
                  ? "font-normal text-ink"
                  : "font-normal text-ink/45"
            }`}
          >
            {STEP_LABELS[step]}
          </div>
        );
      })}
    </div>
  );
}

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
  const [imageFileSize, setImageFileSize] = useState<number | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
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

  function clearImage() {
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    setImageObjectKey(null);
    setImageFileName(null);
    setImageFileSize(null);
    setImagePreviewUrl(null);
  }

  function resetToSearch() {
    setSelected(null);
    setTitle("");
    setBody("");
    clearImage();
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
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
      setImageObjectKey(objectKey);
      setImageFileName(file.name);
      setImageFileSize(file.size);
      setImagePreviewUrl(URL.createObjectURL(file));
    } catch {
      // 오류 문구는 imageUploadState.error 가 이미 들고 있다.
    }
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
    <section data-testid="send-operator-notice-section" className="flex flex-col gap-[18px]">
      <StepIndicator current={step} />

      {step === "search" && (
        <Panel title="받는 사람 찾기">
          <form onSubmit={handleSearch} data-testid="operator-notice-search-form" className="flex flex-col gap-[14px] p-[15px]">
            <label className="flex flex-col gap-[5px]">
              <span className="text-[11.5px] text-ink/45">받는 사람 검색(이메일 또는 이름)</span>
              <input
                data-testid="operator-notice-search-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="border border-rule bg-paper px-[11px] py-2 text-[13px] text-ink"
              />
            </label>
            <button type="submit" data-testid="operator-notice-search-submit" disabled={searching} className={`${PRIMARY_BUTTON} w-fit`}>
              {searching ? "검색 중..." : "검색"}
            </button>
            {searchError && (
              <p role="alert" data-testid="operator-notice-search-error" className="text-[12.5px] text-attention">
                {searchError}
              </p>
            )}
            {results.length > 0 && (
              <ul data-testid="operator-notice-search-results" className="flex flex-col divide-y divide-rule border border-rule">
                {results.map((recipient) => (
                  <li key={recipient.id} className="flex items-center justify-between gap-3 px-[12px] py-[10px] text-[13px]">
                    <span>
                      {recipient.display_name} <span className="text-ink/45">({recipient.email})</span>
                    </span>
                    <button
                      type="button"
                      data-testid={`operator-notice-select-${recipient.id}`}
                      onClick={() => selectRecipient(recipient)}
                      className={SECONDARY_BUTTON}
                    >
                      선택
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </form>
        </Panel>
      )}

      {step === "compose" && selected && (
        <Panel title="운영팀 알림 보내기" meta="한 번에 한 사람">
          <form onSubmit={handleConfirm} data-testid="operator-notice-compose-form" className="flex flex-col gap-[14px] p-[15px]">
            <div className="flex items-center justify-between gap-3 border border-rule bg-paper px-3 py-[10px]">
              <p data-testid="operator-notice-selected-recipient" className="text-[13px]">
                {selected.display_name} <span className="text-ink/45">· {selected.email}</span>
              </p>
              <button
                type="button"
                data-testid="operator-notice-change-recipient"
                onClick={resetToSearch}
                className={SECONDARY_BUTTON}
              >
                다른 사람 선택
              </button>
            </div>

            <label className="flex flex-col gap-[5px]">
              <span className="text-[11.5px] text-ink/45">제목 (필수)</span>
              <input
                data-testid="operator-notice-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="border border-rule bg-paper px-[11px] py-2 text-[13px] text-ink"
              />
            </label>

            <label className="flex flex-col gap-[5px]">
              <span className="text-[11.5px] text-ink/45">본문</span>
              <textarea
                data-testid="operator-notice-body"
                value={body}
                onChange={(event) => setBody(event.target.value)}
                className="min-h-[72px] border border-rule bg-paper px-[11px] py-2 text-[13px] text-ink"
              />
            </label>

            <div className="flex flex-col gap-[7px]">
              <span className="text-[11.5px] text-ink/45">이미지 (선택 · png·jpeg·webp)</span>

              {imageObjectKey ? (
                <div className="flex items-center gap-[11px] border border-rule bg-paper px-3 py-[10px]">
                  {imagePreviewUrl && (
                    <img
                      src={imagePreviewUrl}
                      alt="첨부한 이미지 미리보기"
                      data-testid="operator-notice-image-preview-thumb"
                      className="h-10 w-16 shrink-0 border border-rule bg-surface object-cover"
                    />
                  )}
                  <p className="min-w-0 flex-1 truncate text-[12.5px]" data-testid="operator-notice-image-attached">
                    {imageFileName}
                    {imageFileSize !== null && (
                      <span className="text-ink/45" data-testid="operator-notice-image-size">
                        {" "}
                        · {formatFileSize(imageFileSize)}
                      </span>
                    )}
                  </p>
                  <button type="button" data-testid="operator-notice-image-remove" onClick={clearImage} className={SECONDARY_BUTTON}>
                    떼기
                  </button>
                </div>
              ) : (
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  data-testid="operator-notice-image-input"
                  disabled={imageUploadState.status === "uploading" || imageUploadState.status === "requesting"}
                  onChange={handleImageChange}
                  className="text-[12.5px]"
                />
              )}

              {(imageUploadState.status === "requesting" || imageUploadState.status === "uploading") && (
                <p data-testid="operator-notice-image-uploading" className="text-[12.5px] text-ink/62">
                  이미지 업로드 중...
                </p>
              )}
              {imageUploadState.status === "error" && imageUploadState.error && (
                <p role="alert" data-testid="operator-notice-image-error" className="text-[12.5px] text-attention">
                  {imageUploadState.error}
                </p>
              )}
            </div>

            <div className="flex gap-2">
              <button type="submit" data-testid="operator-notice-review" disabled={title.trim() === ""} className={PRIMARY_BUTTON}>
                확인으로
              </button>
            </div>
          </form>
        </Panel>
      )}

      {step === "confirm" && selected && (
        <Panel title="확인">
          <div data-testid="operator-notice-confirm" className="flex flex-col gap-[10px] p-[15px]">
            <p className="text-[13px] text-attention">다음 내용으로 보냅니다 — 보낸 뒤에는 고칠 수 없습니다.</p>
            <p data-testid="operator-notice-confirm-recipient" className="text-[13px]">
              받는 사람: {selected.display_name} ({selected.email})
            </p>
            <p data-testid="operator-notice-confirm-title" className="text-[13px]">
              제목: {title}
            </p>
            {body && (
              <p data-testid="operator-notice-confirm-body" className="text-[13px]">
                본문: {body}
              </p>
            )}
            {imageFileName && (
              <p data-testid="operator-notice-confirm-image" className="text-[13px]">
                이미지 첨부됨: {imageFileName}
              </p>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                data-testid="operator-notice-back-to-compose"
                onClick={() => setStep("compose")}
                className={SECONDARY_BUTTON}
              >
                수정
              </button>
              <button
                type="button"
                data-testid="operator-notice-send"
                onClick={handleSend}
                disabled={sending}
                className={PRIMARY_BUTTON}
              >
                {sending ? "보내는 중..." : "보내기"}
              </button>
            </div>
            {sendError && (
              <p role="alert" data-testid="operator-notice-send-error" className="text-[12.5px] text-attention">
                {sendError}
              </p>
            )}
          </div>
        </Panel>
      )}
    </section>
  );
}
