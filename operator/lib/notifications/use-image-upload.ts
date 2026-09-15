"use client";

// 운영팀 알림 이미지 업로드(#419) — presigned POST로 비공개 버킷에 올린다
// (frontend/lib/upload/use-contest-image-upload.ts와 같은 관용구, 서명된
// 필드가 `file`보다 먼저 실려야 한다). 등록은 업로드 직후가 아니라 알림을
// 실제로 「보내기」할 때 한 번에 끝난다 — 그래서 이 훅은 object_key만 돌려주고
// 어디에도 붙이지 않는다.
import { useCallback, useState } from "react";

import { bffClient } from "@/lib/bff/client";

interface UploadUrlResponse {
  object_key: string;
  upload_url: string;
  method: string;
  fields: Record<string, string>;
  expires_at: string;
}

export type ImageUploadStatus = "idle" | "requesting" | "uploading" | "error";

export interface ImageUploadState {
  status: ImageUploadStatus;
  error: string | null;
}

async function requestUploadUrl(contentType: string): Promise<UploadUrlResponse> {
  const result = await bffClient.post<UploadUrlResponse>(
    "/api/backend/operator/notifications/operator-notices/image-upload-url",
    { content_type: contentType },
  );
  if (!result.ok) throw new Error(result.detail);
  return result.data;
}

function postToStorage(presigned: UploadUrlResponse, file: File): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(presigned.fields)) {
      form.append(key, value);
    }
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open(presigned.method, presigned.upload_url);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(
          new Error(
            `이미지 업로드가 실패했습니다 (${xhr.status}). 형식·크기 제한을 확인하거나 다시 시도해 주세요.`,
          ),
        );
      }
    };
    xhr.onerror = () => reject(new Error("네트워크 오류로 이미지 업로드에 실패했습니다."));
    xhr.send(form);
  });
}

export interface UseOperatorNoticeImageUploadResult {
  state: ImageUploadState;
  upload: (file: File) => Promise<string>;
}

export function useOperatorNoticeImageUpload(): UseOperatorNoticeImageUploadResult {
  const [state, setState] = useState<ImageUploadState>({ status: "idle", error: null });

  const upload = useCallback(async (file: File): Promise<string> => {
    setState({ status: "requesting", error: null });
    try {
      const presigned = await requestUploadUrl(file.type || "application/octet-stream");

      setState({ status: "uploading", error: null });
      await postToStorage(presigned, file);

      setState({ status: "idle", error: null });
      return presigned.object_key;
    } catch (error) {
      const message = error instanceof Error ? error.message : "이미지 업로드에 실패했습니다.";
      setState({ status: "error", error: message });
      throw error;
    }
  }, []);

  return { state, upload };
}
