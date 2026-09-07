"use client";

// InviteCode 입력·진입 + 과제 상세 + 제출·수정 (#208, ADR-0028/0029).
//
// **본인확인을 요구하지 않는다** — `/console/contests/[contestId]/submit`과 달리
// Verification 게이트가 없다. 대신 InviteCode 를 아는 사람만 이 화면에 닿는다:
// 코드는 URL 자체가 들고 있고, 제출·수정 요청마다 서버가 다시 확인한다
// (`submissions.api._require_invite_code_for_assignment`).
//
// **`/console` 밖에 둔다.** 학생은 로그인 전에 이 URL을 열 수 있어야 한다 —
// `useSession()`(app/console/**)은 401을 만나면 곧장 `/login`으로 리다이렉트해
// 버려 "먼저 과제를 구경하고 나중에 로그인" 흐름을 끊는다. 그래서 헤더의
// `SessionSlot`과 같은 관용구(`unauthorizedIsAnswer: true`)로 세션을 직접 확인한다.
//
// 상금·결제·Award·Escrow는 이 화면 어디에도 나오지 않는다 — 대신 제출 전에
// 두 가지를 고지한다: 강사가 소스를 열람할 수 있다는 것, 저작권은 학생에게
// 남는다는 것(스펙 #197, 약관 항목 17·18).
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { useBackendQuery } from "@laurio/bff-client";
import type { components } from "@laurio/bff-client/schema";

import { bffClient } from "@/lib/bff/client";
import { ScoreSummary } from "@/lib/assignments/score-summary";
import { ASSET_KIND_LABELS } from "@/lib/submissions/types";
import type { SubmissionIn, SubmissionOut } from "@/lib/submissions/types";

import {
  AssetKindSection,
  createEmptyAsset,
  type EditableAsset,
} from "../../console/contests/[contestId]/submit/asset-kind-section";
import {
  RequirementField,
  type RequirementFieldState,
} from "../../console/contests/[contestId]/submit/requirement-field";

type AssignmentDetail = components["schemas"]["AssignmentOut"];
type OwnScore = components["schemas"]["OwnScoreOut"];
type ScoreState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "not-scored" }
  | { status: "error" }
  | { status: "ready"; data: OwnScore };

type SessionUser = { id: number; username: string };
type SessionState =
  | { status: "loading" }
  | { status: "authenticated"; user: SessionUser }
  | { status: "unauthenticated" };

function useLightSession(): SessionState {
  const { state } = useBackendQuery<SessionUser>(bffClient, "/api/auth/session", {
    unauthorizedIsAnswer: true,
  });
  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") return { status: "unauthenticated" };
  return { status: "authenticated", user: state.data };
}

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

