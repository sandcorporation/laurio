"use client";

// Contest/Assignment 이미지 패널 (#234/#236, ADR-0032, design 선례
// requirement-draft-panel.tsx).
//
// Sponsor(출제자 포함)가 참고 이미지를 여러 장 올리고, 순서를 바꾸고, 잘못 올린
// 것을 뺀다 — 전부 각 자원의 편집 게이트가 열려 있는 동안에만 된다(공모전은
// 결제가 문을 닫기 전 DRAFT, 과제는 첫 제출이 들어오기 전). 업로드는 presigned
// POST(크기 상한·content-type 이 서명된 정책에 묶인다,
// `lib/upload/use-contest-image-upload.ts`)이고, 업로드가 끝나면 이 화면에
// 바로 그려진다(spec #225 user story 5 — "결제 전에 무엇이 올라갔는지 확인할
// 수 있다").
//
// **`resourcePath`가 두 자원을 가른다.** 백엔드가 같은 `ContestImage` 모델을
// 두 URL 접두어(`/contests/{id}/images/...` · `/assignments/{id}/images/...`)로
// 똑같이 다루므로(#236), 이 컴포넌트도 그 접두어 하나만 넘겨받으면 그대로
// 재사용된다 — 화면마다 두 벌을 만들지 않는다.
import { useRef, useState } from "react";

import { bffClient } from "@/lib/bff/client";
import {
  useContestImageUpload,
  type ContestImage,
  type ContestImageResourcePath,
} from "@/lib/upload/use-contest-image-upload";

export interface ContestImagePanelProps {
  contestId: number;
  images: ContestImage[];
  /** 편집 게이트가 닫혀 있으면 false — 업로드·순서변경·제거를 전부 숨기고 읽기 전용으로 그린다. */
  editable: boolean;
  onImagesChange: (images: ContestImage[]) => void;
  /** 기본값 `"contests"` — Assignment 화면은 `"assignments"`를 넘긴다. */
  resourcePath?: ContestImageResourcePath;
}

function byOrder(a: ContestImage, b: ContestImage): number {
  return a.order - b.order;
}

