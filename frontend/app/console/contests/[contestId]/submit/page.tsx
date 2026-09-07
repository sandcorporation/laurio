"use client";

// 제출 폼 (FE-10, #35, ADR-0014). Laurio에서 가장 고유한 화면이다.
//
// 지켜야 할 비대칭: 소스코드는 필수(플랫폼의 "강제하지 않고 배지로 신호한다"
// 원칙의 유일한 예외 — ADR-0014)이고, 시연 영상·데모 URL·테스트 계정은 비워도
// 제출이 성공한다. 이 파일에서 그 둘을 같은 방식으로 다루면 안 된다.
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import { ASSET_KIND_LABELS } from "@/lib/submissions/types";
import type {
  ContestDetail,
  SubmissionIn,
  SubmissionOut,
  VerificationStatusOut,
} from "@/lib/submissions/types";

import {
  clearRedirectVerificationParams,
  getPortOneBrowserConfig,
  peekRedirectVerificationResult,
  requestPortOneIdentityVerification,
} from "@/lib/verification/portone";

import { AssetKindSection, createEmptyAsset, type EditableAsset } from "./asset-kind-section";
import { RequirementField, type RequirementFieldState } from "./requirement-field";

// #190 이후 제출작은 자료 목록을 담는다(ADR-0027) — 종류는 넷: 전체 소스코드
// (필수, 최소 1개), 시연 영상·데모 URL(권장), GitHub 저장소(권장, 공개
// 저장소는 채점에 반영된다). `EditableAsset[]`을 종류별로 따로 두는 이유는
// 종류마다 값 편집 UI(업로드 vs URL 텍스트)와 허용되는 부가 필드(테스트
// 계정은 demo_url뿐)가 달라서다.
const KNOWN_ASSET_KINDS = new Set(["source", "demo_video", "demo_url", "repository"]);

function assetsOfKind(assets: SubmissionOut["assets"], kind: string): EditableAsset[] {
  return assets
    .filter((asset) => asset.kind === kind)
    .map((asset) => ({
      key: `existing-${asset.id}`,
      id: asset.id,
      value: asset.value,
      label: asset.label,
      testAccount: asset.test_account,
      isPublic: asset.is_public,
    }));
}

// 이 폼이 모르는 종류의 자료를 위한 통과 버킷 — #190의 `untouchedAssets`가
// 하던 일과 같다. 오늘 `KNOWN_ASSET_KINDS`는 `SubmissionAsset.Kind` 전부라
// 항상 빈 배열이지만, 없애면 서버에 다섯 번째 종류가 생기고 이 폼이 함께
// 못 고쳐졌을 때 `_merge_assets`가 그 자료를 "페이로드에 없음"으로 보고
// 지운다 — 그 자료를 가리키던 Evidence까지 CASCADE로 함께 사라진다. 손대지
// 않고 그대로 되돌려 보내면 그 사고를 막는다.
function unknownKindAssetsOf(assets: SubmissionOut["assets"]): SubmissionOut["assets"] {
  return assets.filter((asset) => !KNOWN_ASSET_KINDS.has(asset.kind));
}

// 종류 하나의 편집 행을 저장 페이로드로 접는다. 값이 빈 행(추가만 하고
// 채우지 않은 행)은 조용히 뺀다 — 서버는 빈 값을 422로 거절하는데, 그냥
// 빈 채로 둔 행까지 실패로 만들 이유가 없다. `order`는 화면에 보이는
// 순서(위/아래로 버튼이 바꾼 순서) 그대로 인덱스로 다시 매긴다.
//
// **모듈 스코프에 둔다** — 컴포넌트 상태에 기대지 않는 순수 함수라, 저장
// 시점(handleSubmit)과 완성도 계산(completion useMemo) 둘 다 이 함수를
// 불러써야 "실제로 보낼 자산"과 "화면이 채워졌다고 말하는 것"이 갈리지
// 않는다 — 갈리면 참가자가 테스트 계정만 채우고 데모 URL을 비웠을 때
// 화면은 "채워졌다"고 말하지만 저장은 그 행을 통째로 버리는 사고가 난다.
function rowsToAssetsIn(rows: EditableAsset[], kind: string): SubmissionIn["assets"] {
  return rows
    .filter((row) => row.value.trim() !== "")
    .map((row, index) => ({
      ...(row.id != null ? { id: row.id } : {}),
      kind,
      value: row.value.trim(),
      label: row.label.trim(),
      test_account: kind === "demo_url" ? row.testAccount.trim() : "",
      order: index,
    }));
}

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      contest: ContestDetail;
      verification: VerificationStatusOut;
      submission: SubmissionOut | null;
    };

