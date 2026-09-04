"use client";

// 제출 폼 (FE-10, #35, ADR-0014). Laurio에서 가장 고유한 화면이다.
//
// 지켜야 할 비대칭: 소스코드는 필수(플랫폼의 "강제하지 않고 배지로 신호한다"
// 원칙의 유일한 예외 — ADR-0014)이고, 시연 영상·데모 URL·테스트 계정은 비워도
// 제출이 성공한다. 이 파일에서 그 둘을 같은 방식으로 다루면 안 된다.
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { UploadField } from "@/components/upload/upload-field";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
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

import { RequirementField, type RequirementFieldState } from "./requirement-field";

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

  const [sourceObjectKey, setSourceObjectKey] = useState("");
  const [demoVideoObjectKey, setDemoVideoObjectKey] = useState("");
  const [demoUrl, setDemoUrl] = useState("");
  const [testAccount, setTestAccount] = useState("");
  const [requirementStates, setRequirementStates] = useState<
    Record<number, RequirementFieldState>
  >({});
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const portOneConfig = useMemo(() => getPortOneBrowserConfig(), []);

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

      setSourceObjectKey(submission?.source_object_key ?? "");
      setDemoVideoObjectKey(submission?.demo_video_object_key ?? "");
      setDemoUrl(submission?.demo_url ?? "");
      setTestAccount(submission?.test_account ?? "");

      const initialStates: Record<number, RequirementFieldState> = {};
      for (const requirement of contest.data.requirements) {
        const existing = submission?.requirement_responses.find(
          (r) => r.requirement_id === requirement.id,
        );
        initialStates[requirement.id] = {
          isMet: existing?.is_met ?? false,
          note: existing?.note ?? "",
          evidence: existing?.evidence.map((e) => ({ kind: e.kind, value: e.value })) ?? [],
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
    const optionalSignals = [
      Boolean(demoVideoObjectKey),
      Boolean(demoUrl.trim()),
      Boolean(testAccount.trim()),
    ];
    const optionalRatio = optionalSignals.filter(Boolean).length / optionalSignals.length;
    const percent = Math.round((checklistRatio * 0.7 + optionalRatio * 0.3) * 100);
    return { percent, linked, total, optionalFilled: optionalSignals.filter(Boolean).length };
  }, [requirements, requirementStates, demoVideoObjectKey, demoUrl, testAccount]);

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
    if (!sourceObjectKey.trim()) {
      setSaveState({ status: "error", message: "소스코드를 먼저 업로드해주세요." });
      return;
    }

    setSaveState({ status: "saving" });
    const payload: SubmissionIn = {
      source_object_key: sourceObjectKey,
      demo_video_object_key: demoVideoObjectKey || null,
      demo_url: demoUrl || null,
      test_account: testAccount || null,
      requirement_responses: load.contest.requirements.map((r) => ({
        requirement_id: r.id,
        is_met: requirementStates[r.id]?.isMet ?? false,
        note: requirementStates[r.id]?.note ?? "",
        evidence: requirementStates[r.id]?.evidence ?? [],
      })),
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

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">소스코드 (필수)</h2>
        <p className="text-sm text-ink" data-testid="source-privacy-notice">
          제출한 소스코드는 선정(Award) 전까지 Sponsor에게 공개되지 않습니다. AI 채점과
          플랫폼만 열람합니다.
        </p>
        {sourceTargetRef && (
          <UploadField
            targetRef={sourceTargetRef}
            label="전체 소스코드 업로드"
            testId="source-upload"
            onUploaded={setSourceObjectKey}
          />
        )}
        {sourceObjectKey && (
          <p className="font-mono text-sm text-verified" data-testid="source-uploaded-key">
            업로드됨: {sourceObjectKey}
          </p>
        )}
        {!sourceObjectKey && (
          <p className="text-sm text-attention" data-testid="source-missing-warning">
            소스코드가 아직 없습니다 — 없으면 제출이 거부됩니다.
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">권장 항목 (비워도 제출됩니다)</h2>
        {demoVideoTargetRef && (
          <UploadField
            targetRef={demoVideoTargetRef}
            label="시연 영상"
            testId="demo-video-upload"
            onUploaded={setDemoVideoObjectKey}
          />
        )}
        <label className="flex flex-col gap-1 text-sm">
          데모 URL
          <input
            className="rounded-sm border border-rule bg-paper px-2 py-1"
            value={demoUrl}
            disabled={isPastDeadline}
            onChange={(event) => setDemoUrl(event.target.value)}
            data-testid="demo-url-input"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          테스트 계정
          <input
            className="rounded-sm border border-rule bg-paper px-2 py-1"
            value={testAccount}
            disabled={isPastDeadline}
            onChange={(event) => setTestAccount(event.target.value)}
            data-testid="test-account-input"
          />
        </label>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">요구사항 체크리스트</h2>
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
        </div>
      )}
    </main>
  );
}
