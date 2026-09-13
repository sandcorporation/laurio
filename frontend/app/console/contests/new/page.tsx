"use client";

// AI grill 개최 — 브리프 (FE-12, #37, spec #25 User Story 40-48, design/Brief.dc.html).
// 초안이 자기 자리를 갖게 되면서(#111, 부모 #110) 이 화면은 **Phase A(브리프)
// 까지만** 맡는다 — 아직 Contest가 없는 상태에서 제목·카테고리·요구형태·상금·
// 마감을 받는다. 요구형태를 고를 때마다 최소 제안 상금 합계를 POST
// /contests/quote로 실시간으로 보여준다(직접 합산하지 않는다 — 규칙이 두 곳에서
// 어긋나면 안 된다).
//
// 제출하면 그 순간 Contest가 draft로 생성되고(POST /api/contests,
// requirements=[]), 화면은 그 Contest의 URL —
// `/console/contests/{contestId}/draft` — 로 넘어간다. AI grill 대화·
// Requirement CRUD는 전부 그 화면의 몫이다: 초안이 URL을 가지므로 새로고침·
// 북마크·목록 진입이 전부 그 화면에서 이어진다(이 화면 자체는 다시 방문해도
// 항상 빈 브리프 폼이다 — 그것이 맞다, 브리프는 Contest 생성 전 단계다).
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorNote, INPUT_CLASS, PageShell, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import { formatPrize } from "@/lib/contest-format";
import type { Category, DeliverableType, VerificationStatusOut } from "@/lib/contests/grill-types";

import {
  clearRedirectVerificationParams,
  getPortOneBrowserConfig,
  peekRedirectVerificationResult,
  requestPortOneIdentityVerification,
} from "@/lib/verification/portone";

import { ContestStageStepper } from "../_components/contest-stage-stepper";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      categories: Category[];
      deliverableTypes: DeliverableType[];
      verification: VerificationStatusOut;
    };

type BriefForm = {
  title: string;
  categoryId: number | "";
  deliverableTypeIds: number[];
  prize: string;
  deadlineAt: string;
  description: string;
};

