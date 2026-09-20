"use client";

// 소스 파일의 presigned 업로드 (#286) — 공개 앱(frontend/lib/upload/
// use-presigned-upload.ts)과 같은 계약(발급은 BFF 프록시로, 실제 바이트는
// storage로 직접)이지만, 이 앱은 진행률·만료 재시도 같은 편의는 갖추지 않은
// 최소 구현이다 — 이 화면의 인수조건(#286)은 "낸 것이 시도 목록에 선다"까지다.
import * as Sentry from "@sentry/nextjs";
import { useCallback, useState } from "react";

import type { ApiFailure } from "@codemit/bff-client";

import { bffClient, unwrap } from "@/lib/bff/client";
import { describeUploadFailure, type UploadFailureContext } from "./upload-failure";

function isApiFailure(error: unknown): error is ApiFailure {
  return typeof error === "object" && error !== null && "ok" in error && !(error as ApiFailure).ok;
}

/** 서버가 준 실패면 그 문구를 그대로 쓰고(#462 — 배열 detail 도 이미 사람이
 * 읽는 문자열로 좁혀져 온다), 그 밖의 오류(네트워크·업로드 자체의 실패)는
 * `Error.message`를 쓴다. */
function uploadErrorMessage(error: unknown): string {
  if (isApiFailure(error)) return error.detail;
  if (error instanceof Error) return error.message;
  return "업로드에 실패했습니다.";
}

export type UploadStatus = "idle" | "uploading" | "done" | "error";

export type UploadState = {
  status: UploadStatus;
  error: string | null;
  objectKey: string | null;
  contentType: string | null;
};

type PresignedUpload = {
  object_key: string;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  fields: Record<string, string>;
  max_size_bytes: number | null;
};

/** 바이트는 우리 서버를 거치지 않고 스토리지로 직접 간다 — 그래서 이 실패는
 *  백엔드 로그 어디에도 남지 않는다. 오류 수집기에 남기는 것은 이 자리뿐이다
 *  (2026-09-18, prod 에서 실제로 아무 기록 없이 실패했다). */
async function sendToStorage(presigned: PresignedUpload, file: File): Promise<void> {
  const context: UploadFailureContext = {
    uploadUrl: presigned.upload_url,
    method: presigned.method,
    fileSize: file.size,
  };

  let response: Response;
  try {
    response =
      presigned.method === "POST"
        ? await fetch(presigned.upload_url, { method: "POST", body: postForm(presigned, file) })
        : await fetch(presigned.upload_url, {
            method: presigned.method,
            headers: presigned.headers,
            body: file,
          });
  } catch (error) {
    throw reportUploadFailure(error, context);
  }

  if (!response.ok) {
    throw reportUploadFailure(new Error(`upload responded ${response.status}`), {
      ...context,
      status: response.status,
    });
  }
}

function postForm(presigned: PresignedUpload, file: File): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(presigned.fields)) {
    form.append(key, value);
  }
  form.append("file", file);
  return form;
}

/** 수집기에 원문과 맥락을 보내고, 화면에는 한국어 한 문장을 던진다. */
function reportUploadFailure(error: unknown, context: UploadFailureContext): Error {
  const { message, tags } = describeUploadFailure(error, context);
  Sentry.captureException(error, { tags });
  return new Error(message);
}

export function useSourceUpload(targetRef: string | null) {
  const [state, setState] = useState<UploadState>({
    status: "idle",
    error: null,
    objectKey: null,
    contentType: null,
  });

  const upload = useCallback(
    async (file: File) => {
      if (!targetRef) throw new Error("아직 준비되지 않았습니다. 잠시 후 다시 시도해주세요.");

      const contentType = file.type || null;
      setState({ status: "uploading", error: null, objectKey: null, contentType });
      try {
        const presigned = await unwrap(
          bffClient.post<PresignedUpload>("/api/backend/storage/uploads", {
            target_ref: targetRef,
            content_type: contentType,
          }),
        );
        if (presigned.max_size_bytes !== null && file.size > presigned.max_size_bytes) {
          const megabytes = Math.round((presigned.max_size_bytes / (1024 * 1024)) * 10) / 10;
          throw new Error(`파일이 너무 큽니다. 최대 ${megabytes}MB까지 업로드할 수 있습니다.`);
        }
        await sendToStorage(presigned, file);
        setState({ status: "done", error: null, objectKey: presigned.object_key, contentType });
        return { objectKey: presigned.object_key, contentType };
      } catch (error) {
        setState({
          status: "error",
          error: uploadErrorMessage(error),
          objectKey: null,
          contentType: null,
        });
        throw error;
      }
    },
    [targetRef],
  );

  return { state, upload };
}