export function ContestImagePanel({
  contestId,
  images,
  editable,
  onImagesChange,
  resourcePath = "contests",
}: ContestImagePanelProps) {
  const { state, upload } = useContestImageUpload(contestId, resourcePath);
  const [actionError, setActionError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const sorted = [...images].sort(byOrder);

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    setActionError(null);
    // 여러 장을 한 번에 골라도 순서대로 하나씩 올린다 — 병렬로 쏘면 등록
    // 순서(서버가 매기는 order)가 파일을 고른 순서와 어긋날 수 있다.
    //
    // `accumulated`를 로컬로 들고 간다 — `images` prop을 그대로 spread하면
    // 두 번째 파일부터는 아직 리렌더 전(클로저 안의 옛 `images`)을 기준으로
    // 계산해, 방금 등록한 첫 번째 이미지를 덮어써 버린다(실제로 겪은 버그:
    // 두 장을 골랐는데 화면엔 마지막 한 장만 남았다).
    let accumulated = images;
    for (const file of Array.from(fileList)) {
      try {
        const created = await upload(file);
        accumulated = [...accumulated, created];
        onImagesChange(accumulated);
      } catch {
        // useContestImageUpload.state.error 가 이유를 담고 있다 — 아래 UI가 보여준다.
        break;
      }
    }
    if (inputRef.current) inputRef.current.value = "";
  }

  async function patchOrder(imageId: number, order: number): Promise<ContestImage | null> {
    const response = await bffClient.request<ContestImage>(
      `/api/backend/${resourcePath}/${contestId}/images/${imageId}`,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ order }),
      },
    );
    if (!response.ok) {
      setActionError(response.detail || "순서를 바꾸지 못했습니다. 다시 시도해 주세요.");
      return null;
    }
    return response.data;
  }

  async function handleReorder(image: ContestImage, direction: -1 | 1) {
    const currentIndex = sorted.findIndex((img) => img.id === image.id);
    const swapWith = sorted[currentIndex + direction];
    if (!swapWith) return;

    setActionError(null);
    // 진짜 스왑이다 — 한쪽만 상대의 order를 받으면 둘이 같은 값이 되어(동점은
    // id로 갈린다) 화면상 아무것도 안 바뀐 것처럼 보인다(실제로 겪은 버그).
    // 두 PATCH를 순서대로 보낸다: image 를 먼저 자기 자신과 겹치지 않는 값으로
    // 옮겨야 UniqueConstraint 가 없는 이 모델에서도 항상 안전하지만(order에
    // 유일성 제약이 없다), 그래도 "둘 다 갱신됐다"를 응답으로 직접 확인한다.
    const updatedImage = await patchOrder(image.id, swapWith.order);
    if (!updatedImage) return;
    const updatedSwapWith = await patchOrder(swapWith.id, image.order);
    if (!updatedSwapWith) return;

    onImagesChange(
      images.map((img) => {
        if (img.id === updatedImage.id) return updatedImage;
        if (img.id === updatedSwapWith.id) return updatedSwapWith;
        return img;
      }),
    );
  }

  async function handleRemove(image: ContestImage) {
    setActionError(null);
    const response = await bffClient.request(
      `/api/backend/${resourcePath}/${contestId}/images/${image.id}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setActionError(response.detail || "이미지를 빼지 못했습니다. 다시 시도해 주세요.");
      return;
    }
    onImagesChange(images.filter((img) => img.id !== image.id));
  }

  const uploading = state.status === "requesting" || state.status === "uploading" || state.status === "registering";

  return (
    <section
      className="flex flex-col gap-3 border-b border-rule px-6 py-4"
      data-testid="contest-image-panel"
    >
      <h2 className="text-sm font-medium">참고 이미지</h2>
      <p className="text-xs text-ink/60">
        시안·와이어프레임처럼 글로 풀면 흐려지는 조건을 이미지로 보여주세요.{" "}
        {resourcePath === "assignments"
          ? "제출자가 제출을 시작하면 더 이상 고칠 수 없습니다."
          : "결제가 끝나면 더 이상 고칠 수 없습니다."}
      </p>

      {sorted.length === 0 ? (
        <p className="text-sm text-ink/60" data-testid="contest-image-empty">
          아직 올린 이미지가 없습니다.
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="contest-image-list">
          {sorted.map((image, index) => (
            <li key={image.id} className="flex flex-col gap-1" data-testid={`contest-image-${image.id}`}>
              {/* eslint-disable-next-line @next/next/no-img-element -- 공개 버킷의 서명 없는 URL, next/image 원격 최적화 불필요 */}
              <img
                src={image.url}
                alt=""
                className="aspect-video w-full rounded-sm border border-rule object-cover"
              />
              {editable && (
                <div className="flex items-center justify-between gap-1 text-xs text-ink/60">
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => void handleReorder(image, -1)}
                      disabled={index === 0}
                      data-testid={`contest-image-${image.id}-up`}
                      className="rounded-sm border border-rule px-1.5 py-0.5 disabled:opacity-50"
                      aria-label="앞으로 이동"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleReorder(image, 1)}
                      disabled={index === sorted.length - 1}
                      data-testid={`contest-image-${image.id}-down`}
                      className="rounded-sm border border-rule px-1.5 py-0.5 disabled:opacity-50"
                      aria-label="뒤로 이동"
                    >
                      ↓
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleRemove(image)}
                    data-testid={`contest-image-${image.id}-remove`}
                    className="text-attention hover:underline"
                  >
                    빼기
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {editable && (
        <div className="flex flex-col gap-2">
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            onChange={(event) => void handleFiles(event.target.files)}
            disabled={uploading}
            data-testid="contest-image-input"
          />
          {uploading && (
            <p className="text-xs text-ink/60" data-testid="contest-image-uploading">
              올리는 중...
            </p>
          )}
          {state.error && (
            <p role="alert" className="text-xs text-attention" data-testid="contest-image-upload-error">
              {state.error}
            </p>
          )}
          {actionError && (
            <p role="alert" className="text-xs text-attention" data-testid="contest-image-action-error">
              {actionError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
