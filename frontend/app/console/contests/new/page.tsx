"use client";

// AI grill 개최 (FE-12, #37, spec #25 User Story 40-48, design/Brief.dc.html).
//
// 두 단계로 나뉜다 — 백엔드 API 표면이 그렇게 생겼기 때문이다:
//
//   Phase A (브리프) — 아직 Contest가 없다. 제목·카테고리·요구형태·상금·마감을
//   받는다. 요구형태를 고를 때마다 최소 제안 상금 합계를 POST /contests/quote로
//   실시간으로 보여준다(직접 합산하지 않는다 — 규칙이 두 곳에서 어긋나면 안 된다).
//
//   Phase B (AI grill) — Phase A를 제출하면 그 순간 Contest가 draft로
//   생성된다(POST /api/contests, requirements=[]). AI grill 대화와 Requirement
//   CRUD는 전부 이 contest_id에 매달린 하위 자원이라, 대화가 시작되려면 Contest가
//   먼저 있어야 한다. 생성 이후에는 제목·요구형태·상금을 고치는 엔드포인트가
//   없으므로(REQUEST.md의 "체크리스트만 대화로 정한다"는 설계 그대로) 그 값들은
//   Phase B에서 읽기 전용 요약으로만 보여준다. 이 화면 안에서 실제로 계속
//   바뀌는 것은 Requirement 체크리스트뿐이다.
//
// LLM 신뢰 경계 — 이 화면이 실제로 부르는 백엔드
// (contests/requirement_chat.py `send_requirement_chat_message`)는 어댑터가
// 죽어도 이미 사과 응답으로 감성해 절대 500을 내지 않는다. 그래도 이 화면은
// 그 응답을 타입 캐스팅으로 그냥 믿지 않는다 — BFF 프록시가 502/504를 빈
// 본문으로 삼키거나 응답이 아예 오지 않는 경우까지 포함해, `lib/contests/
// chat-response.ts`의 방어적 파서를 거친다(#37 인수조건 — "LLM이 이상하거나
// 형식에 맞지 않는 응답을 해도 화면이 죽지 않는다").
import { useEffect, useMemo, useState } from "react";

import { sessionFetch } from "@/lib/auth/client-fetch";
import { useSession } from "@/lib/auth/use-session";
import { formatPrize } from "@/lib/contest-format";
import {
  FALLBACK_CHAT_REPLY,
  parseChatReply,
  readErrorDetail,
  sanitizeChatTurns,
  type ChatProposal,
  type ParsedChatTurn,
} from "@/lib/contests/chat-response";
import {
  CHAT_MAX_HISTORY_TURNS,
  type Category,
  type ContestDetail,
  type DeliverableType,
  type RequirementGrade,
  type RequirementOut,
  type VerificationStatusOut,
} from "@/lib/contests/grill-types";

