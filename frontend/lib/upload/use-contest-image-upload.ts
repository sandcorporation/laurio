"use client";

// Contest 이미지 업로드 (#234/#236, ADR-0032).
//
// `lib/upload/use-presigned-upload.ts`(소스·시연 영상 등)와 갈리는 이유가 하나다 —
// 저 훅은 presigned **PUT**(파일 바이트를 그대로 요청 본문으로 보내고, 서명은
// 헤더에 실린다)을 가정하는데, 이미지는 presigned **POST**로 발급된다(백엔드가
// 크기 상한·content-type을 서명된 정책 필드에 묶어, 스토리지 자신이 위반을
// 거절하게 한다 — ADR-0032). POST는 본문이 multipart/form-data이고, 서명된
// 필드들을 파일보다 **먼저** 실어야 정책이 성립한다.
//
// 업로드가 끝나도 아직 Contest에 붙지 않는다 — `POST
// /contests/{id}/images`로 object_key를 등록해야 화면에 나타나고
// 편집 게이트가 닫힌 뒤 잠기는 대상이 된다. 그래서 이 훅의 결과는 "등록까지
// 끝난 ContestImage"다.
//
import { useCallback, useState } from "react";
import { bffClient } from "@/lib/bff/client";

export interface ContestImage {
  id: number;
  url: string;
  order: number;
}

interface UploadUrlResponse {
  object_key: string;
  upload_url: string;
  method: string;
  fields: Record<string, string>;
  expires_at: string;
}

export type ContestImageUploadStatus = "idle" | "requesting" | "uploading" | "registering" | "error";

export interface ContestImageUploadState {
  status: ContestImageUploadStatus;
  error: string | null;
}

async function requestUploadUrl(
  contestId: number,
  contentType: string,
): Promise<UploadUrlResponse> {
  const result = await bffClient.post<UploadUrlResponse>(
    `/api/backend/contests/${contestId}/images/upload-url`,
    { content_type: contentType },
  );
  if (!result.ok) throw new Error(result.detail);
  return result.data;
}

function postToStorage(presigned: UploadUrlResponse, file: File): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    // 서명된 필드가 `file`보다 먼저 실려야 한다 — presigned POST 정책의 요구사항이다.
    for (const [key, value] of Object.entries(presigned.fields)) {
      form.append(key, value);
    }
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    // presigned.upload_url은 스토리지(공개 이미지 버킷)의 절대 URL이다 — 이
    // 요청은 Next를 거치지 않고 그 오리진으로 직접 나간다.
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

async function registerImage(
  contestId: number,
  objectKey: string,
): Promise<ContestImage> {
  const result = await bffClient.post<ContestImage>(
    `/api/backend/contests/${contestId}/images`,
    { object_key: objectKey },
  );
  if (!result.ok) throw new Error(result.detail);
  return result.data;
}

export interface UseContestImageUploadResult {
  state: ContestImageUploadState;
  upload: (file: File) => Promise<ContestImage>;
}

export function useContestImageUpload(
  contestId: number,
): UseContestImageUploadResult {
  const [state, setState] = useState<ContestImageUploadState>({ status: "idle", error: null });

  const upload = useCallback(
    async (file: File): Promise<ContestImage> => {
      setState({ status: "requesting", error: null });
      try {
        const presigned = await requestUploadUrl(
          contestId,
          file.type || "application/octet-stream",
        );

        setState({ status: "uploading", error: null });
        await postToStorage(presigned, file);

        setState({ status: "registering", error: null });
        const image = await registerImage(contestId, presigned.object_key);

        setState({ status: "idle", error: null });
        return image;
      } catch (error) {
        const message = error instanceof Error ? error.message : "이미지 업로드에 실패했습니다.";
        setState({ status: "error", error: message });
        throw error;
      }
    },
    [contestId],
  );

  return { state, upload };
}