type SaveState = { status: "idle" | "saving" | "done" | "error"; message?: string };

function formatRemaining(ms: number): string {
  if (ms <= 0) return "마감";
  const totalSeconds = Math.floor(ms / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `D-${days} (${hours}시간 ${minutes}분 남음)`;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)} 남음`;
}

export default function SubmitPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [reloadTick, setReloadTick] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const [sourceAssets, setSourceAssets] = useState<EditableAsset[]>([createEmptyAsset()]);
  const [demoVideoAssets, setDemoVideoAssets] = useState<EditableAsset[]>([]);
  const [demoUrlAssets, setDemoUrlAssets] = useState<EditableAsset[]>([]);
  const [repositoryAssets, setRepositoryAssets] = useState<EditableAsset[]>([]);
  // 이 폼이 편집하지 않는(모르는) 종류의 자료 — 통과 버킷. 오늘은 항상
  // 빈 배열이지만 없애면 다섯 번째 종류가 생겼을 때 조용히 삭제된다(위
  // `unknownKindAssetsOf` 주석).
  const [unknownKindAssets, setUnknownKindAssets] = useState<SubmissionOut["assets"]>([]);
  const [requirementStates, setRequirementStates] = useState<
    Record<number, RequirementFieldState>
  >({});
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  // 직전 저장에서 서버가 연결을 푼 근거 수 (#195) — 자료를 지우면 그것을 가리키던
  // 근거의 연결이 함께 풀린다는 것을 참가자에게 알린다.
  const [unlinkedEvidenceCount, setUnlinkedEvidenceCount] = useState(0);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const portOneConfig = useMemo(() => getPortOneBrowserConfig(), []);

  // 로드 직후와 저장 성공 직후 둘 다 이 함수를 부른다 — **서버 응답이 이
  // 화면의 자료 id에 대한 유일한 출처다.** 저장 직후에도 다시 부르지 않으면
  // 방금 새로 만든 자료의 id를 이 화면이 계속 모른 채로 남아, 다음에 그 자료를
  // 근거로 고르는 드롭다운이 그것을 선택지로 내놓지 못한다.
  function applySubmissionAssets(submission: SubmissionOut | null) {
    const assets = submission?.assets ?? [];
    const nextSourceAssets = assetsOfKind(assets, "source");
    setSourceAssets(nextSourceAssets.length > 0 ? nextSourceAssets : [createEmptyAsset()]);
    setDemoVideoAssets(assetsOfKind(assets, "demo_video"));
    setDemoUrlAssets(assetsOfKind(assets, "demo_url"));
    setRepositoryAssets(assetsOfKind(assets, "repository"));
    setUnknownKindAssets(unknownKindAssetsOf(assets));
  }

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    async function loadAll() {
      const [contest, verification] = await Promise.all([
        bffClient.get<ContestDetail>(`/api/backend/contests/${contestId}`),
        bffClient.get<VerificationStatusOut>("/api/backend/verification/me"),
      ]);
      if (cancelled) return;

      if (!contest.ok) {
        if (contest.status === 404) return setLoad({ status: "not-found" });
        return setLoad({ status: "error", message: "Contest 정보를 불러오지 못했습니다." });
      }
      if (!verification.ok) {
        return setLoad({ status: "error", message: "본인확인 상태를 확인하지 못했습니다." });
      }

      let submission: SubmissionOut | null = null;
      if (verification.data.status === "verified") {
        // 404 는 실패가 아니다 — 「아직 안 냈다」는 정상적인 사실이다.
        const existing = await bffClient.get<SubmissionOut>(
          `/api/backend/contests/${contestId}/submissions/me`,
        );
        if (cancelled) return;
        if (existing.ok) {
          submission = existing.data;
        } else if (existing.status !== 404) {
          return setLoad({ status: "error", message: "제출 정보를 불러오지 못했습니다." });
        }
      }

      if (cancelled) return;

      applySubmissionAssets(submission);

      const initialStates: Record<number, RequirementFieldState> = {};
      for (const requirement of contest.data.requirements) {
        const existing = submission?.requirement_responses.find(
          (r) => r.requirement_id === requirement.id,
        );
        initialStates[requirement.id] = {
          isMet: existing?.is_met ?? false,
          note: existing?.note ?? "",
          evidence:
            existing?.evidence.map((e) => ({
              kind: e.kind,
              value: e.value,
              asset_id: e.asset_id ?? null,
            })) ?? [],
        };
      }
      setRequirementStates(initialStates);
      setLoad({ status: "ready", contest: contest.data, verification: verification.data, submission });
    }

    loadAll().catch(() => {
      if (!cancelled) setLoad({ status: "error", message: "불러오는 중 오류가 발생했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, contestId, reloadTick]);

  const deadlineAt = load.status === "ready" ? new Date(load.contest.deadline_at).getTime() : null;
  const isPastDeadline = deadlineAt !== null && now >= deadlineAt;

  const requirements = load.status === "ready" ? load.contest.requirements : [];
  const completion = useMemo(() => {
    const total = requirements.length;
    const linked = requirements.filter(
      (r) => (requirementStates[r.id]?.evidence.length ?? 0) > 0,
    ).length;
    const checklistRatio = total > 0 ? linked / total : 1;
    // `rowsToAssetsIn`으로 계산한다 — 값이 빈 행(예: 데모 URL은 비우고
    // 테스트 계정만 채운 행)은 저장 시 통째로 버려지므로, 완성도가 "채워짐"
    // 이라 말하면서 저장은 그 행을 버리는 모순을 막는다.
    const demoVideoToSave = rowsToAssetsIn(demoVideoAssets, "demo_video");
    const demoUrlToSave = rowsToAssetsIn(demoUrlAssets, "demo_url");
    const optionalSignals = [
      demoVideoToSave.length > 0,
      demoUrlToSave.length > 0,
      demoUrlToSave.some((a) => a.test_account.trim() !== ""),
    ];
    const optionalRatio = optionalSignals.filter(Boolean).length / optionalSignals.length;
    const percent = Math.round((checklistRatio * 0.7 + optionalRatio * 0.3) * 100);
    return { percent, linked, total, optionalFilled: optionalSignals.filter(Boolean).length };
  }, [requirements, requirementStates, demoVideoAssets, demoUrlAssets]);

  async function handleVerifyDev() {
    if (session.status !== "authenticated") return;
    setVerifying(true);
    try {
      const seed = session.user.username;
      const result = await bffClient.post("/api/backend/verification/verify", {
        verification_token: `${seed}|1990-01-01|ci-${seed}|di-${seed}`,
      });
      if (result.ok) setReloadTick((t) => t + 1);
    } finally {
      setVerifying(false);
    }
  }

  // 서버에 확정 요청을 보낸 결과 — recoverable=true는 우리 서버에 요청 자체가
  // 닿지 않은 네트워크 수준 실패다(#85 코드리뷰 지적 2). 이 경우 벤더 쪽에서는
  // 본인확인이 이미 끝났을 수 있으므로, 호출부가 identityVerificationId를 URL
  // (또는 재시도 경로)에 그대로 남겨 다시 시도할 수 있게 해야 한다 — 반대로
  // recoverable=false(서버가 확정된 응답을 줬다 — 성공이든 4xx든)는 그
  // identityVerificationId의 운명이 이미 정해졌으므로 지워도 안전하다.
  type FinalizeOutcome = { ok: true } | { ok: false; recoverable: boolean; message: string };

  async function finalizeLiveVerification(identityVerificationId: string): Promise<FinalizeOutcome> {
    const result = await bffClient.post("/api/backend/verification/verify", {
      verification_token: identityVerificationId,
    });

    if (result.ok) {
      setReloadTick((t) => t + 1);
      return { ok: true };
    }
    if (result.code === "network") {
      return {
        ok: false,
        recoverable: true,
        message:
          "본인확인 결과를 서버에 전달하지 못했습니다. 네트워크를 확인한 뒤 페이지를 " +
          "새로고침해 다시 시도해 주세요.",
      };
    }
    return { ok: false, recoverable: false, message: result.detail };
  }

  async function handleVerifyLive() {
    if (session.status !== "authenticated") return;
    const config = portOneConfig;
    if (!config) return;
    setVerifying(true);
    setVerifyError(null);
    try {
      const identityVerificationId = await requestPortOneIdentityVerification(config);
      const outcome = await finalizeLiveVerification(identityVerificationId);
      if (!outcome.ok) setVerifyError(outcome.message);
    } catch (err) {
      setVerifyError(err instanceof Error ? err.message : "본인확인에 실패했습니다.");
    } finally {
      setVerifying(false);
    }
  }

  // 모바일에서는 PortOne 인증창이 팝업이 아니라 전체 페이지 리다이렉트로 열려
  // handleVerifyLive의 Promise가 resolve되지 않는다(#85 코드리뷰 지적 3) — 이
  // 화면이 리다이렉트로 돌아왔는지를 마운트 시점에 별도로 확인해야 한다.
  //
  // URL은 `peekRedirectVerificationResult`로 읽기만 하고, 서버 확정 요청이
  // 실제로 끝난(recoverable=false가 된) 뒤에만 `clearRedirectVerificationParams`
  // 를 부른다(#85 코드리뷰 지적 2) — 그 전에 지우면 확정 요청이 일시적으로
  // 실패했을 때 재시도할 identityVerificationId 자체를 잃는다.
  useEffect(() => {
    if (session.status !== "authenticated") return;
    const redirectResult = peekRedirectVerificationResult();
    if (redirectResult === null) return;

    if (redirectResult.status === "failure") {
      // 벤더 쪽에서 이미 실패로 끝난 시도다 — 재시도할 여지가 없으므로 곧장
      // 지운다.
      clearRedirectVerificationParams();
      setVerifyError(redirectResult.message);
      return;
    }

    let cancelled = false;
    setVerifying(true);
    finalizeLiveVerification(redirectResult.identityVerificationId)
      .then((outcome) => {
        if (cancelled) return;
        if (outcome.ok || !outcome.recoverable) {
          clearRedirectVerificationParams();
        }
        if (!outcome.ok) setVerifyError(outcome.message);
      })
      .finally(() => {
        if (!cancelled) setVerifying(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 마운트 시점 1회만 확인한다.
  }, [session.status]);

  async function handleSubmit() {
    if (load.status !== "ready") return;
    const hasSource = sourceAssets.some((row) => row.value.trim() !== "");
    if (!hasSource) {
      setSaveState({ status: "error", message: "소스코드를 먼저 업로드해주세요." });
      return;
    }

    setSaveState({ status: "saving" });
    // 직전 저장의 알림은 여기서 지운다 — 안 그러면 이번 저장이 아무 것도 풀지
    // 않았는데도 옛 문구가 그대로 남는다.
    setUnlinkedEvidenceCount(0);

    const assets: SubmissionIn["assets"] = [
      ...rowsToAssetsIn(sourceAssets, "source"),
      ...rowsToAssetsIn(demoVideoAssets, "demo_video"),
      ...rowsToAssetsIn(demoUrlAssets, "demo_url"),
      ...rowsToAssetsIn(repositoryAssets, "repository"),
      // 이 폼이 모르는 종류의 자료도 그대로 되돌려 보낸다 — 손대지 않고
      // 지나가는 것 자체가 이 배열이 하는 일의 전부다.
      ...unknownKindAssets.map((asset) => ({
        id: asset.id,
        kind: asset.kind,
        value: asset.value,
        label: asset.label,
        test_account: asset.test_account,
        order: asset.order,
      })),
    ];

    // **근거의 asset_id는 손대지 않고 그대로 보낸다**(#195). 예전에는 여기서
    // `_merge_assets`의 `(kind, value)` 정체성 규칙을 클라이언트에서 다시 구현해,
    // 이번 저장으로 사라질 자료를 가리키는 연결을 미리 풀어 보냈다 — 안 그러면
    // 백엔드가 422를 냈기 때문이다.
    //
    // **그 미러링이 두 번 틀렸다**(#192): 처음엔 값만 비교했고(서버는 kind도 본다),
    // 고친 뒤엔 id로 판정했다(서버는 id 없는 행도 정체성으로 맞춰 원래 id를 살린다).
    // 서버 규칙이 바뀔 때마다 조용히 어긋나는 구조였다.
    //
    // 이제 서버가 판정한다 — 병합 뒤의 자산을 이미 아는 쪽이 그 일을 한다. 이번
    // 요청이 지운 자료를 가리킨 근거는 서버가 연결만 풀어 돌려주고, **남의 자료
    // id는 여전히 422다**(#190의 방어는 그대로다).

    const payload: SubmissionIn = {
      assets,
      requirement_responses: load.contest.requirements.map((r) => {
        const state = requirementStates[r.id];
        return {
          requirement_id: r.id,
          is_met: state?.isMet ?? false,
          note: state?.note ?? "",
          evidence: (state?.evidence ?? []).map((e) => ({
            kind: e.kind,
            value: e.value,
            asset_id: e.asset_id,
          })),
        };
      }),
    };

    const isUpdate = load.submission !== null;
    const path = isUpdate
      ? `/api/backend/contests/${contestId}/submissions/me`
      : `/api/backend/contests/${contestId}/submissions`;

    const saved = await bffClient.request<SubmissionOut>(path, {
      method: isUpdate ? "PUT" : "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!saved.ok) {
      setSaveState({ status: "error", message: saved.detail });
      return;
    }

    const submission = saved.data;
    setLoad((prev) => (prev.status === "ready" ? { ...prev, submission } : prev));
    applySubmissionAssets(submission);

    // **보낸 것과 돌아온 것을 견준다**(#195). 서버가 사라진 자료를 가리키던 근거의
    // 연결을 풀었다면 응답의 `asset_id`가 null로 온다. 이건 서버 규칙을 흉내 내는
    // 것이 아니라 **서버의 답을 읽는 것**이라, 그 규칙이 바뀌어도 어긋나지 않는다.
    //
    // **순서에 기대지 않는다**(#195 리뷰). 처음엔 (requirement_id, 인덱스)로 짝지었는데
    // 그건 두 곳에서 깨진다: 응답의 근거 순서가 보장되지 않았고(그건 별도로 `Evidence`에
    // `ordering`을 줘서 고쳤다), 저장이 도는 동안 사용자가 근거를 지우면 나중에 도는
    // 업데이터의 `prev`가 보낸 것과 어긋나 **남의 근거에 남의 자료 id를 덮어쓴다.**
    // 그래서 세는 것은 개수 차이로, 정리하는 것은 "응답에 없는 id"로 한다 — 둘 다
    // 순서와 무관하다.
    //
    // 세는 값은 클로저의 `requirementStates`(=방금 보낸 것)와 응답을 비교한 것이라
    // 저장 중 편집의 영향을 받지 않는다.
    const linkedCount = (evidences: { asset_id?: number | null }[]) =>
      evidences.filter((e) => e.asset_id != null).length;
    const sentLinked = Object.values(requirementStates).reduce(
      (n, state) => n + linkedCount(state.evidence),
      0,
    );
    const savedLinked = submission.requirement_responses.reduce(
      (n, response) => n + linkedCount(response.evidence),
      0,
    );
    setUnlinkedEvidenceCount(Math.max(sentLinked - savedLinked, 0));

    // 응답에 없는 자료를 가리키는 연결만 푼다 — 위치가 아니라 id로 판정하므로
    // 저장 중에 근거가 늘거나 줄어도 엉뚱한 행을 건드리지 않는다.
    const savedAssetIds = new Set(submission.assets.map((a) => a.id));
    setRequirementStates((prev) => {
      const next: Record<number, RequirementFieldState> = {};
      for (const [key, state] of Object.entries(prev)) {
        next[Number(key)] = {
          ...state,
          evidence: state.evidence.map((e) =>
            e.asset_id != null && !savedAssetIds.has(e.asset_id) ? { ...e, asset_id: null } : e,
          ),
        };
      }
      return next;
    });

    setSaveState({ status: "done" });
  }

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="submit-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "not-found") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="submit-not-found">Contest를 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (load.status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="submit-load-error">
          {load.message}
        </p>
      </main>
    );
  }

  const { contest, verification, submission } = load;

  if (verification.status !== "verified") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-10">
        <p role="alert" data-testid="verification-required" className="text-attention">
          본인확인(Verification)을 완료해야 제출할 수 있습니다.
        </p>
        <p className="text-sm text-ink" data-testid="verification-reason">
          {verification.status === "underage"
            ? verification.reason || "만 19세 미만은 본인확인을 완료할 수 없습니다."
            : "휴대폰 본인확인을 먼저 마쳐주세요."}
        </p>
        {verification.status !== "underage" && (
          <button
            type="button"
            onClick={handleVerifyDev}
            disabled={verifying}
            data-testid="verify-now-dev"
            className="rounded-sm border border-rule px-4 py-2 text-sm hover:border-ink disabled:opacity-50"
          >
            {verifying ? "확인 중..." : "지금 본인확인하기(dev)"}
          </button>
        )}
        {verification.status !== "underage" && portOneConfig && (
          <button
            type="button"
            onClick={handleVerifyLive}
            disabled={verifying}
            data-testid="verify-now-live"
            className="rounded-sm border border-rule px-4 py-2 text-sm hover:border-ink disabled:opacity-50"
          >
            {verifying ? "확인 중..." : "실제 본인확인하기(PortOne)"}
          </button>
        )}
        {verifyError && (
          <p role="alert" data-testid="verify-live-error" className="text-sm text-attention">
            {verifyError}
          </p>
        )}
      </main>
    );
  }

  const userId = session.status === "authenticated" ? session.user.id : null;
  const sourceTargetRef = userId ? `submission:${contestId}:${userId}:source` : null;
  const demoVideoTargetRef = userId ? `submission:${contestId}:${userId}:demo-video` : null;

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 p-10">
      <div>
        <h1 className="text-2xl font-semibold" data-testid="submit-contest-title">
          {contest.title} — 제출
        </h1>
        <p
          className={`mt-2 font-mono text-sm ${isPastDeadline ? "text-attention" : "text-ink"}`}
          data-testid="submit-deadline"
        >
          {isPastDeadline ? "마감되었습니다" : formatRemaining(deadlineAt! - now)}
        </p>
      </div>

      {isPastDeadline && (
        <p role="alert" data-testid="deadline-passed-notice" className="text-sm text-attention">
          마감 시각이 지나 더 이상 제출하거나 수정할 수 없습니다.
        </p>
      )}

      <section className="flex flex-col gap-2" data-testid="completion-indicator" data-percent={completion.percent}>
        <p className="text-sm">
          완성도 {completion.percent}% — 체크리스트 증거 연결 {completion.linked}/{completion.total},
          권장 항목 {completion.optionalFilled}/3
        </p>
        <div className="h-2 w-full rounded-sm border border-rule">
          <div className="h-full bg-verified" style={{ width: `${completion.percent}%` }} />
        </div>
      </section>

      <p className="text-sm text-ink" data-testid="source-privacy-notice">
        제출한 소스코드와 GitHub 저장소는 선정(Award) 전까지 Sponsor에게 공개되지 않습니다.
        AI 채점과 플랫폼만 열람합니다.
      </p>

      <AssetKindSection
        kind="source"
        title={ASSET_KIND_LABELS.source}
        required
        addLabel="+ 소스코드 추가"
        testIdPrefix="source-asset"
        rows={sourceAssets}
        onChange={setSourceAssets}
        disabled={isPastDeadline}
        targetRefPrefix={sourceTargetRef ?? undefined}
      />

      <AssetKindSection
        kind="repository"
        title={ASSET_KIND_LABELS.repository}
        helperText={
          <p className="text-sm text-ink/70" data-testid="repository-helper">
            공개 저장소는 마감 전 자동으로 확인되어 채점에 반영됩니다(비워도 제출됩니다).
            저장소는 소스 제출을 대체하지 않습니다 — 소스코드는 그래도 필수입니다.
          </p>
        }
        addLabel="+ 저장소 추가"
        testIdPrefix="repository-asset"
        rows={repositoryAssets}
        onChange={setRepositoryAssets}
        disabled={isPastDeadline}
      />

      <AssetKindSection
        kind="demo_video"
        title={ASSET_KIND_LABELS.demo_video}
        addLabel="+ 시연 영상 추가"
        testIdPrefix="demo-video-asset"
        rows={demoVideoAssets}
        onChange={setDemoVideoAssets}
        disabled={isPastDeadline}
        targetRefPrefix={demoVideoTargetRef ?? undefined}
      />

      <AssetKindSection
        kind="demo_url"
        title={ASSET_KIND_LABELS.demo_url}
        addLabel="+ 데모 URL 추가"
        testIdPrefix="demo-url-asset"
        rows={demoUrlAssets}
        onChange={setDemoUrlAssets}
        disabled={isPastDeadline}
      />

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">요구사항 체크리스트</h2>
        <p className="text-xs text-ink/60" data-testid="evidence-asset-picker-notice">
          근거가 가리킬 수 있는 자료 목록은 마지막으로 저장된 자료 기준입니다 — 방금
          추가한 자료는 한 번 저장한 뒤에 근거로 연결할 수 있습니다.
        </p>
        {contest.requirements.map((requirement) => (
          <RequirementField
            key={requirement.id}
            requirement={requirement}
            state={
              requirementStates[requirement.id] ?? { isMet: false, note: "", evidence: [] }
            }
            onChange={(next) =>
              setRequirementStates((prev) => ({ ...prev, [requirement.id]: next }))
            }
            disabled={isPastDeadline}
            testId={`requirement-${requirement.id}`}
            assets={submission?.assets ?? []}
          />
        ))}
      </section>

      {!isPastDeadline && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saveState.status === "saving"}
            data-testid="submit-button"
            className="w-fit rounded-sm border border-ink bg-ink px-6 py-2 text-sm text-paper disabled:opacity-50"
          >
            {saveState.status === "saving"
              ? "저장 중..."
              : submission
                ? "수정 사항 저장"
                : "제출하기"}
          </button>
          {saveState.status === "error" && (
            <p role="alert" data-testid="submit-error" className="text-sm text-attention">
              {saveState.message}
            </p>
          )}
          {saveState.status === "done" && (
            <p data-testid="submit-success" className="text-sm text-verified">
              저장되었습니다. 마감 전까지 몇 번이든 다시 수정할 수 있습니다.
            </p>
          )}
          {/* 자료를 지우면 그것을 가리키던 근거의 연결이 함께 풀린다(#195) —
              말해주지 않으면 참가자는 다음에 화면을 열어서야 안다. 근거 자체는
              남으므로 경고(attention)가 아니라 알림이다. */}
          {saveState.status === "done" && unlinkedEvidenceCount > 0 && (
            <p data-testid="evidence-unlinked-notice" className="text-sm text-ink/70">
              지운 자료를 가리키던 증거 {unlinkedEvidenceCount}건의 연결이 해제되었습니다.
              증거 자체는 그대로 남아 있으니 다른 자료에 다시 연결할 수 있습니다.
            </p>
          )}
        </div>
      )}
    </main>
  );
}