export default function AssignmentInvitePage() {
  const params = useParams<{ code: string }>();
  const code = params.code;
  const session = useLightSession();

  const [assignment, setAssignment] = useState<
    { status: "loading" } | { status: "not-found" } | { status: "error" } | { status: "ready"; data: AssignmentDetail }
  >({ status: "loading" });
  const [submission, setSubmission] = useState<SubmissionOut | null>(null);
  const [submissionLoaded, setSubmissionLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const [sourceAssets, setSourceAssets] = useState<EditableAsset[]>([createEmptyAsset()]);
  const [demoVideoAssets, setDemoVideoAssets] = useState<EditableAsset[]>([]);
  const [demoUrlAssets, setDemoUrlAssets] = useState<EditableAsset[]>([]);
  const [repositoryAssets, setRepositoryAssets] = useState<EditableAsset[]>([]);
  const [unknownKindAssets, setUnknownKindAssets] = useState<SubmissionOut["assets"]>([]);
  const [requirementStates, setRequirementStates] = useState<Record<number, RequirementFieldState>>({});
  const [saveState, setSaveState] = useState<{ status: "idle" | "saving" | "done" | "error"; message?: string }>({
    status: "idle",
  });
  const [score, setScore] = useState<ScoreState>({ status: "idle" });

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // 과제 상세 — 로그인 여부와 무관하게 코드 하나로 조회한다(백엔드 auth=None).
  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    void bffClient.get<AssignmentDetail>(`/api/backend/assignments/invite/${code}`).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setAssignment(result.status === 404 ? { status: "not-found" } : { status: "error" });
        return;
      }
      setAssignment({ status: "ready", data: result.data });
    });
    return () => {
      cancelled = true;
    };
  }, [code]);

  function applySubmissionAssets(next: SubmissionOut | null) {
    const assets = next?.assets ?? [];
    const nextSourceAssets = assetsOfKind(assets, "source");
    setSourceAssets(nextSourceAssets.length > 0 ? nextSourceAssets : [createEmptyAsset()]);
    setDemoVideoAssets(assetsOfKind(assets, "demo_video"));
    setDemoUrlAssets(assetsOfKind(assets, "demo_url"));
    setRepositoryAssets(assetsOfKind(assets, "repository"));
    setUnknownKindAssets(assets.filter((a) => !KNOWN_ASSET_KINDS.has(a.kind)));
  }

  // 로그인된 뒤에만 내 제출을 읽는다 — 비로그인 방문자에게는 애초에 「내 것」이 없다.
  useEffect(() => {
    if (session.status !== "authenticated" || assignment.status !== "ready") return;
    let cancelled = false;
    const assignmentId = assignment.data.id;

    void bffClient
      .get<SubmissionOut>(`/api/backend/contests/${assignmentId}/submissions/me`)
      .then((result) => {
        if (cancelled) return;
        const existing = result.ok ? result.data : null;
        setSubmission(existing);
        applySubmissionAssets(existing);

        const initialStates: Record<number, RequirementFieldState> = {};
        for (const requirement of assignment.data.requirements) {
          const existingResponse = existing?.requirement_responses.find(
            (r) => r.requirement_id === requirement.id,
          );
          initialStates[requirement.id] = {
            isMet: existingResponse?.is_met ?? false,
            note: existingResponse?.note ?? "",
            evidence:
              existingResponse?.evidence.map((e) => ({
                kind: e.kind,
                value: e.value,
                asset_id: e.asset_id ?? null,
              })) ?? [],
          };
        }
        setRequirementStates(initialStates);
        setSubmissionLoaded(true);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- assignment.data는 조회 성공 시 한 번만 갈린다.
  }, [session.status, assignment.status]);

  const deadlineAt =
    assignment.status === "ready" ? new Date(assignment.data.deadline_at).getTime() : null;
  const isPastDeadline = deadlineAt !== null && now >= deadlineAt;
  const requirements = assignment.status === "ready" ? assignment.data.requirements : [];

  // 마감 후 내 Score 를 본다(#210, ADR-0006) — 채점은 마감 후 스캔이 한 번만
  // 만든다(ADR-0003)이므로 마감 직후에는 아직 없을 수 있다("아직 채점 전"과
  // "실패"는 다른 사실이라 404 를 에러로 취급하지 않는다).
  useEffect(() => {
    if (!isPastDeadline || submission === null) return;
    let cancelled = false;
    setScore({ status: "loading" });
    void bffClient.get<OwnScore>(`/api/backend/submissions/${submission.id}/score`).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setScore(result.status === 404 ? { status: "not-scored" } : { status: "error" });
        return;
      }
      setScore({ status: "ready", data: result.data });
    });
    return () => {
      cancelled = true;
    };
  }, [isPastDeadline, submission]);

  const completion = useMemo(() => {
    const total = requirements.length;
    const linked = requirements.filter((r) => (requirementStates[r.id]?.evidence.length ?? 0) > 0).length;
    return total > 0 ? Math.round((linked / total) * 100) : 0;
  }, [requirements, requirementStates]);

  // 업로드 대상 — `console/contests/[contestId]/submit`와 같은 object key 모양
  // (`submission:{contest_id}:{developer_user_id}:{종류}`, `submissions.api`가
  // presigned URL을 발급할 때 검증하는 접두어). 이게 없으면 `AssetKindSection`이
  // `UploadField`를 아예 그리지 않아 소스를 업로드할 방법이 없다 — 이 화면이
  // 실제로 그 상태였다(#210 이 브라우저로 걸어보다 발견).
  const assignmentId = assignment.status === "ready" ? assignment.data.id : null;
  const userId = session.status === "authenticated" ? session.user.id : null;
  const sourceTargetRef =
    assignmentId !== null && userId !== null ? `submission:${assignmentId}:${userId}:source` : null;
  const demoVideoTargetRef =
    assignmentId !== null && userId !== null
      ? `submission:${assignmentId}:${userId}:demo-video`
      : null;

  async function handleSubmit() {
    if (assignment.status !== "ready" || session.status !== "authenticated") return;
    const hasSource = sourceAssets.some((row) => row.value.trim() !== "");
    if (!hasSource) {
      setSaveState({ status: "error", message: "소스코드를 먼저 업로드해주세요." });
      return;
    }

    setSaveState({ status: "saving" });

    const assets: SubmissionIn["assets"] = [
      ...rowsToAssetsIn(sourceAssets, "source"),
      ...rowsToAssetsIn(demoVideoAssets, "demo_video"),
      ...rowsToAssetsIn(demoUrlAssets, "demo_url"),
      ...rowsToAssetsIn(repositoryAssets, "repository"),
      ...unknownKindAssets.map((asset) => ({
        id: asset.id,
        kind: asset.kind,
        value: asset.value,
        label: asset.label,
        test_account: asset.test_account,
        order: asset.order,
      })),
    ];

    const payload: SubmissionIn = {
      assets,
      requirement_responses: assignment.data.requirements.map((r) => {
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
      // InviteCode 를 매 저장마다 함께 보낸다 — 본인확인·자전거래 검사가 없는
      // Assignment 경로에서 이것이 유일한 경계다(#208).
      invite_code: code,
    };

    const isUpdate = submission !== null;
    const path = isUpdate
      ? `/api/backend/contests/${assignment.data.id}/submissions/me`
      : `/api/backend/contests/${assignment.data.id}/submissions`;

    const saved = await bffClient.request<SubmissionOut>(path, {
      method: isUpdate ? "PUT" : "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!saved.ok) {
      setSaveState({ status: "error", message: saved.detail });
      return;
    }

    setSubmission(saved.data);
    applySubmissionAssets(saved.data);
    setSaveState({ status: "done" });
  }

  if (assignment.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="assignment-invite-loading">불러오는 중...</p>
      </main>
    );
  }

  if (assignment.status === "not-found") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="assignment-invite-not-found">
          InviteCode 를 찾을 수 없습니다. 코드를 다시 확인해 주세요.
        </p>
      </main>
    );
  }

  if (assignment.status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="assignment-invite-error">
          과제를 불러오지 못했습니다.
        </p>
      </main>
    );
  }

  const { data } = assignment;

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 p-10">
      <div>
        <h1 className="text-2xl font-semibold" data-testid="assignment-invite-title">
          {data.title}
        </h1>
        <p className="mt-2 text-sm text-ink/70" data-testid="assignment-invite-description">
          {data.description}
        </p>
        <p className="mt-2 font-mono text-sm" data-testid="assignment-invite-deadline">
          마감 {new Date(data.deadline_at).toLocaleString("ko-KR")}
          {isPastDeadline ? " — 마감되었습니다" : ""}
        </p>
      </div>

      {/* 제출 전 고지 둘 — 스펙 #197, 약관 항목 17·18. */}
      <div className="flex flex-col gap-1 border border-rule p-4 text-sm text-ink/80">
        <p data-testid="assignment-source-reading-notice">
          강사가 지도·채점을 위해 제출한 소스를 열람할 수 있으며, 그 열람은 기록됩니다.
        </p>
        <p data-testid="assignment-copyright-notice">
          제출한 소스코드의 저작권은 학생 본인에게 그대로 남습니다.
        </p>
      </div>

      {session.status === "loading" ? (
        <p data-testid="assignment-invite-session-loading">불러오는 중...</p>
      ) : session.status === "unauthenticated" ? (
        <a
          href={`/login?next=${encodeURIComponent(`/assignments/${code}`)}`}
          data-testid="assignment-invite-login-link"
          className="w-fit rounded-sm border border-ink bg-ink px-6 py-2 text-sm text-paper"
        >
          로그인해서 참여하기
        </a>
      ) : !submissionLoaded ? (
        <p data-testid="assignment-invite-submission-loading">불러오는 중...</p>
      ) : (
        <>
          <section
            className="flex flex-col gap-2"
            data-testid="assignment-completion-indicator"
            data-percent={completion}
          >
            <p className="text-sm">체크리스트 증거 연결 {completion}%</p>
            <div className="h-2 w-full rounded-sm border border-rule">
              <div className="h-full bg-verified" style={{ width: `${completion}%` }} />
            </div>
          </section>

          <AssetKindSection
            kind="source"
            title={ASSET_KIND_LABELS.source}
            required
            addLabel="+ 소스코드 추가"
            testIdPrefix="assignment-source-asset"
            rows={sourceAssets}
            onChange={setSourceAssets}
            disabled={isPastDeadline}
            targetRefPrefix={sourceTargetRef ?? undefined}
          />
          <AssetKindSection
            kind="repository"
            title={ASSET_KIND_LABELS.repository}
            addLabel="+ 저장소 추가"
            testIdPrefix="assignment-repository-asset"
            rows={repositoryAssets}
            onChange={setRepositoryAssets}
            disabled={isPastDeadline}
          />
          <AssetKindSection
            kind="demo_video"
            title={ASSET_KIND_LABELS.demo_video}
            addLabel="+ 시연 영상 추가"
            testIdPrefix="assignment-demo-video-asset"
            rows={demoVideoAssets}
            onChange={setDemoVideoAssets}
            disabled={isPastDeadline}
            targetRefPrefix={demoVideoTargetRef ?? undefined}
          />
          <AssetKindSection
            kind="demo_url"
            title={ASSET_KIND_LABELS.demo_url}
            addLabel="+ 데모 URL 추가"
            testIdPrefix="assignment-demo-url-asset"
            rows={demoUrlAssets}
            onChange={setDemoUrlAssets}
            disabled={isPastDeadline}
          />

          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-semibold">요구사항 체크리스트</h2>
            {data.requirements.map((requirement) => (
              <RequirementField
                key={requirement.id}
                requirement={requirement}
                state={requirementStates[requirement.id] ?? { isMet: false, note: "", evidence: [] }}
                onChange={(next) =>
                  setRequirementStates((prev) => ({ ...prev, [requirement.id]: next }))
                }
                disabled={isPastDeadline}
                testId={`assignment-requirement-${requirement.id}`}
                assets={submission?.assets ?? []}
              />
            ))}
          </section>

          {!isPastDeadline && (
            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={saveState.status === "saving"}
                data-testid="assignment-submit-button"
                className="w-fit rounded-sm border border-ink bg-ink px-6 py-2 text-sm text-paper disabled:opacity-50"
              >
                {saveState.status === "saving" ? "저장 중..." : submission ? "수정 사항 저장" : "제출하기"}
              </button>
              {saveState.status === "error" && (
                <p role="alert" data-testid="assignment-submit-error" className="text-sm text-attention">
                  {saveState.message}
                </p>
              )}
              {saveState.status === "done" && (
                <p data-testid="assignment-submit-success" className="text-sm text-verified">
                  저장되었습니다. 마감 전까지 몇 번이든 다시 수정할 수 있습니다.
                </p>
              )}
            </div>
          )}

          {isPastDeadline && submission !== null && <ScoreSection score={score} />}
        </>
      )}
    </main>
  );
}

