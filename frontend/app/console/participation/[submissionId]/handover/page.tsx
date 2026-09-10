"use client";

// 인수 자료 업로드 화면 (#180, #14) — Developer가 Award된 자기 제출물에 빌드
// 자산(빌드 설정·서명키·스토어 메타데이터·실행 문서)을 올린다.
//
// #179가 Sponsor의 확인 버튼을 만들면 돈은 풀린다. 그런데 그 확인이 **무엇을
// 받았다는 확인인지**가 비어 있었다 — 백엔드에는 등록·조회 엔드포인트가 둘 다
// 있는데 부르는 화면이 없었다.
//
// **자료가 없어도 Sponsor의 인수 확인을 막지 않는다.** 이 화면에서 아무것도
// 올리지 않아도 Sponsor는 인수를 끝낼 수 있어야 한다 — 안 그러면 Developer의
// 무응답이 자기 상금을 막는 새 정체가 된다(#167이 닫으려는 바로 그 모양). 그래서
// 이 화면은 그 사실을 먼저 말한다.
//
// 업로드는 이 저장소의 기존 경로(presigned, ADR-0005)를 그대로 쓴다 — 제출
// 폼(submit/page.tsx)의 UploadField를 재사용한다.
import Link from "next/link";
import { use, useEffect, useState } from "react";

import { UploadField } from "@/components/upload/upload-field";
import { useSession } from "@/lib/auth/use-session";
import { bffClient } from "@/lib/bff/client";
import {
  BUILD_ASSET_KINDS,
  buildAssetKindLabel,
  recordBuildAsset,
  useBuildAssets,
  type BuildAssetKind,
} from "@/lib/handovers/use-build-assets";

type SubmissionMeta = { id: number; contest_id: number };

type SubmissionLoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "forbidden"; message: string }
  | { status: "error" }
  | { status: "ready"; submission: SubmissionMeta };

export default function DeveloperBuildAssetsPage({
  params,
}: {
  params: Promise<{ submissionId: string }>;
}) {
  const { submissionId } = use(params);
  const session = useSession();
  const [load, setLoad] = useState<SubmissionLoadState>({ status: "loading" });
  const { state: assets, reload: reloadAssets } = useBuildAssets(submissionId);

  const [kind, setKind] = useState<BuildAssetKind>(BUILD_ASSET_KINDS[0].value);
  const [label, setLabel] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [uploadNonce, setUploadNonce] = useState(0);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;
    void bffClient.get<SubmissionMeta>(`/api/backend/submissions/${submissionId}`).then((result) => {
      if (cancelled) return;
      if (result.ok) return setLoad({ status: "ready", submission: result.data });
      if (result.status === 404) return setLoad({ status: "not-found" });
      if (result.status === 403) return setLoad({ status: "forbidden", message: result.detail });
      setLoad({ status: "error" });
    });
    return () => {
      cancelled = true;
    };
  }, [session.status, submissionId]);

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="build-assets-loading">불러오는 중...</p>
      </main>
    );
  }

  async function handleUploaded(objectKey: string, contentType: string | null) {
    setSaveError(null);
    const result = await recordBuildAsset(submissionId, { kind, objectKey, label, contentType });
    if (!result.ok) {
      setSaveError(result.message);
      return;
    }
    setLabel("");
    // UploadField를 새로 마운트해 "업로드 완료" 잔상 없이 다음 파일을 받는다.
    setUploadNonce((n) => n + 1);
    reloadAssets();
  }

  const userId = session.status === "authenticated" ? session.user.id : null;
  const contestId = load.status === "ready" ? load.submission.contest_id : null;
  const targetRef =
    userId !== null && contestId !== null ? `submission:${contestId}:${userId}:build-asset` : null;

  return (
    <main className="mx-auto max-w-2xl p-10">
      <Link
        className="text-sm text-muted"
        href="/console/participation"
        data-testid="build-assets-back"
      >
        ← 내 참가 현황
      </Link>
      <h1 className="mt-2 text-2xl font-semibold" data-testid="build-assets-heading">
        인수 자료
      </h1>

      {load.status === "not-found" ? (
        <p className="mt-6" data-testid="build-assets-not-found">
          제출물을 찾을 수 없습니다.
        </p>
      ) : load.status === "forbidden" ? (
        <p className="mt-6 text-attention" role="alert" data-testid="build-assets-forbidden">
          {load.message}
        </p>
      ) : load.status === "error" ? (
        <p className="mt-6 text-attention" role="alert" data-testid="build-assets-error">
          자료를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : (
        <>
          <p className="mt-6 text-sm text-ink" data-testid="build-assets-optional-notice">
            빌드 설정·서명키·스토어 메타데이터·실행 문서 등 개최자의 인수에 도움이 될 자료를
            올릴 수 있습니다 — <strong>선택 사항입니다.</strong> 아무것도 올리지 않아도
            개최자는 인수를 확인할 수 있고 상금은 그대로 지급됩니다. 소스코드는 선정
            시점에 이미 공개되어 있습니다.
          </p>

          {targetRef ? (
            <div className="mt-6 flex flex-col gap-3 rounded border border-subtle p-4">
              <div className="flex flex-col gap-1">
                <label className="text-sm" htmlFor="build-asset-kind">
                  종류
                </label>
                <select
                  id="build-asset-kind"
                  className="rounded border border-subtle p-2 text-sm"
                  value={kind}
                  onChange={(event) => setKind(event.target.value as BuildAssetKind)}
                  data-testid="build-asset-kind-select"
                >
                  {BUILD_ASSET_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-sm" htmlFor="build-asset-label">
                  라벨 (선택)
                </label>
                <input
                  id="build-asset-label"
                  className="rounded border border-subtle p-2 text-sm"
                  type="text"
                  maxLength={200}
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="예: release.yaml"
                  data-testid="build-asset-label-input"
                />
              </div>
              <UploadField
                key={uploadNonce}
                targetRef={targetRef}
                label="파일 선택"
                onUploaded={handleUploaded}
                testId="build-asset-upload"
              />
              {saveError ? (
                <p role="alert" className="text-attention" data-testid="build-asset-save-error">
                  {saveError}
                </p>
              ) : null}
            </div>
          ) : null}

          <section className="mt-8" data-testid="build-assets-own-list">
            <h2 className="text-lg font-semibold">올린 자료</h2>
            {assets.status === "loading" ? (
              <p className="mt-2 text-sm text-muted">불러오는 중...</p>
            ) : assets.status === "ready" && assets.assets.length === 0 ? (
              <p className="mt-2 text-sm text-muted" data-testid="build-assets-empty">
                아직 올린 자료가 없습니다.
              </p>
            ) : assets.status === "ready" ? (
              <ul className="mt-2 flex flex-col gap-2">
                {assets.assets.map((asset) => (
                  <li
                    key={asset.id}
                    className="rounded border border-subtle p-3 text-sm"
                    data-testid={`build-asset-${asset.id}`}
                  >
                    <span className="rounded-sm border border-rule px-2 py-0.5 text-xs">
                      {buildAssetKindLabel(asset.kind)}
                    </span>{" "}
                    {asset.label || <span className="text-muted">(라벨 없음)</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-attention">목록을 불러오지 못했습니다.</p>
            )}
          </section>
        </>
      )}
    </main>
  );
}
