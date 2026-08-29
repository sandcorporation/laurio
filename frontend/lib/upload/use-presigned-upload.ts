"use client";

// presigned 업로드 (ADR-0005, FE-09 #34).
//
// 발급 요청(POST /storage/uploads)은 BFF 프록시(FE-08, /api/backend/**)를
// 거쳐 인증된 사용자로 인가되지만, 실제 PUT은 그 자리에서 받은 upload_url로
// **스토리지에 직접** 나간다 — Next를 한 번도 거치지 않는다. 이 파일에서
// fetch로 요청하는 대상이 둘로 갈리는 게 그 증거다: 발급은 상대 경로
// "/api/backend/storage/uploads"(우리 오리진)로, 업로드는 백엔드가 돌려준
// 절대 URL(스토리지 오리진)로 나간다.
import { useCallback, useRef, useState } from "react";

export type UploadStatus = "idle" | "requesting" | "uploading" | "done" | "error";

export interface UploadState {
  status: UploadStatus;
  progress: number;
  error: string | null;
  objectKey: string | null;
}

interface PresignedUpload {
  object_key: string;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  expires_at: string;
}

async function requestPresignedUpload(
  targetRef: string,
  contentType: string | undefined,
): Promise<PresignedUpload> {
  const res = await fetch("/api/backend/storage/uploads", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ target_ref: targetRef, content_type: contentType ?? null }),
  });

  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `업로드 URL 발급에 실패했습니다 (${res.status})`);
  }

  return (await res.json()) as PresignedUpload;
}

function putWithProgress(
  presigned: PresignedUpload,
  file: File,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    // presigned.upload_url은 스토리지의 절대 URL이다 — XHR이 이 요청을 Next가
    // 아니라 그 오리진으로 직접 연다.
    xhr.open(presigned.method, presigned.upload_url);
    for (const [key, value] of Object.entries(presigned.headers)) {
      xhr.setRequestHeader(key, value);
    }
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`업로드가 실패했습니다 (${xhr.status}). 만료됐거나 네트워크 문제일 수 있습니다.`));
      }
    };
    xhr.onerror = () => reject(new Error("네트워크 오류로 업로드에 실패했습니다."));
    xhr.send(file);
  });
}

export interface UsePresignedUploadResult {
  state: UploadState;
  upload: (file: File) => Promise<string>;
  retry: () => Promise<string>;
}

export function usePresignedUpload(targetRef: string): UsePresignedUploadResult {
  const [state, setState] = useState<UploadState>({
    status: "idle",
    progress: 0,
    error: null,
    objectKey: null,
  });
  const fileRef = useRef<File | null>(null);

  const attempt = useCallback(
    async (file: File): Promise<string> => {
      setState({ status: "requesting", progress: 0, error: null, objectKey: null });
      const presigned = await requestPresignedUpload(targetRef, file.type || undefined);

      setState((prev) => ({ ...prev, status: "uploading" }));
      try {
        await putWithProgress(presigned, file, (percent) => {
          setState((prev) => ({ ...prev, progress: percent }));
        });
      } catch (uploadError) {
        // 발급받은 URL이 만료됐을 수 있다(FE-09 인수조건) — 한 번 재발급받아
        // 다시 시도한다. 그래도 실패하면 진짜 실패로 본다.
        const reissued = await requestPresignedUpload(targetRef, file.type || undefined);
        await putWithProgress(reissued, file, (percent) => {
          setState((prev) => ({ ...prev, progress: percent }));
        }).catch((retryError: unknown) => {
          throw retryError instanceof Error ? retryError : uploadError;
        });
        setState({ status: "done", progress: 100, error: null, objectKey: reissued.object_key });
        return reissued.object_key;
      }

      setState({ status: "done", progress: 100, error: null, objectKey: presigned.object_key });
      return presigned.object_key;
    },
    [targetRef],
  );

  const upload = useCallback(
    async (file: File): Promise<string> => {
      fileRef.current = file;
      try {
        return await attempt(file);
      } catch (error) {
        const message = error instanceof Error ? error.message : "업로드에 실패했습니다.";
        setState({ status: "error", progress: 0, error: message, objectKey: null });
        throw error;
      }
    },
    [attempt],
  );

  const retry = useCallback((): Promise<string> => {
    if (!fileRef.current) {
      return Promise.reject(new Error("다시 시도할 파일이 없습니다. 파일을 다시 선택해주세요."));
    }
    return upload(fileRef.current);
  }, [upload]);

  return { state, upload, retry };
}