// 마감 후 내 Score 와 판정 근거(#210, ADR-0006) — 과제에는 이의제기가 없다
// (스펙 #197 Out of Scope). 점수에 이견이 있으면 갈 곳은 화면(운영자 이의)이
// 아니라 사람(강사)이라는 것을 여기서 분명히 말한다.
function ScoreSection({ score }: { score: ScoreState }) {
  return (
    <section
      className="flex flex-col gap-3 border-t border-rule pt-6"
      data-testid="assignment-score-section"
    >
      <h2 className="text-lg font-semibold">채점 결과</h2>

      {score.status === "loading" && (
        <p data-testid="assignment-score-loading">불러오는 중...</p>
      )}
      {score.status === "not-scored" && (
        <p data-testid="assignment-score-not-scored" className="text-sm text-ink/70">
          아직 채점되지 않았습니다. 조금만 기다려주세요.
        </p>
      )}
      {score.status === "error" && (
        <p role="alert" data-testid="assignment-score-error" className="text-sm text-attention">
          채점 결과를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}
      {score.status === "ready" && <ScoreSummary score={score.data} testIdPrefix="assignment-score" />}

      {/* 이의제기가 없다는 사실은 채점 결과와 무관하게(로딩·미채점 포함) 항상
          알린다 — 학생이 언제 이 화면을 보든 "다음에 이견이 있으면 어디로
          가야 하는가"를 미리 알아야 한다(스펙 #197 인수조건). */}
      <p className="text-sm text-ink/70" data-testid="assignment-no-appeal-notice">
        과제에는 이의제기 절차가 없습니다. 점수에 이견이 있으면 강사에게 직접 문의해 주세요.
      </p>
    </section>
  );
}
