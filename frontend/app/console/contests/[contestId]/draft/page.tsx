"use client";

// 초안 이어서 작성 화면 (#111, 부모 #110).
//
// 지금까지 draft Contest는 브라우저 메모리에만 살았다 — 새로고침하면 화면은
// 빈 브리프 폼으로 돌아가고, 만들어진 draft는 DB에 남는데 돌아갈 자리가
// 없었다. 이 화면이 그 자리다: **Contest를 URL로 식별하고 서버에서 다시
// 읽는다** — POST /contests의 생성 응답에만 기대지 않는다(AC1). 그래서
// 새로고침·북마크·「내 공모전」목록에서의 재진입이 전부 여기로 수렴한다.
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015, 다른 모든 /console/** 화면과 같은
// 이유) — "서버에서 읽는다"는 것은 Next 서버 컴포넌트가 아니라 이 클라이언트
// 컴포넌트가 마운트 시 항상 GET으로 백엔드에서 다시 조회한다는 뜻이다
// (payment/page.tsx와 같은 관용구).
//
// **이 티켓은 읽기까지다** — 브리프 필드(제목·카테고리·요구형태·상금·마감)를
// 고치는 화면은 #113의 몫이다. 여기서 실제로 계속 바뀌는 것은 기존 Phase B와
// 같이 AI grill 대화와 Requirement 체크리스트뿐이다.
//
// **결제가 끝나면 이 화면으로의 편집 이동이 닫힌다**(spec #110) — Contest가
// draft를 벗어나면 대화·체크리스트 UI를 그리지 않고, 공개된 공모전으로 가는
// 링크만 남긴다.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import {
  FALLBACK_CHAT_REPLY,
  parseChatReply,
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
} from "@/lib/contests/grill-types";

import { BriefEditPanel, type BriefEditPatch } from "../../_components/brief-edit-panel";
import { ContestImagePanel } from "../../_components/contest-image-panel";
import { ContestStageStepper } from "../../_components/contest-stage-stepper";
import { GrillChatPanel } from "../../_components/grill-chat-panel";
import { RequirementDraftPanel } from "../../_components/requirement-draft-panel";
import type { ContestImage } from "@/lib/upload/use-contest-image-upload";

type LoadState =
  | { status: "loading" }
  // 존재하지 않거나 남의 draft다 — 두 경우를 구별하지 않는다(#111 AC: "있는지가
  // 아니라 없는지로 단언한다"). GET /contests/{id}가 이미 이 두 경우를 같은
  // 404로 합친다.
  | { status: "not-found" }
  | { status: "error"; message: string }
  // draft를 벗어난 Contest다 — 결제가 끝나 공개됐다(또는 그 이후 상태다).
  // 이 화면에서 더 이상 고칠 것이 없으므로 대화·체크리스트를 그리지 않는다.
  | { status: "closed"; contest: ContestDetail }
  | { status: "ready"; contest: ContestDetail };

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function ContestDraftPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });

  const [requirements, setRequirements] = useState<RequirementOut[]>([]);
  const [images, setImages] = useState<ContestImage[]>([]);
  const [messages, setMessages] = useState<ParsedChatTurn[]>([]);
  const [proposals, setProposals] = useState<ChatProposal[]>([]);
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [requirementError, setRequirementError] = useState<string | null>(null);
  const [requirementBusy, setRequirementBusy] = useState(false);

  // #113 — 브리프 수정(제목·설명·카테고리·요구형태·상금·마감). 편집 폼이 필요로
  // 하는 선택지도 draft일 때만 함께 읽는다.
  const [categories, setCategories] = useState<Category[]>([]);
  const [deliverableTypes, setDeliverableTypes] = useState<DeliverableType[]>([]);
  const [briefSaving, setBriefSaving] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [deliverableTypesChangedNotice, setDeliverableTypesChangedNotice] = useState(false);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    async function loadAll() {
      const contest = await bffClient.get<ContestDetail>(`/api/backend/contests/${contestId}`);
      if (cancelled) return;

      if (!contest.ok) {
        if (contest.status === 404) return setLoad({ status: "not-found" });
        return setLoad({ status: "error", message: "공모전 정보를 불러오지 못했습니다." });
      }
      if (contest.data === undefined) {
        return setLoad({ status: "error", message: "공모전 정보를 해석하지 못했습니다." });
      }

      if (contest.data.status !== "draft") {
        return setLoad({ status: "closed", contest: contest.data });
      }

      // 대화 이력·브리프 편집 폼이 쓸 선택지도 함께 읽는다 — "다시 들어와도 이어갈 수 있게
      // 한다"(contests/models.py RequirementChatMessage)와, 브리프 수정 폼(#113)이 카테고리·
      // 요구형태 선택지를 그리는 데 쓴다. 이 조회들이 실패해도 화면 자체는 죽지 않는다 —
      // 빈 대화·빈 선택지로 이어가면 그만이다. 클라이언트가 네트워크 실패까지 `ApiResult` 로
      // 돌려주므로(#146) 셋 중 하나가 죽어도 나머지가 함께 무너지지 않는다.
      const [chat, categoriesResult, deliverableTypesResult] = await Promise.all([
        bffClient.get<unknown>(`/api/backend/contests/${contestId}/requirement-chat/messages`),
        bffClient.get<unknown>("/api/backend/contests/categories"),
        bffClient.get<unknown>("/api/backend/contests/deliverable-types"),
      ]);
      if (cancelled) return;

      setRequirements(Array.isArray(contest.data.requirements) ? contest.data.requirements : []);
      setImages(Array.isArray(contest.data.images) ? contest.data.images : []);
      setMessages(sanitizeChatTurns(chat.ok ? chat.data : null));
      setCategories(categoriesResult.ok && Array.isArray(categoriesResult.data) ? categoriesResult.data : []);
      setDeliverableTypes(deliverableTypesResult.ok && Array.isArray(deliverableTypesResult.data) ? deliverableTypesResult.data : []);
      setLoad({ status: "ready", contest: contest.data });
    }

    loadAll().catch(() => {
      if (!cancelled) setLoad({ status: "error", message: "불러오는 중 오류가 발생했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, contestId]);

  const turnLimitReached = messages.length >= CHAT_MAX_HISTORY_TURNS;

  async function handleSendChat(text: string) {
    setChatError(null);
    setSending(true);
    try {
      const sent = await bffClient.post<unknown>(
        `/api/backend/contests/${contestId}/requirement-chat/messages`,
        { message: text },
      );

      if (!sent.ok) {
        if (sent.code === "malformed") {
          // 2xx 인데 본문이 JSON이 아니다 — 프록시가 대신 HTML 에러 페이지 등을 돌려준
          // 경우다. 대화는 끊지 않고 사과 메시지 한 턴만 화면에 남긴다.
          const now = new Date().toISOString();
          setMessages((prev) => [
            ...prev,
            { role: "sponsor", content: text, created_at: now },
            { role: "assistant", content: FALLBACK_CHAT_REPLY, created_at: now },
          ]);
          return;
        }
        setChatError(sent.detail);
        return;
      }

      const body = sent.data;

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
    setRequirementError(null);
    setRequirementBusy(true);
    try {
      const response = await bffClient.post<unknown>(
        `/api/backend/contests/${contestId}/requirements`,
        { text, grade },
      );

      if (!response.ok) {
        setRequirementError(response.detail);
        return;
      }

      const created = response.data;
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
    setRequirementError(null);
    try {
      const response = await bffClient.request<unknown>(
        `/api/backend/contests/${contestId}/requirements/${id}`,
        {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(patch),
        },
      );

      if (!response.ok) {
        setRequirementError(response.detail);
        return false;
      }

      const updated = response.data;
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

  /** 브리프를 고친다(#113) — 판정은 전부 백엔드가 한다: 파생값(최소 상금 합계·
   * 상금미달)은 이 함수가 계산하지 않고 `PATCH /contests/{id}` 응답을 그대로
   * 반영한다. 요구형태가 바뀌었으면 배너를 띄운다 — 이미 붙인 Requirement는
   * 지워지지 않지만 Sponsor가 스스로 검토해야 하기 때문이다. */
  async function handleSaveBrief(patch: BriefEditPatch): Promise<boolean> {
    if (load.status !== "ready") return false;
    const previousTypeIds = load.contest.deliverable_types
      .map((dt) => dt.id)
      .sort((a, b) => a - b)
      .join(",");

    setBriefError(null);
    setBriefSaving(true);
    try {
      const response = await bffClient.request<ContestDetail>(`/api/backend/contests/${contestId}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(patch),
      });

      if (!response.ok) {
        setBriefError(response.detail);
        return false;
      }

      const updated = response.data;
      if (updated === undefined) {
        setBriefError("수정 응답을 해석하지 못했습니다. 새로고침해 확인해 주세요.");
        return false;
      }

      const nextTypeIds = updated.deliverable_types
        .map((dt) => dt.id)
        .sort((a, b) => a - b)
        .join(",");
      if (nextTypeIds !== previousTypeIds) {
        setDeliverableTypesChangedNotice(true);
      }

      setRequirements(Array.isArray(updated.requirements) ? updated.requirements : requirements);
      setImages(Array.isArray(updated.images) ? updated.images : images);
      setLoad({ status: "ready", contest: updated });
      return true;
    } catch {
      setBriefError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      return false;
    } finally {
      setBriefSaving(false);
    }
  }

  async function handleDeleteRequirement(id: number) {
    setRequirementError(null);
    try {
      const response = await bffClient.request(
        `/api/backend/contests/${contestId}/requirements/${id}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        setRequirementError(response.detail);
        return;
      }
      setRequirements((prev) => prev.filter((r) => r.id !== id));
    } catch {
      setRequirementError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  }

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="draft-loading">불러오는 중...</p>
      </main>
    );
  }

  if (load.status === "not-found") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="draft-not-found">공모전을 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (load.status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="draft-load-error">
          {load.message}
        </p>
      </main>
    );
  }

  if (load.status === "closed") {
    return (
      <main className="mx-auto max-w-xl p-10">
        <ContestStageStepper current="payment" />
        <h1 className="mt-4 text-2xl font-semibold" data-testid="draft-closed-heading">
          {load.contest.title}
        </h1>
        <p className="mt-6" data-testid="draft-closed">
          이미 결제가 완료되어 공개된 공모전입니다. 더 이상 브리프나 요구사항을 수정할 수 없습니다.
        </p>
        <Link
          href={`/contests/${contestId}`}
          data-testid="draft-view-contest"
          className="mt-4 inline-block text-sm underline"
        >
          공모전 보기
        </Link>
      </main>
    );
  }

  const { contest } = load;
  const contestForPanel = { ...contest, requirements };

  return (
    <main className="flex min-h-screen flex-col" data-testid="draft-phase-b">
      <div className="border-b border-rule px-8 py-3">
        <ContestStageStepper current="requirements" />
      </div>
      <BriefEditPanel
        contest={contest}
        categories={categories}
        deliverableTypes={deliverableTypes}
        saving={briefSaving}
        error={briefError}
        deliverableTypesChangedNotice={deliverableTypesChangedNotice}
        onDismissDeliverableTypesChangedNotice={() => setDeliverableTypesChangedNotice(false)}
        onSave={handleSaveBrief}
      />
      <ContestImagePanel
        contestId={contest.id}
        images={images}
        editable
        onImagesChange={setImages}
      />
      <div className="grid flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_452px]">
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
      </div>
    </main>
  );
}
