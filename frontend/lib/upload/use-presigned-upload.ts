"use client";

// presigned 업로드 (ADR-0005, FE-09 #34).
//
// 발급 요청(POST /storage/uploads)은 BFF 프록시(FE-08, /api/backend/**)를
// 거쳐 인증된 사용자로 인가되지만, 실제 바이트는 그 자리에서 받은 upload_url로
// **스토리지에 직접** 나간다 — Next를 한 번도 거치지 않는다. 이 파일에서
// fetch로 요청하는 대상이 둘로 갈리는 게 그 증거다: 발급은 상대 경로
// "/api/backend/storage/uploads"(우리 오리진)로, 업로드는 백엔드가 돌려준
// 절대 URL(스토리지 오리진)로 나간다.
//
// **method가 PUT일 수도 POST일 수도 있다(#261).** 이 슬롯(소스·시연 영상·
// 빌드 자산)에 종류별 바이트 상한(#263)이 걸려 있으면 백엔드가 presigned
// POST를 내려준다 — 크기가 서명된 정책 조건에 묶여 넘기면 스토리지 자신이
// 거절한다(presigned PUT은 서명에 크기를 묶을 수단이 없다, ADR-0032/ADR-0035).
// `max_size_bytes`가 함께 오면, 실제 바이트를 보내기 전에(발급 자체는 이미
// 끝난 뒤) 파일 크기를 먼저 재본다 — 몇 GB를 다 올린 뒤 거절당하는 것은
// 잔인하다. 막는 것은 서명이고 이 검사는 빨리 말해 주는 역할일 뿐이다.
import * as Sentry from "@sentry/nextjs";
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
  // presigned POST(#261)의 서명된 정책 필드 — multipart/form-data 본문에
  // "file"보다 먼저 실어야 한다. PUT이면 빈 객체다.
  fields: Record<string, string>;
  expires_at: string;
  // 이 슬롯에 실제로 걸린 바이트 상한. 없으면 null(상한 없음).
  max_size_bytes: number | null;
}

function formatMegabytes(bytes: number): string {
  const megabytes = bytes / (1024 * 1024);
  const rounded = Math.round(megabytes * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}MB`;
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

/** 파일 크기가 이 슬롯의 상한(있으면)을 넘는지 먼저 잰다 — 넘으면 실제 바이트를
 * 보내지 않고 바로 실패시킨다(#261). 서버가 나중에 거절해도 안전하지만(막는 것은
 * 서명이다), 몇 GB를 다 올린 뒤에야 아는 것은 잔인하다. */
function rejectIfOversized(presigned: PresignedUpload, file: File): void {
  if (presigned.max_size_bytes !== null && file.size > presigned.max_size_bytes) {
    throw new Error(`파일이 너무 큽니다. 최대 ${formatMegabytes(presigned.max_size_bytes)}까지 업로드할 수 있습니다.`);
  }
}

function sendToStorage(
  presigned: PresignedUpload,
  file: File,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    // presigned.upload_url은 스토리지의 절대 URL이다 — XHR이 이 요청을 Next가
    // 아니라 그 오리진으로 직접 연다.
    xhr.open(presigned.method, presigned.upload_url);

    let body: File | FormData = file;
    if (presigned.method === "POST") {
      // 서명된 필드가 파일보다 먼저 실려야 한다 — presigned POST 정책의 요구사항이다
      // (lib/upload/use-contest-image-upload.ts와 같은 규칙).
      const form = new FormData();
      for (const [key, value] of Object.entries(presigned.fields)) {
        form.append(key, value);
      }
      form.append("file", file);
      body = form;
    } else {
      for (const [key, value] of Object.entries(presigned.headers)) {
        xhr.setRequestHeader(key, value);
      }
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
        reject(new Error(`업로드가 실패했습니다 (${xhr.status}). 만료됐거나 형식·크기 제한을 확인해 주세요.`));
      }
    };
    xhr.onerror = () => reject(new Error("네트워크 오류로 업로드에 실패했습니다."));
    xhr.send(body);
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
      rejectIfOversized(presigned, file);

      setState((prev) => ({ ...prev, status: "uploading" }));
      try {
        await sendToStorage(presigned, file, (percent) => {
          setState((prev) => ({ ...prev, progress: percent }));
        });
      } catch (uploadError) {
        // 발급받은 URL이 만료됐을 수 있다(FE-09 인수조건) — 한 번 재발급받아
        // 다시 시도한다. 그래도 실패하면 진짜 실패로 본다.
        const reissued = await requestPresignedUpload(targetRef, contentType ?? undefined);
        rejectIfOversized(reissued, file);
        await sendToStorage(reissued, file, (percent) => {
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
        // **여기서만 오류 수집기에 보낸다**(2026-09-18). 바이트는 우리 서버를
        // 거치지 않고 스토리지로 직접 가므로 이 실패는 백엔드 로그 어디에도
        // 남지 않는다 — prod 에서 업로드가 실패했는데 수집기에 아무 기록이
        // 없어 「그때 무슨 일이 있었나」를 물어볼 자리가 없었다. 재시도가
        // 성공한 경우는 여기 닿지 않으므로 소음이 되지 않는다.
        Sentry.captureException(error, {
          tags: {
            upload_target_ref: targetRef,
            upload_file_bytes: String(file.size),
            upload_failure: "final",
          },
        });
        const message = error instanceof Error ? error.message : "업로드에 실패했습니다.";
        setState({ status: "error", progress: 0, error: message, objectKey: null, contentType: null });
        throw error;
      }
    },
    [attempt, targetRef],
  );

  const retry = useCallback((): Promise<UploadResult> => {
    if (!fileRef.current) {
      return Promise.reject(new Error("다시 시도할 파일이 없습니다. 파일을 다시 선택해주세요."));
    }
    return upload(fileRef.current);
  }, [upload]);

  return { state, upload, retry };
}