const EMPTY_BRIEF: BriefForm = {
  title: "",
  categoryId: "",
  deliverableTypeIds: [],
  prize: "",
  deadlineAt: "",
  description: "",
};

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function NewContestGrillPage() {
  const session = useSession();
  const router = useRouter();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [reloadTick, setReloadTick] = useState(0);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const portOneConfig = useMemo(() => getPortOneBrowserConfig(), []);

  const [brief, setBrief] = useState<BriefForm>(EMPTY_BRIEF);
  const [quoteTotal, setQuoteTotal] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    async function loadAll() {
      const [categories, deliverableTypes, verification] = await Promise.all([
        bffClient.get<unknown>("/api/backend/contests/categories"),
        bffClient.get<unknown>("/api/backend/contests/deliverable-types"),
        bffClient.get<unknown>("/api/backend/verification/me"),
      ]);
      if (cancelled) return;

      if (!categories.ok || !deliverableTypes.ok || !verification.ok) {
        setLoad({ status: "error", message: "화면을 불러오지 못했습니다." });
        return;
      }
      // 응답 모양을 여기서 한 번 더 본다 — 프록시가 다른 것을 돌려줘도 화면이 빈 목록을
      // 그럴듯하게 그리지 않는다.
      if (
        !Array.isArray(categories.data) ||
        !Array.isArray(deliverableTypes.data) ||
        !isPlainRecord(verification.data)
      ) {
        setLoad({ status: "error", message: "화면을 불러오지 못했습니다." });
        return;
      }

      setLoad({
        status: "ready",
        categories: categories.data,
        deliverableTypes: deliverableTypes.data,
        verification: verification.data as unknown as VerificationStatusOut,
      });
    }

    loadAll().catch(() => {
      if (!cancelled) setLoad({ status: "error", message: "불러오는 중 오류가 발생했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, reloadTick]);

  // 요구형태 선택이 바뀔 때마다 최소 제안 상금 합계를 서버에서 다시 받는다 —
  // DeliverableType.minimum_prize를 프론트가 직접 합산하지 않는다(REQUEST.md,
  // #37 인수조건: "규칙이 두 곳에서 어긋나면 안 된다").
  const deliverableTypeKey = brief.deliverableTypeIds.slice().sort((a, b) => a - b).join(",");
  useEffect(() => {
    if (brief.deliverableTypeIds.length === 0) {
      setQuoteTotal(0);
      return;
    }
    let cancelled = false;
    void bffClient
      .post<unknown>("/api/backend/contests/quote", {
        deliverable_type_ids: brief.deliverableTypeIds,
      })
      .then((result) => {
        if (cancelled) return;
        if (result.ok && isPlainRecord(result.data) && typeof result.data.minimum_total === "number") {
          setQuoteTotal(result.data.minimum_total);
          return;
        }
        setQuoteTotal(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliverableTypeKey가 배열 내용의 안정된 대리 키다.
  }, [deliverableTypeKey]);

  const prizeNumber = Number(brief.prize);
  const previewUnderfunded =
    quoteTotal !== null && quoteTotal > 0 && Number.isFinite(prizeNumber) && prizeNumber < quoteTotal;

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

  function toggleDeliverableType(id: number) {
    setBrief((prev) => ({
      ...prev,
      deliverableTypeIds: prev.deliverableTypeIds.includes(id)
        ? prev.deliverableTypeIds.filter((x) => x !== id)
        : [...prev.deliverableTypeIds, id],
    }));
  }

  async function handleCreateDraft() {
    setCreateError(null);

    const title = brief.title.trim();
    if (!title) {
      setCreateError("제목을 입력해주세요.");
      return;
    }
    if (brief.categoryId === "") {
      setCreateError("카테고리를 선택해주세요.");
      return;
    }
    if (brief.deliverableTypeIds.length === 0) {
      setCreateError("요구형태를 하나 이상 선택해주세요.");
      return;
    }
    if (!Number.isFinite(prizeNumber) || prizeNumber <= 0) {
      setCreateError("상금은 0보다 큰 금액이어야 합니다.");
      return;
    }
    if (!brief.deadlineAt) {
      setCreateError("마감 기한을 선택해주세요.");
      return;
    }

    setCreating(true);
    try {
      const created = await bffClient.post<unknown>("/api/backend/contests", {
        title,
        category_id: brief.categoryId,
        deliverable_type_ids: brief.deliverableTypeIds,
        description: brief.description,
        prize: prizeNumber,
        deadline_at: new Date(brief.deadlineAt).toISOString(),
        requirements: [],
      });

      if (!created.ok) {
        setCreateError(created.detail);
        return;
      }
      if (!isPlainRecord(created.data) || typeof created.data.id !== "number") {
        setCreateError("초안 생성 응답을 해석하지 못했습니다. 다시 시도해 주세요.");
        return;
      }

      // 초안이 자기 URL을 갖는다(#111) — 여기서부터는 그 화면(요구사항 작성)이
      // 이어받는다. 새로고침·북마크·목록에서의 재진입이 전부 그 URL을 통해
      // 이뤄지므로, 이 화면(브리프)은 생성 후 상태를 들고 있지 않는다.
      router.push(`/console/contests/${created.data.id}/draft`);
    } catch {
      setCreateError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setCreating(false);
    }
  }

  if (session.status === "loading" || load.status === "loading") {
    return (
      <PageShell>
        <p data-testid="grill-loading">불러오는 중...</p>
      </PageShell>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="grill-load-error">{load.message}</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const { categories, deliverableTypes, verification } = load;

  if (verification.status !== "verified") {
    return (
      <PageShell>
        <div className="flex flex-col items-center gap-4">
          <ErrorNote>
            <span data-testid="grill-verification-required">
              본인확인을 완료해야 공모전을 개최할 수 있습니다.
            </span>
          </ErrorNote>
          <p className="text-sm text-ink" data-testid="grill-verification-reason">
            {verification.status === "underage"
              ? verification.reason || "만 19세 미만은 본인확인을 완료할 수 없습니다."
              : "휴대폰 본인확인을 먼저 마쳐주세요."}
          </p>
          {verification.status !== "underage" && (
            <button
              type="button"
              onClick={handleVerifyDev}
              disabled={verifying}
              data-testid="grill-verify-now-dev"
              className={buttonClass("secondary")}
            >
              {verifying ? "확인 중..." : "지금 본인확인하기(dev)"}
            </button>
          )}
          {verification.status !== "underage" && portOneConfig && (
            <button
              type="button"
              onClick={handleVerifyLive}
              disabled={verifying}
              data-testid="grill-verify-now-live"
              className={buttonClass("secondary")}
            >
              {verifying ? "확인 중..." : "실제 본인확인하기(PortOne)"}
            </button>
          )}
          {verifyError && (
            <ErrorNote>
              <span data-testid="grill-verify-live-error">{verifyError}</span>
            </ErrorNote>
          )}
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <ContestStageStepper current="brief" />
          <div>
            <p className="text-xs font-medium tracking-widest text-ink/60">공모전 개최</p>
            <h1 className="text-2xl font-semibold" data-testid="grill-brief-heading">
              기본 정보를 알려주세요
            </h1>
            <p className="mt-2 text-sm text-ink/70">
              다음 단계에서 AI와 대화하며 요구사항 체크리스트를 함께 만듭니다.
            </p>
          </div>
        </div>

        <label className="flex flex-col gap-1 text-sm">
          제목
          <input
            value={brief.title}
            onChange={(event) => setBrief((prev) => ({ ...prev, title: event.target.value }))}
            maxLength={200}
            data-testid="grill-brief-title"
            className={INPUT_CLASS}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          카테고리
          <select
            value={brief.categoryId}
            onChange={(event) =>
              setBrief((prev) => ({ ...prev, categoryId: event.target.value ? Number(event.target.value) : "" }))
            }
            data-testid="grill-brief-category"
            className={INPUT_CLASS}
          >
            <option value="">선택해주세요</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>

        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="mb-1">요구형태 · 복수 선택</legend>
          {deliverableTypes.map((dt) => (
            <label
              key={dt.id}
              className="flex items-center justify-between border border-rule px-3 py-2"
              data-testid={`grill-brief-deliverable-type-${dt.id}`}
            >
              <span className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={brief.deliverableTypeIds.includes(dt.id)}
                  onChange={() => toggleDeliverableType(dt.id)}
                  data-testid={`grill-brief-deliverable-type-${dt.id}-checkbox`}
                />
                {dt.name}
              </span>
              <span className="font-mono text-xs text-ink/60">{formatPrize(dt.minimum_prize)}</span>
            </label>
          ))}
          <div className="flex items-center justify-between border-t border-rule pt-2 text-xs">
            <span className="text-ink/60">최소 제안 상금 합계</span>
            <span className="font-mono font-semibold" data-testid="grill-brief-quote-total">
              {quoteTotal === null ? "-" : formatPrize(quoteTotal)}
            </span>
          </div>
        </fieldset>

        <label className="flex flex-col gap-1 text-sm">
          상금 (원)
          <input
            type="number"
            min={1}
            value={brief.prize}
            onChange={(event) => setBrief((prev) => ({ ...prev, prize: event.target.value }))}
            data-testid="grill-brief-prize"
            className={`${INPUT_CLASS} font-mono`}
          />
        </label>

        {previewUnderfunded && quoteTotal !== null && (
          <p role="status" data-testid="grill-brief-underfunded-preview" className="text-xs text-attention">
            최소 제안 상금 합계({formatPrize(quoteTotal)}원)보다 적습니다 — 등록하면 목록에 「상금미달」 배지가
            붙지만, 그래도 개최할 수 있습니다.
          </p>
        )}

        <label className="flex flex-col gap-1 text-sm">
          마감 기한
          <input
            type="datetime-local"
            value={brief.deadlineAt}
            onChange={(event) => setBrief((prev) => ({ ...prev, deadlineAt: event.target.value }))}
            data-testid="grill-brief-deadline"
            className={INPUT_CLASS}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          설명 (선택)
          <textarea
            value={brief.description}
            onChange={(event) => setBrief((prev) => ({ ...prev, description: event.target.value }))}
            rows={3}
            data-testid="grill-brief-description"
            className={INPUT_CLASS}
          />
        </label>

        {createError && (
          <ErrorNote>
            <span data-testid="grill-brief-error">{createError}</span>
          </ErrorNote>
        )}

        <button
          type="button"
          onClick={() => void handleCreateDraft()}
          disabled={creating}
          data-testid="grill-brief-submit"
          className={`w-fit ${buttonClass("primary")}`}
        >
          {creating ? "만드는 중..." : "AI와 대화 시작"}
        </button>
      </div>
    </PageShell>
  );
}