import { GrillChatPanel } from "./grill-chat-panel";
import { RequirementDraftPanel } from "./requirement-draft-panel";

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

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [reloadTick, setReloadTick] = useState(0);
  const [verifying, setVerifying] = useState(false);

  // --- Phase A: 브리프 ------------------------------------------------------
  const [brief, setBrief] = useState<BriefForm>(EMPTY_BRIEF);
  const [quoteTotal, setQuoteTotal] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // --- Phase B: AI grill 대화 + 체크리스트 -----------------------------------
  const [contest, setContest] = useState<ContestDetail | null>(null);
  const [requirements, setRequirements] = useState<RequirementOut[]>([]);
  const [messages, setMessages] = useState<ParsedChatTurn[]>([]);
  const [proposals, setProposals] = useState<ChatProposal[]>([]);
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [requirementError, setRequirementError] = useState<string | null>(null);
  const [requirementBusy, setRequirementBusy] = useState(false);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    async function loadAll() {
      const [catRes, dtRes, verRes] = await Promise.all([
        sessionFetch("/api/backend/contests/categories"),
        sessionFetch("/api/backend/contests/deliverable-types"),
        sessionFetch("/api/backend/verification/me"),
      ]);
      if (cancelled) return;

      if (!catRes.ok || !dtRes.ok || !verRes.ok) {
        setLoad({ status: "error", message: "화면을 불러오지 못했습니다." });
        return;
      }

      const categories = await catRes.json().catch(() => null);
      const deliverableTypes = await dtRes.json().catch(() => null);
      const verification = await verRes.json().catch(() => null);
      if (cancelled) return;

      if (!Array.isArray(categories) || !Array.isArray(deliverableTypes) || !isPlainRecord(verification)) {
        setLoad({ status: "error", message: "화면을 불러오지 못했습니다." });
        return;
      }

      setLoad({
        status: "ready",
        categories,
        deliverableTypes,
        verification: verification as unknown as VerificationStatusOut,
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
    if (contest) return; // Phase B에서는 서버가 만든 required_minimum_prize를 그대로 쓴다.
    if (brief.deliverableTypeIds.length === 0) {
      setQuoteTotal(0);
      return;
    }
    let cancelled = false;
    sessionFetch("/api/backend/contests/quote", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ deliverable_type_ids: brief.deliverableTypeIds }),
    })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setQuoteTotal(null);
          return;
        }
        const body = await res.json().catch(() => null);
        if (isPlainRecord(body) && typeof body.minimum_total === "number") {
          setQuoteTotal(body.minimum_total);
        } else {
          setQuoteTotal(null);
        }
      })
      .catch(() => {
        if (!cancelled) setQuoteTotal(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliverableTypeKey가 배열 내용의 안정된 대리 키다.
  }, [deliverableTypeKey, contest]);

  const prizeNumber = Number(brief.prize);
  const previewUnderfunded =
    quoteTotal !== null && quoteTotal > 0 && Number.isFinite(prizeNumber) && prizeNumber < quoteTotal;

  async function handleVerifyDev() {
    if (session.status !== "authenticated") return;
    setVerifying(true);
    try {
      const seed = session.user.username;
      const res = await sessionFetch("/api/backend/verification/verify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ verification_token: `${seed}|1990-01-01|ci-${seed}|di-${seed}` }),
      });
      if (res.ok) setReloadTick((t) => t + 1);
    } finally {
      setVerifying(false);
    }
  }

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
      const res = await sessionFetch("/api/backend/contests", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title,
          category_id: brief.categoryId,
          deliverable_type_ids: brief.deliverableTypeIds,
          description: brief.description,
          prize: prizeNumber,
          deadline_at: new Date(brief.deadlineAt).toISOString(),
          requirements: [],
        }),
      });

      if (!res.ok) {
        setCreateError((await readErrorDetail(res)) ?? `초안을 만들지 못했습니다 (${res.status})`);
        return;
      }

      const created = await res.json().catch(() => null);
      if (!isPlainRecord(created) || typeof created.id !== "number") {
        setCreateError("초안 생성 응답을 해석하지 못했습니다. 다시 시도해 주세요.");
        return;
      }

      setContest(created as unknown as ContestDetail);
      setRequirements(Array.isArray(created.requirements) ? (created.requirements as RequirementOut[]) : []);
    } catch {
      setCreateError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setCreating(false);
    }
  }

  const turnLimitReached = messages.length >= CHAT_MAX_HISTORY_TURNS;

  async function handleSendChat(text: string) {
    if (!contest) return;
    setChatError(null);
    setSending(true);
    try {
      const res = await sessionFetch(`/api/backend/contests/${contest.id}/requirement-chat/messages`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text }),
      });

      if (!res.ok) {
        setChatError((await readErrorDetail(res)) ?? `메시지를 보내지 못했습니다 (${res.status})`);
        return;
      }

      let body: unknown;
      try {
        body = await res.json();
      } catch {
        // 본문이 JSON이 아니다 — 프록시가 대신 HTML 에러 페이지 등을 돌려준
        // 경우다. 대화는 끊지 않고 사과 메시지 한 턴만 화면에 남긴다.
        const now = new Date().toISOString();
        setMessages((prev) => [
          ...prev,
          { role: "sponsor", content: text, created_at: now },
          { role: "assistant", content: FALLBACK_CHAT_REPLY, created_at: now },
        ]);
        return;
      }

      const parsed = parseChatReply(body);
      const sanitizedHistory = sanitizeChatTurns(
        isPlainRecord(body) ? (body as Record<string, unknown>).messages : undefined,
      );
      if (sanitizedHistory.length > 0) {
        setMessages(sanitizedHistory);
      } else {
        // messages 필드가 아예 없거나 전부 깨져 있어도, 최소한 지금 주고받은
        // 두 턴만은 화면에 남겨 대화가 끊긴 것처럼 보이지 않게 한다.
        const now = new Date().toISOString();
        setMessages((prev) => [
          ...prev,
          { role: "sponsor", content: text, created_at: now },
          { role: "assistant", content: parsed.reply, created_at: now },
        ]);
      }
      setProposals(parsed.proposals);
    } catch {
      setChatError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSending(false);
    }
  }

  async function handleAddRequirement(text: string, grade: RequirementGrade, fromProposal?: ChatProposal) {
    if (!contest) return;
    setRequirementError(null);
    setRequirementBusy(true);
    try {
      const res = await sessionFetch(`/api/backend/contests/${contest.id}/requirements`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text, grade }),
      });

      if (!res.ok) {
        setRequirementError((await readErrorDetail(res)) ?? `추가하지 못했습니다 (${res.status})`);
        return;
      }

      const created = await res.json().catch(() => null);
      if (isPlainRecord(created) && typeof created.id === "number" && typeof created.text === "string") {
        setRequirements((prev) => [...prev, created as unknown as RequirementOut]);
        if (fromProposal) {
          setProposals((prev) => prev.filter((p) => p !== fromProposal));
        }
      } else {
        setRequirementError("추가 응답을 해석하지 못했습니다. 새로고침해 확인해 주세요.");
      }
    } catch {
      setRequirementError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setRequirementBusy(false);
    }
  }

  async function handleUpdateRequirement(
    id: number,
    patch: { text?: string; grade?: RequirementGrade },
  ): Promise<boolean> {
    if (!contest) return false;
    setRequirementError(null);
    try {
      const res = await sessionFetch(`/api/backend/contests/${contest.id}/requirements/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(patch),
      });

      if (!res.ok) {
        setRequirementError((await readErrorDetail(res)) ?? `수정하지 못했습니다 (${res.status})`);
        return false;
      }

      const updated = await res.json().catch(() => null);
      if (isPlainRecord(updated) && typeof updated.id === "number") {
        setRequirements((prev) =>
          prev.map((r) => (r.id === id ? (updated as unknown as RequirementOut) : r)),
        );
        return true;
      }
      setRequirementError("수정 응답을 해석하지 못했습니다. 다시 시도해 주세요.");
      return false;
    } catch {
      setRequirementError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      return false;
    }
  }

  async function handleDeleteRequirement(id: number) {
    if (!contest) return;
    setRequirementError(null);
    try {
      const res = await sessionFetch(`/api/backend/contests/${contest.id}/requirements/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        setRequirementError((await readErrorDetail(res)) ?? `삭제하지 못했습니다 (${res.status})`);
        return;
      }
      setRequirements((prev) => prev.filter((r) => r.id !== id));
    } catch {
      setRequirementError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  }

  const contestForPanel = useMemo(() => {
    if (!contest) return null;
    return { ...contest, requirements };
  }, [contest, requirements]);

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="grill-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="grill-load-error">
          {load.message}
        </p>
      </main>
    );
  }

  const { categories, deliverableTypes, verification } = load;

  if (verification.status !== "verified") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-10">
        <p role="alert" data-testid="grill-verification-required" className="text-attention">
          본인확인(Verification)을 완료해야 공모전을 개최할 수 있습니다.
        </p>
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
            className="rounded-sm border border-rule px-4 py-2 text-sm hover:border-ink disabled:opacity-50"
          >
            {verifying ? "확인 중..." : "지금 본인확인하기(dev)"}
          </button>
        )}
      </main>
    );
  }

  // --- Phase B: 이미 draft Contest가 있으면 AI grill 화면을 보여준다 ------------
  if (contestForPanel) {
    return (
      <main className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_452px]" data-testid="grill-phase-b">
        <GrillChatPanel
          messages={messages}
          proposals={proposals}
          onSend={handleSendChat}
          onAddProposal={(proposal) => void handleAddRequirement(proposal.text, proposal.grade, proposal)}
          sending={sending}
          chatError={chatError}
          turnLimitReached={turnLimitReached}
        />
        <RequirementDraftPanel
          contest={contestForPanel}
          requirements={requirements}
          requirementError={requirementError}
          requirementBusy={requirementBusy}
          onAdd={(text, grade) => handleAddRequirement(text, grade)}
          onUpdate={handleUpdateRequirement}
          onDelete={handleDeleteRequirement}
        />
      </main>
    );
  }

  // --- Phase A: 브리프 입력 폼 ------------------------------------------------
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col gap-6 p-10">
      <div>
        <p className="text-xs font-medium tracking-widest text-ink/60">공모전 개최</p>
        <h1 className="text-2xl font-semibold" data-testid="grill-brief-heading">
          기본 정보를 알려주세요
        </h1>
        <p className="mt-2 text-sm text-ink/70">
          다음 단계에서 AI와 대화하며 요구사항 체크리스트를 함께 만듭니다.
        </p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        제목
        <input
          value={brief.title}
          onChange={(event) => setBrief((prev) => ({ ...prev, title: event.target.value }))}
          maxLength={200}
          data-testid="grill-brief-title"
          className="border border-rule bg-surface px-3 py-2"
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
          className="border border-rule bg-surface px-3 py-2"
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
          className="border border-rule bg-surface px-3 py-2 font-mono"
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
          className="border border-rule bg-surface px-3 py-2"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        설명 (선택)
        <textarea
          value={brief.description}
          onChange={(event) => setBrief((prev) => ({ ...prev, description: event.target.value }))}
          rows={3}
          data-testid="grill-brief-description"
          className="border border-rule bg-surface px-3 py-2"
        />
      </label>

      {createError && (
        <p role="alert" data-testid="grill-brief-error" className="text-sm text-attention">
          {createError}
        </p>
      )}

      <button
        type="button"
        onClick={() => void handleCreateDraft()}
        disabled={creating}
        data-testid="grill-brief-submit"
        className="w-fit border border-ink bg-ink px-6 py-2 text-sm text-paper disabled:opacity-50"
      >
        {creating ? "만드는 중..." : "AI와 대화 시작"}
      </button>
    </main>
  );
}
