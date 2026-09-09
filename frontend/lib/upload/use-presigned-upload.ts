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
import { bffClient } from "@/lib/bff/client";

export type UploadStatus = "idle" | "requesting" | "uploading" | "done" | "error";

export interface UploadState {
  status: UploadStatus;
  progress: number;
  error: string | null;
  objectKey: string | null;
  // 업로드한 File의 MIME 타입(#241) — 제출 시 그대로 실어 보내면 백엔드가
  // SubmissionAsset.content_type에 남겨 다운로드 파일명의 확장자를 유도한다.
  // 브라우저가 형식을 못 알아낸 파일(빈 문자열)이면 null로 정규화한다.
  contentType: string | null;
}

export interface UploadResult {
  objectKey: string;
  contentType: string | null;
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
  // 인증 구역 호출이다 — 맨 fetch 였을 때는 401 이 그냥 「발급 실패」로 보였다(#147).
  const result = await bffClient.post<PresignedUpload>("/api/backend/storage/uploads", {
    target_ref: targetRef,
    content_type: contentType ?? null,
  });

  if (!result.ok) throw new Error(result.detail);
  return result.data;
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
  upload: (file: File) => Promise<UploadResult>;
  retry: () => Promise<UploadResult>;
}

export function usePresignedUpload(targetRef: string): UsePresignedUploadResult {
  const [state, setState] = useState<UploadState>({
    status: "idle",
    progress: 0,
    error: null,
    objectKey: null,
    contentType: null,
  });
  const fileRef = useRef<File | null>(null);

  const attempt = useCallback(
    async (file: File): Promise<UploadResult> => {
      const contentType = file.type || null;
      setState({
        status: "requesting",
        progress: 0,
        error: null,
        objectKey: null,
        contentType,
      });
      const presigned = await requestPresignedUpload(targetRef, contentType ?? undefined);

      setState((prev) => ({ ...prev, status: "uploading" }));
      try {
        await putWithProgress(presigned, file, (percent) => {
          setState((prev) => ({ ...prev, progress: percent }));
        });
      } catch (uploadError) {
        // 발급받은 URL이 만료됐을 수 있다(FE-09 인수조건) — 한 번 재발급받아
        // 다시 시도한다. 그래도 실패하면 진짜 실패로 본다.
        const reissued = await requestPresignedUpload(targetRef, contentType ?? undefined);
        await putWithProgress(reissued, file, (percent) => {
          setState((prev) => ({ ...prev, progress: percent }));
        }).catch((retryError: unknown) => {
          throw retryError instanceof Error ? retryError : uploadError;
        });
        setState({
          status: "done",
          progress: 100,
          error: null,
          objectKey: reissued.object_key,
          contentType,
        });
        return { objectKey: reissued.object_key, contentType };
      }

      setState({
        status: "done",
        progress: 100,
        error: null,
        objectKey: presigned.object_key,
        contentType,
      });
      return { objectKey: presigned.object_key, contentType };
    },
    [targetRef],
  );

  const upload = useCallback(
    async (file: File): Promise<UploadResult> => {
      fileRef.current = file;
      try {
        return await attempt(file);
      } catch (error) {
        const message = error instanceof Error ? error.message : "업로드에 실패했습니다.";
        setState({ status: "error", progress: 0, error: message, objectKey: null, contentType: null });
        throw error;
      }
    },
    [attempt],
  );

  const retry = useCallback((): Promise<UploadResult> => {
    if (!fileRef.current) {
      return Promise.reject(new Error("다시 시도할 파일이 없습니다. 파일을 다시 선택해주세요."));
    }
    return upload(fileRef.current);
  }, [upload]);

  return { state, upload, retry };
}
