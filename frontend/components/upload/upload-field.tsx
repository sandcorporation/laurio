"use client";

// 재사용 가능한 presigned 업로드 필드(FE-09 #34). FE-10(#35) 제출 폼의
// 소스코드·시연 영상 업로드가 이 컴포넌트를 그대로 쓴다.
import { useRef } from "react";

import { usePresignedUpload } from "@/lib/upload/use-presigned-upload";

export interface UploadFieldProps {
  targetRef: string;
  label: string;
  accept?: string;
  // 두 번째 인자(#241)는 업로드한 File의 MIME 타입이다(모르면 null) — 호출자가
  // 그대로 제출 페이로드의 content_type에 실으면 백엔드가 다운로드 파일명의
  // 확장자를 유도한다. 기존 호출부(인자 하나만 받는 콜백)는 그대로 동작한다 —
  // 여분의 인자를 무시하는 함수는 그 타입에 그대로 대입된다.
  onUploaded?: (objectKey: string, contentType: string | null) => void;
  testId: string;
}

export function UploadField({ targetRef, label, accept, onUploaded, testId }: UploadFieldProps) {
  const { state, upload, retry } = usePresignedUpload(targetRef);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const { objectKey, contentType } = await upload(file);
      onUploaded?.(objectKey, contentType);
    } catch {
      // state.error가 이미 이유를 담고 있다 — 아래 UI가 보여준다.
    }
  }

  async function handleRetry() {
    try {
      const { objectKey, contentType } = await retry();
      onUploaded?.(objectKey, contentType);
    } catch {
      // 마찬가지로 state.error에서 보여준다.
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm" htmlFor={`${testId}-input`}>
        {label}
      </label>
      <input
        ref={inputRef}
        id={`${testId}-input`}
        data-testid={`${testId}-input`}
        type="file"
        accept={accept}
        onChange={handleFileChange}
        disabled={state.status === "requesting" || state.status === "uploading"}
      />

      {(state.status === "requesting" || state.status === "uploading") && (
        <div
          role="progressbar"
          aria-valuenow={state.progress}
          aria-valuemin={0}
          aria-valuemax={100}
          data-testid={`${testId}-progress`}
          data-progress={state.progress}
          className="h-2 w-full max-w-xs overflow-hidden rounded-sm border border-rule"
        >
          <div className="h-full bg-verified transition-[width]" style={{ width: `${state.progress}%` }} />
        </div>
      )}

      {state.status === "done" && state.objectKey && (
        <p className="text-sm text-verified" data-testid={`${testId}-done`}>
          업로드 완료: <span className="font-mono">{state.objectKey}</span>
        </p>
      )}

      {state.status === "error" && (
        <div className="flex items-center gap-3">
          <p role="alert" className="text-sm text-attention" data-testid={`${testId}-error`}>
            {state.error}
          </p>
          <button
            type="button"
            onClick={handleRetry}
            data-testid={`${testId}-retry`}
            className="rounded-sm border border-rule px-3 py-1 text-sm hover:border-ink"
          >
            재시도
          </button>
        </div>
      )}
    </div>
  );
}
