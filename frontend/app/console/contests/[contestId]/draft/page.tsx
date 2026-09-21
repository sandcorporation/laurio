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
// 브리프 필드(제목·카테고리·요구형태·마감·설명)는 #113의 `BriefEditPanel`이
// 고친다. Requirement 체크리스트 CRUD는 이 화면의 핵심이다.
//
// **제출을 받는 동안(published)에도 이 화면에서 계속 고칠 수 있다**(#473,
// ADR-0051) — 예전에는 결제(또는 무료 공개)가 끝나는 순간 이 화면 전체가
// 「닫힘」으로 바뀌었다. 지금은 **마감**(closed 이후)이 그 문이다. published
// 에서는 AI grill 대화(새 체크리스트를 처음부터 함께 만드는 자리)와 이미지
// CRUD만 계속 닫혀 있다 — 그 둘을 열지 않은 이유는 `contests.api.
// _get_owned_draft_contest`의 독스트링에 있다.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorNote, PageShell } from "@/app/components/ui";
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

// 마감 뒤(closed 이후)다 — Score가 이미 그 체크리스트를 근거로 만들어졌거나
// 만들어질 참이라(ADR-0006) 더 이상 고칠 것이 없다(#473, ADR-0051).
// draft·published는 둘 다 계속 고칠 수 있으므로 여기 들지 않는다.
const CONTENT_LOCKED_STATUSES = new Set(["closed", "judging_ended", "awarded"]);

type LoadState =
  | { status: "loading" }
  // 존재하지 않거나 남의 Contest다 — 두 경우를 구별하지 않는다(#111 AC: "있는지가
  // 아니라 없는지로 단언한다"). GET /contests/{id}가 이미 이 두 경우를 같은
  // 404로 합친다.
  | { status: "not-found" }
  | { status: "error"; message: string }
  // 마감 뒤다 — 이 화면에서 더 이상 고칠 것이 없으므로 대화·체크리스트를
  // 그리지 않는다.
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

  // 무료 공모전 공개 (#415, ADR-0048) — 결제 대신 이 화면에서 곧바로 부른다.
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  // 개최자 표시 이름(#447) — 비어 있으면 공개가 422로 막힌다.
  const [savingSponsorDisplayName, setSavingSponsorDisplayName] = useState(false);
  const [sponsorDisplayNameError, setSponsorDisplayNameError] = useState<string | null>(null);

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

      if (CONTENT_LOCKED_STATUSES.has(contest.data.status)) {
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

  /** 무료 공모전 공개(#415) — 본인확인·결제 없이 개최 권한만으로 `draft ->
   * published`를 옮긴다. 성공하면 이 화면이 더 이상 편집을 허용하지 않는
   * `closed` 상태로 다시 그려지도록 응답을 그대로 반영한다(payment/page.tsx의
   * 결제 확인 성공 경로와 같은 모양). */
  async function handlePublish() {
    setPublishError(null);
    setPublishing(true);
    try {
      const response = await bffClient.post<ContestDetail>(
        `/api/backend/contests/${contestId}/publish`,
        {},
      );
      if (!response.ok) {
        setPublishError(response.detail);
        return;
      }
      if (response.data === undefined) {
        setPublishError("공개 응답을 해석하지 못했습니다. 새로고침해 확인해 주세요.");
        return;
      }
      setLoad({ status: "closed", contest: response.data });
    } catch {
      setPublishError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setPublishing(false);
    }
  }

  /** 개최자 표시 이름을 저장한다(#447, 기존 프로필 저장 API) — 성공하면 이
   * 화면이 들고 있는 Contest에도 즉시 반영해, 다시 불러오지 않고도 공개
   * 버튼이 바로 풀리게 한다. */
  async function handleSaveSponsorDisplayName(name: string): Promise<boolean> {
    if (load.status !== "ready") return false;
    setSponsorDisplayNameError(null);
    setSavingSponsorDisplayName(true);
    try {
      const response = await bffClient.post<{ display_name: string }>(
        "/api/backend/accounts/sponsor-profile",
        { display_name: name },
      );
      if (!response.ok) {
        setSponsorDisplayNameError(response.detail);
        return false;
      }
      setLoad({
        status: "ready",
        contest: { ...load.contest, sponsor_display_name: response.data.display_name || null },
      });
      return true;
    } catch {
      setSponsorDisplayNameError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      return false;
    } finally {
      setSavingSponsorDisplayName(false);
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
        <ErrorNote>
          <span data-testid="draft-load-error">{load.message}</span>
        </ErrorNote>
      </main>
    );
  }

  if (load.status === "closed") {
    return (
      <PageShell>
        <ContestStageStepper current="payment" variant={load.contest.is_free ? "free" : "paid"} />
        <h1 className="mt-4 text-2xl font-semibold" data-testid="draft-closed-heading">
          {load.contest.title}
        </h1>
        {/* 마감이 이유다(#473) — Score가 이미 이 체크리스트를 근거로
            만들어졌거나 만들어질 참이라, 그 뒤에 조건이 바뀌면 이의 심판이
            무엇을 근거로 판정했는지 재현할 수 없다. */}
        <p className="mt-6" data-testid="draft-closed">
          마감된 공모전입니다. 채점이 지금의 요구사항을 근거로 진행되므로 더 이상 브리프나 요구사항을
          수정할 수 없습니다.
        </p>
        <Link
          href={`/contests/${contestId}`}
          data-testid="draft-view-contest"
          className="mt-4 inline-block text-sm underline"
        >
          공모전 보기
        </Link>
      </PageShell>
    );
  }

  const { contest } = load;
  const contestForPanel = { ...contest, requirements };
  const isDraft = contest.status === "draft";

  return (
    <main className="flex min-h-screen flex-col" data-testid="draft-phase-b">
      <div className="border-b border-rule px-8 py-3">
        <ContestStageStepper current="requirements" variant={contest.is_free ? "free" : "paid"} />
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
      {/* 이미지 CRUD는 여전히 DRAFT뿐이다 — `contests.api._get_owned_draft_
          contest` 독스트링이 이유를 적는다(#473). */}
      {isDraft && (
        <ContestImagePanel
          contestId={contest.id}
          images={images}
          editable
          onImagesChange={setImages}
        />
      )}
      <div
        className={
          isDraft
            ? "grid flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_452px]"
            : "grid flex-1 grid-cols-1 lg:grid-cols-[452px]"
        }
      >
        {/* AI grill 대화도 여전히 DRAFT뿐이다 — 이미 확정된 체크리스트를
            처음부터 다시 대화로 만드는 자리라서다(같은 독스트링). */}
        {isDraft && (
          <GrillChatPanel
            messages={messages}
            proposals={proposals}
            onSend={handleSendChat}
            onAddProposal={(proposal) => void handleAddRequirement(proposal.text, proposal.grade, proposal)}
            sending={sending}
            chatError={chatError}
            turnLimitReached={turnLimitReached}
          />
        )}
        <RequirementDraftPanel
          contest={contestForPanel}
          requirements={requirements}
          requirementError={requirementError}
          requirementBusy={requirementBusy}
          onAdd={(text, grade) => handleAddRequirement(text, grade)}
          onUpdate={handleUpdateRequirement}
          onDelete={handleDeleteRequirement}
          onPublish={handlePublish}
          publishing={publishing}
          publishError={publishError}
          onSaveSponsorDisplayName={handleSaveSponsorDisplayName}
          savingSponsorDisplayName={savingSponsorDisplayName}
          sponsorDisplayNameError={sponsorDisplayNameError}
        />
      </div>
    </main>
  );
}
