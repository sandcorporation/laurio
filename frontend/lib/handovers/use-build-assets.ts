"use client";

// 빌드 자산(#180, #14) — Award된 Submission에 Developer가 추가로 올리는
// 빌드 설정·서명키·스토어 메타데이터·실행 문서.
//
// Sponsor의 인수 확인과 Developer의 업로드가 **같은 목록**을 본다 — 화면이
// 둘이라 훅도 둘로 나누고 싶어지지만, 그러면 "무엇을 냈는지"가 두 갈래로
// 갈릴 수 있다. 조회(`useBuildAssets`)는 공유하고 쓰기(`recordBuildAsset`)만
// Developer 전용 화면에서 쓴다 — 백엔드 자체가 그렇게 나눠 인가한다
// (`handovers.api`: 업로드는 본인 Submission만, 조회는 본인 또는 그 Contest의
// Sponsor).
import { useBackendQuery } from "@laurio/bff-client";
import type { components } from "@laurio/bff-client/schema";

import { bffClient } from "@/lib/bff/client";

export type BuildAsset = components["schemas"]["BuildAssetOut"];
export type BuildAssetKind = components["schemas"]["BuildAssetIn"]["kind"];

/** `BuildAsset.Kind` 번역표(backend/handovers/models.py). 새 종류가 서버에
 * 생겨도 여기서 옵션을 더하기 전까지는 셀렉트에 나타나지 않을 뿐이다 —
 * 서버가 `_BUILD_ASSET_KINDS`로 알 수 없는 종류를 422로 이미 막으므로,
 * 이 표가 뒤처져도 잘못된 값이 저장되지는 않는다. */
export const BUILD_ASSET_KINDS: { value: BuildAssetKind; label: string }[] = [
  { value: "build_config", label: "빌드 설정" },
  { value: "signing_key", label: "서명키" },
  { value: "store_metadata", label: "스토어 메타데이터" },
  { value: "run_docs", label: "실행 문서" },
  { value: "other", label: "기타" },
];

export function buildAssetKindLabel(kind: string): string {
  return BUILD_ASSET_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

export type BuildAssetsState =
  | { status: "loading" }
  | { status: "forbidden"; message: string }
  | { status: "error" }
  | { status: "ready"; assets: BuildAsset[] };

/** Award된 Submission의 빌드 자산 목록. 본인이거나 그 Contest의 Sponsor여야
 * 200을 받는다(handovers.api.list_build_assets).
 *
 * `submissionId`가 `null`이면 아직 부를 준비가 안 된 것이다(예: 인수 확인
 * 화면이 Handover 조회를 먼저 끝내 submission_id를 얻어야 하는 경우) —
 * `useBackendQuery`의 `path === null` 규약과 같다: 그동안 "loading"에 머물고
 * 요청을 보내지 않는다. */
export function useBuildAssets(submissionId: number | string | null): {
  state: BuildAssetsState;
  reload: () => void;
} {
  const path =
    submissionId === null ? null : `/api/backend/submissions/${submissionId}/build-assets`;
  const { state, reload } = useBackendQuery<BuildAsset[]>(bffClient, path);

  if (state.status === "loading") return { state: { status: "loading" }, reload };
  if (state.status === "error") {
    if (state.failure.status === 403) {
      return { state: { status: "forbidden", message: state.failure.detail }, reload };
    }
    return { state: { status: "error" }, reload };
  }
  return { state: { status: "ready", assets: state.data }, reload };
}

/** Developer가 이미 storage에 올린 빌드 자산의 object_key를 기록한다 — 바이트
 * 자체는 presigned 업로드(ADR-0005)가 이미 옮겼다. */
export async function recordBuildAsset(
  submissionId: number | string,
  payload: { kind: string; objectKey: string; label?: string },
): Promise<{ ok: true; asset: BuildAsset } | { ok: false; message: string }> {
  const result = await bffClient.post<BuildAsset>(
    `/api/backend/submissions/${submissionId}/build-assets`,
    { kind: payload.kind, object_key: payload.objectKey, label: payload.label ?? "" },
  );
  if (!result.ok) return { ok: false, message: result.detail };
  return { ok: true, asset: result.data };
}
