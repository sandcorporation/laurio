"use client";

// 제출 폼 (FE-10, #35, ADR-0014). Codemit에서 가장 고유한 화면이다.
//
// 지켜야 할 비대칭: 소스코드는 필수(플랫폼의 "강제하지 않고 배지로 신호한다"
// 원칙의 유일한 예외 — ADR-0014)이고, 시연 영상·데모 URL·테스트 계정은 비워도
// 제출이 성공한다. 이 파일에서 그 둘을 같은 방식으로 다루면 안 된다.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { checkGithubRepositoryUrl } from "@codemit/bff-client/repository-url";
import type { components } from "@codemit/bff-client/schema";

import { ErrorNote, PageHeader, PageShell, SectionHeading, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import { formatSubmitCountdown } from "@/lib/contest-format";
import { NEXT_ACTION_LABELS } from "@/lib/participation/use-my-participation";
import { ScoreSummary } from "@/lib/submissions/score-summary";
import { ASSET_KIND_LABELS } from "@/lib/submissions/types";
import { useDeadlineRefetch } from "@/lib/submissions/use-deadline-refetch";
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

// #190 이후 제출작은 자료 목록을 담는다(ADR-0027) — 종류는 다섯: 전체 소스코드
// (필수, 최소 1개), 시연 영상·스크린샷(#264, ADR-0036)·데모 URL(권장), GitHub
// 저장소(권장, 공개 저장소는 채점에 반영된다). `EditableAsset[]`을 종류별로
// 따로 두는 이유는 종류마다 값 편집 UI(업로드 vs URL 텍스트)와 허용되는 부가
// 필드(테스트 계정은 demo_url뿐)가 달라서다.
const KNOWN_ASSET_KINDS = new Set([
  "source",
  "demo_video",
  "screenshot",
  "demo_url",
  "repository",
]);

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
      refFound: asset.repository_ref_found,
      commitSha: asset.commit_sha,
      retentionDeadline: asset.demo_video_retention_deadline,
      retentionExpired: asset.demo_video_destroyed,
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
function repositoryValue(raw: string): string {
  const check = checkGithubRepositoryUrl(raw);
  return check !== null && check.ok ? check.url : raw.trim();
}

function rowsToAssetsIn(rows: EditableAsset[], kind: string): SubmissionIn["assets"] {
  return rows
    .filter((row) => row.value.trim() !== "")
    .map((row, index) => ({
      ...(row.id != null ? { id: row.id } : {}),
      kind,
      // 저장소는 끝의 .git·슬래시 같은 것을 정리한 주소로 보낸다(강의실과 같은 판정).
      value: kind === "repository" ? repositoryValue(row.value) : row.value.trim(),
      label: row.label.trim(),
      test_account: kind === "demo_url" ? row.testAccount.trim() : "",
      order: index,
      // 방금 업로드한 File의 MIME 타입(#241) — 기존 자료를 그대로 불러온 행에는
      // 없다(서버가 다시 내주지 않는다). 그래도 안전하다: value가 안 바뀐 자료의
      // content_type은 서버가 건드리지 않는다(`submissions.api._merge_assets`).
      content_type: row.contentType ?? "",
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

// 채점 결과 (#248) — `next_action`이 이미 "채점이 끝났는가"를 답하므로, 이
// 상태는 그 뒤에 오는 조회 하나만 감싼다("불러오는 중"·"불러오지 못함"·"됐음"
// 셋). 채점 전 두 상태(마감 전/채점 대기)는 `next_action`만으로 이미 구별되어
// 조회 자체를 하지 않는다 — 아래 `ScoreSection` 참고.
type OwnScore = components["schemas"]["OwnScoreOut"];
type ScoreState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; data: OwnScore };

export default function SubmitPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [reloadTick, setReloadTick] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const [sourceAssets, setSourceAssets] = useState<EditableAsset[]>([createEmptyAsset()]);
  const [demoVideoAssets, setDemoVideoAssets] = useState<EditableAsset[]>([]);
  const [screenshotAssets, setScreenshotAssets] = useState<EditableAsset[]>([]);
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
  // 무료 공모전 전용(#416, ADR-0048) — 「수상작의 소스는 개최자가 볼 수
  // 있습니다」 동의 체크박스. 이미 동의한 적이 있으면(수정 화면 재방문)
  // 체크된 채로 시작한다 — 제출마다 다시 확인하는 것이지 처음부터 매번
  // 비워 두는 것이 아니다.
  const [sourceAccessConsent, setSourceAccessConsent] = useState(false);
  const [score, setScore] = useState<ScoreState>({ status: "idle" });
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
    setScreenshotAssets(assetsOfKind(assets, "screenshot"));
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
        return setLoad({ status: "error", message: "공모전 정보를 불러오지 못했습니다." });
      }
      if (!verification.ok) {
        return setLoad({ status: "error", message: "본인확인 상태를 확인하지 못했습니다." });
      }

      // **`verified`가 아니어도 조회한다**(#250, ADR-0025) — 신원 파기(EXPIRED)
      // 는 실명·CI 등 신원 정보를 지우는 것이지 그 사람이 낸 제출물을 감추는
      // 것이 아니다. 예전에는 `verified`일 때만 이 요청을 보내, 2년 쉬고
      // 돌아온 사람(신원만 파기된 채 로그인은 그대로 되는 상태)에게 자기
      // 제출물이 통째로 사라진 것처럼 보였다. 쓰기(생성·수정)는 여전히
      // 서버가 `_require_verification`으로 막는다 — 여기서 여는 것은 읽기뿐이다.
      //
      // **다만 `unverified`·`underage`는 건너뛴다.** 이 둘은 애초에 제출물을
      // 만든 적이 없는 상태다 — 쓰기(`create_submission`)가 그 시점에 이미
      // `verified`를 요구하므로, `unverified`(Verification 행 자체가 없음)나
      // `underage`인 계정에 제출물이 있는 것은 구조적으로 불가능하다. 한 번
      // `verified`였다가 다른 CI로 `underage`가 되는 경로도 없다 — ADR-0025의
      // `would_change_identity`가 CI가 다른 재확인 자체를 거부한다. 그래서 이
      // 두 상태에서는 조회해 봐야 항상 404 — 낼 게 없어 아래에서 어차피 전체
      // 화면을 본인확인 안내로 막을 상태에, 처음 방문할 때마다(가장 흔한
      // 경로 — 누구나 여기서 시작한다) 헛수고인 요청을 하나 더 보내지 않는다.
      // 무료 공모전(#416, ADR-0048)은 본인확인 자체를 요구하지 않는다 — 그
      // 계정에 Verification 행이 아예 없어도(`unverified`) 이미 제출했을 수
      // 있으므로, 무료 공모전이면 이 조회를 건너뛰지 않는다.
      let submission: SubmissionOut | null = null;
      if (
        contest.data.is_free ||
        (verification.data.status !== "unverified" && verification.data.status !== "underage")
      ) {
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
      setSourceAccessConsent(submission?.source_access_consent_at != null);
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

  // **판정은 서버 하나뿐이다**(#247). 예전에는 이 화면이 `now >= deadlineAt`을
  // 직접 비교해 "마감됐다"를 스스로 판단했다 — 그 판정기가 하나 더 생기면
  // 나중에 새 상태(채점 대기·심사 중 등)가 생겨도 이 화면은 "마감 전/후" 둘로만
  // 나뉜 채 조용히 틀린 것을 말한다. `next_action`(`SubmissionOut`, 「내 참가
  // 현황」과 같은 판정기 `submissions.participation.next_action_for`)이 이미
  // "지금 무엇을 해야/기다려야 하는가"를 답한다 — 화면은 그 값만 쓴다.
  //
  // 아직 한 번도 제출하지 않았으면(`submission === null`) Submission 단위
  // 판정 자체가 없다 — 그때는 폼을 열어 둔다. 마감을 넘긴 뒤의 첫 시도는
  // 여전히 서버가 거절한다(`_reject_if_past_deadline`, 409) — 폼을 안 주는
  // 것과 서버가 거절하는 것 둘 다 필요하다는 원칙에서, 여기서는 후자만 선다.
  const currentSubmission = load.status === "ready" ? load.submission : null;
  const hasSubmission = currentSubmission !== null;
  const nextAction = currentSubmission?.next_action ?? null;
  // **판정기가 둘로 갈리지 않는다**(#250). 본인확인이 `verified`가 아니면
  // (신원 파기로 `expired`가 된 경우 포함) 마감 전이어도 수정은 막혀야
  // 하는데, 그 판단을 여기서 다시 내리지 않는다 — `next_action_for`
  // (`submissions/participation.py`)가 `update_submission`이 실제로 보는
  // 조건(`_reject_if_past_deadline` + `_require_verification`)을 그대로
  // 재사용해 이미 `needs_reverification`을 돌려준다. 아래는 그 값 하나만
  // 본다 — `can_edit_submission`일 때만 폼을 연다.
  const canEdit = !hasSubmission || nextAction === "can_edit_submission";
  const stateLabel = nextAction !== null ? NEXT_ACTION_LABELS[nextAction].text : null;

  // 채점이 됐는지도 `next_action`이 이미 답한다(#248) — `next_action_for`가
  // `hasattr(submission, "score")`를 그 경계로 쓰므로, 마감 전 두 값
  // (`can_edit_submission`·`needs_reverification`, #250)과 채점 대기
  // (`awaiting_scoring`) 셋만 아니면 Score가 있다. **404로 짐작하지 않는다**
  // — 조회 자체를 그 값이 "있다"고 말할 때만 보낸다.
  const hasScore =
    nextAction !== null &&
    nextAction !== "can_edit_submission" &&
    nextAction !== "needs_reverification" &&
    nextAction !== "awaiting_scoring";

  useEffect(() => {
    if (!hasScore || currentSubmission === null) {
      setScore({ status: "idle" });
      return;
    }
    let cancelled = false;
    setScore({ status: "loading" });
    void bffClient
      .get<OwnScore>(`/api/backend/submissions/${currentSubmission.id}/score`)
      .then((result) => {
        if (cancelled) return;
        if (!result.ok) {
          setScore({ status: "error" });
          return;
        }
        setScore({ status: "ready", data: result.data });
      });
    return () => {
      cancelled = true;
    };
  }, [hasScore, currentSubmission]);

  // 시계가 마감을 넘는 순간 제출물을 한 번 다시 불러와 `next_action`을
  // 갱신한다(#247, #248) — 판정기는 여전히 서버 하나다(`useDeadlineRefetch` 참고).
  //
  // `applySubmissionAssets`는 부르지 않는다 — 그 시점에 사용자가 폼에 입력해
  // 둔 것(아직 저장 전)을 서버 값으로 조용히 덮어쓰면 안 된다. 대신
  // `next_action`이 갱신되어 `canEdit`이 꺼지고, 폼은 지금까지 입력한 값 그대로
  // 잠긴다 — "더 이상 저장은 안 되지만 방금 쓴 것은 그대로 보인다".
  useDeadlineRefetch({
    now,
    deadlineAt,
    canEdit,
    hasSubmission,
    path: `/api/backend/contests/${contestId}/submissions/me`,
    onResult: (submission) =>
      setLoad((prev) => (prev.status === "ready" ? { ...prev, submission } : prev)),
  });

  // #218(ADR-0030): 소스 또는 저장소 중 하나만 있으면 제출할 수 있다 — 그래서
  // "필수" 배지·경고는 더 이상 소스 하나에 고정되지 않는다. 저장소만 있고
  // 그 저장소 전부가 아직 공개로 확인되지 않았으면(비어 있거나 아직 확인 중),
  // "마감까지 공개로 두지 않으면 0%"를 미리 보여준다 — 제출 시점에는 공개 여부를
  // 알 수 없으므로(ADR-0027) 이 경고는 언제나 뜬다, 배지 자체가 그 불확실성을
  // 이미 보여준다.
  const hasFilledSource = sourceAssets.some((row) => row.value.trim() !== "");
  const hasFilledRepository = repositoryAssets.some((row) => row.value.trim() !== "");
  const showRepositoryOnlyWarning = !hasFilledSource && hasFilledRepository;

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
    const hasRepository = repositoryAssets.some((row) => row.value.trim() !== "");
    // #218(ADR-0030): 소스 또는 GitHub 저장소 중 최소 하나만 있으면 된다 —
    // 저장소만 낸 제출은 마감까지 공개로 남지 않으면 채점이 0%를 남긴다(위
    // repository-only-warning 배너가 그 사실을 미리 보여준다).
    if (!hasSource && !hasRepository) {
      setSaveState({
        status: "error",
        message: "소스코드 또는 GitHub 저장소 중 최소 하나가 필요합니다.",
      });
      return;
    }
    // 저장소 주소가 SSH·파일 주소 같은 모양이면 서버에 보내기 전에 막는다 — 그 칸 아래에
    // 이미 이유와 고칠 주소가 떠 있다.
    if (repositoryAssets.some((row) => checkGithubRepositoryUrl(row.value)?.ok === false)) {
      setSaveState({ status: "error", message: "저장소 주소를 확인해 주세요 — 칸 아래에 이유가 있습니다." });
      return;
    }
    // 무료 공모전(#416) — 동의 없이는 서버가 어차피 422로 거절하지만, 폼
    // 단계에서 먼저 막아 헛된 왕복을 줄인다(화면이 감추는 것과 서버가
    // 거절하는 것은 둘 다 필요하다는 이 저장소의 규율).
    if (load.contest.is_free && !sourceAccessConsent) {
      setSaveState({
        status: "error",
        message: "수상작의 소스는 개최자가 볼 수 있습니다 — 동의해야 제출할 수 있습니다.",
      });
      return;
    }

    setSaveState({ status: "saving" });
    // 직전 저장의 알림은 여기서 지운다 — 안 그러면 이번 저장이 아무 것도 풀지
    // 않았는데도 옛 문구가 그대로 남는다.
    setUnlinkedEvidenceCount(0);

    const assets: SubmissionIn["assets"] = [
      ...rowsToAssetsIn(sourceAssets, "source"),
      ...rowsToAssetsIn(demoVideoAssets, "demo_video"),
      ...rowsToAssetsIn(screenshotAssets, "screenshot"),
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
        // 이 폼이 모르는 종류라 content_type도 모른다 — value가 안 바뀐 자료라
        // 서버가 그대로 무시한다(위 rowsToAssetsIn과 같은 이유, #241).
        content_type: "",
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
      // 유료 공모전은 이 필드를 서버가 무시한다 — 그래도 무조건 함께 보낸다
      // (무료·유료 갈래를 페이로드 구성 단계에서 나누지 않는다).
      source_access_consent: load.contest.is_free && sourceAccessConsent,
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
        <p data-testid="submit-not-found">공모전을 찾을 수 없습니다.</p>
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

  // 낼 것이 아무것도 없을 때만(한 번도 제출하지 않았을 때) 화면 전체를 본인확인
  // 안내로 막는다(#250). 이미 낸 제출물이 있으면 — 신원이 파기(`expired`)됐어도
  // — 아래로 내려가 그 내용을 읽기 전용으로 보여준다(수정 자체를 막는 판정은
  // `next_action`이 `needs_reverification`으로 이미 하고 있다, 아래 `canEdit`
  // 참고). ADR-0025가 지우는 것은 신원 정보(실명·생년월일·CI/DI·전화번호)이지
  // 제출물이 아니다.
  //
  // `verification.status`로 직접 판정한다 — 여기는 아직 Submission이 없을 수
  // 있는 자리라 `next_action`(있어도 없어도 되는 값)에 기댈 수 없다. 이론상
  // `withdrawn`(탈퇴)도 이 조건을 만족하지만 실제로 이 화면에 닿지 않는다 —
  // 탈퇴 계정은 `User.is_active`가 꺼져 로그인 자체가 막힌다(ADR-0025) — 그래도
  // 값 자체는 `underage`와 다르지 않게 다룬다: 재확인 버튼은 감추고 이유만
  // 보여준다(`VerificationReason`).
  if (!contest.is_free && verification.status !== "verified" && !hasSubmission) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-10">
        <ErrorNote>
          <span data-testid="verification-required">본인확인을 완료해야 제출할 수 있습니다.</span>
        </ErrorNote>
        <VerificationReason verification={verification} />
        <VerifyActions
          verification={verification}
          verifying={verifying}
          verifyError={verifyError}
          portOneConfig={portOneConfig}
          onVerifyDev={handleVerifyDev}
          onVerifyLive={handleVerifyLive}
        />
      </main>
    );
  }

  const userId = session.status === "authenticated" ? session.user.id : null;
  const sourceTargetRef = userId ? `submission:${contestId}:${userId}:source` : null;
  const demoVideoTargetRef = userId ? `submission:${contestId}:${userId}:demo-video` : null;
  const screenshotTargetRef = userId ? `submission:${contestId}:${userId}:screenshot` : null;

  return (
    <PageShell>
      <div className="flex flex-col gap-8">
      <PageHeader
        title={`${contest.title} — 제출`}
        titleTestId="submit-contest-title"
        description={
          // **상태 문구는 항상 같은 자리에 있다**(#247) — 마감 전(수정 가능)·채점
          // 대기·심사 중·마감 뒤 어느 상태로 들어와도 이 한 줄이 "지금 무엇을
          // 기다리는가/할 수 있는가"를 말한다. 아직 한 번도 제출하지 않았을 때는
          // 보여줄 상태가 없으므로(제출물 자체가 없다) 남은 시간만 보여준다 —
          // 이건 판정이 아니라 시계 표시다.
          <span
            className={`font-mono ${canEdit ? "text-ink" : "text-attention"}`}
            data-testid="submit-state-band"
          >
            {stateLabel ?? formatSubmitCountdown(contest.deadline_at, new Date(now))}
          </span>
        }
      />

      {hasSubmission && !canEdit && (
        <div className="flex flex-col gap-3">
          {/* **상태 문구가 둘로 갈리지 않는다**(#250). 여기도 위 상태 배너와
              같은 `stateLabel`(=`next_action`의 문구)만 쓴다 — 본인확인이
              필요한 경우 그 값 자체가 이미 "본인확인 필요"라, 이 알림과 위
              배너가 같은 렌더에서 서로 다른 말을 하는 일이 없다. */}
          <ErrorNote>
            <span data-testid="edit-locked-notice">지금은 제출물을 수정할 수 없습니다 — {stateLabel}</span>
          </ErrorNote>
          {/* 신원 파기(EXPIRED)로 본인확인이 풀린 경우(#250, ADR-0025) — 아래
              내용은 그대로 읽히지만, 새로 내거나 고치려면 본인확인을 다시
              마쳐야 한다는 것과 그 길을 여기서 바로 준다. 조건은 `next_action`
              값 하나다 — 화면이 별도로 "본인확인이 필요한가"를 다시 판정하지
              않는다. */}
          {nextAction === "needs_reverification" && (
            <div
              className="flex flex-col items-start gap-2 border border-rule bg-surface p-3"
              data-testid="resubmit-verification-notice"
            >
              <VerificationReason verification={verification} />
              <VerifyActions
                verification={verification}
                verifying={verifying}
                verifyError={verifyError}
                portOneConfig={portOneConfig}
                onVerifyDev={handleVerifyDev}
                onVerifyLive={handleVerifyLive}
              />
            </div>
          )}
        </div>
      )}

      <section className="flex flex-col gap-2" data-testid="completion-indicator" data-percent={completion.percent}>
        <p className="text-sm">
          완성도 {completion.percent}% — 체크리스트 증거 연결 {completion.linked}/{completion.total},
          권장 항목 {completion.optionalFilled}/3
        </p>
        <div className="h-2 w-full border border-rule">
          <div className="h-full bg-verified" style={{ width: `${completion.percent}%` }} />
        </div>
      </section>

      <p className="text-sm text-ink" data-testid="source-privacy-notice">
        제출한 소스코드와 GitHub 저장소는 선정 전까지 개최자에게 공개되지 않습니다.
        AI 채점과 플랫폼만 열람합니다.
      </p>

      <AssetKindSection
        kind="source"
        title={ASSET_KIND_LABELS.source}
        helperText={
          // 상한 숫자는 PlatformPolicy.max_source_assets의 코드 기본값이다
          // (backend/policies/models.py) — 운영자가 정책 화면 밖 API로 바꿀 수
          // 있는 값이라 이 문구가 항상 실제 상한과 같다고 보장하지 않는다.
          // 공개 앱 BFF가 `/api/operator/*`를 막아(#43) 이 화면이 살아있는
          // 값을 직접 물어볼 길이 없다(asset-kind-section.tsx 상단 주석과 같은
          // 이유) — 그래서 "기본값"이라고 못박고, 실제로 넘으면 여전히 서버가
          // 저장 시점에 422로 정확한 한도를 알려준다. **이 기본값이 바뀌면
          // (policies/models.py) 여기와 docs/features/frontend.md의 같은
          // 문장도 같이 고친다.**
          <p className="text-sm text-ink/70" data-testid="source-helper">
            여러 파일을 zip 하나로 묶어 올리는 것이 기본입니다 — 압축하지 않은 파일
            하나만 올려도 받습니다. 기본값은 5개까지이고, 그보다 많이 올리면
            저장할 때 안내합니다.
          </p>
        }
        // #218: 저장소가 채워져 있으면 소스는 더 이상 필수가 아니다 — 마지막
        // 빈 행도 지울 수 있어야 하고, "없으면 거부됩니다" 경고도 뜨면 안 된다.
        required={!hasFilledRepository}
        addLabel="+ 소스코드 추가"
        testIdPrefix="source-asset"
        rows={sourceAssets}
        onChange={setSourceAssets}
        disabled={!canEdit}
        targetRefPrefix={sourceTargetRef ?? undefined}
      />

      <AssetKindSection
        kind="repository"
        title={ASSET_KIND_LABELS.repository}
        helperText={
          <p className="text-sm text-ink/70" data-testid="repository-helper">
            공개 저장소는 마감 전 자동으로 확인되어 채점에 반영됩니다(비워도 제출됩니다).
            소스코드가 없다면 저장소만으로도 제출할 수 있습니다 — 대신 마감까지
            공개 상태여야 합니다.
          </p>
        }
        addLabel="+ 저장소 추가"
        testIdPrefix="repository-asset"
        rows={repositoryAssets}
        onChange={setRepositoryAssets}
        disabled={!canEdit}
      />

      {showRepositoryOnlyWarning && (
        <ErrorNote>
          <span data-testid="repository-only-warning">
            소스코드 없이 저장소만 냈습니다 — 마감까지 모든 저장소를 공개 상태로
            두지 않으면 채점이 0%가 됩니다.
          </span>
        </ErrorNote>
      )}

      <AssetKindSection
        kind="demo_video"
        title={ASSET_KIND_LABELS.demo_video}
        addLabel="+ 시연 영상 추가"
        testIdPrefix="demo-video-asset"
        rows={demoVideoAssets}
        onChange={setDemoVideoAssets}
        disabled={!canEdit}
        targetRefPrefix={demoVideoTargetRef ?? undefined}
      />

      <AssetKindSection
        kind="screenshot"
        title={ASSET_KIND_LABELS.screenshot}
        helperText={
          <p className="text-sm text-ink/70" data-testid="screenshot-helper">
            결과물의 화면을 찍은 이미지입니다(png/jpeg/webp/gif). 마감 후 데모·영상과
            함께 공개됩니다.
          </p>
        }
        addLabel="+ 스크린샷 추가"
        testIdPrefix="screenshot-asset"
        rows={screenshotAssets}
        onChange={setScreenshotAssets}
        disabled={!canEdit}
        targetRefPrefix={screenshotTargetRef ?? undefined}
      />

      <AssetKindSection
        kind="demo_url"
        title={ASSET_KIND_LABELS.demo_url}
        addLabel="+ 데모 URL 추가"
        testIdPrefix="demo-url-asset"
        rows={demoUrlAssets}
        onChange={setDemoUrlAssets}
        disabled={!canEdit}
      />

      <section className="flex flex-col gap-3">
        <SectionHeading title="요구사항 체크리스트" />
        <p className="text-xs text-ink/60" data-testid="evidence-asset-picker-notice">
          근거가 가리킬 수 있는 자료 목록은 마지막으로 저장된 자료 기준입니다 — 방금
          추가한 자료는 한 번 저장한 뒤에 근거로 연결할 수 있습니다. 소스코드를
          둘 이상 냈다면, 그 중 어느 것을 가리키는지 반드시 골라야 합니다 —
          아니면 채점하는 쪽도 어느 소스의 어디를 봐야 하는지 알 수 없습니다.
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
            disabled={!canEdit}
            testId={`requirement-${requirement.id}`}
            assets={submission?.assets ?? []}
          />
        ))}
      </section>

      {canEdit && (
        <div className="flex flex-col gap-2">
          {contest.is_free && (
            <label
              className="flex items-start gap-2 border border-rule bg-surface px-3 py-2.5 text-sm"
              data-testid="source-access-consent-label"
            >
              <input
                type="checkbox"
                checked={sourceAccessConsent}
                onChange={(event) => setSourceAccessConsent(event.target.checked)}
                data-testid="source-access-consent-checkbox"
              />
              <span>
                수상작의 소스는 개최자가 볼 수 있습니다 — 이 문장에 동의해야 제출할 수
                있습니다.
              </span>
            </label>
          )}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={saveState.status === "saving"}
            data-testid="submit-button"
            className={buttonClass("primary")}
          >
            {saveState.status === "saving"
              ? "저장 중..."
              : submission
                ? "수정 사항 저장"
                : "제출하기"}
          </button>
          {saveState.status === "error" && (
            <ErrorNote>
              <span data-testid="submit-error">{saveState.message}</span>
            </ErrorNote>
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

      {hasSubmission && currentSubmission !== null && nextAction !== null && (
        <ScoreSection nextAction={nextAction} score={score} submissionId={currentSubmission.id} />
      )}
      </div>
    </PageShell>
  );
}

// 자기 점수와 「다음 갈래」(#248) — 요구사항·자료를 다시 그리지 않는 이
// 화면에서 "낸 것이 그래서 어떻게 됐나"까지 한 곳에서 끝까지 읽는다.
//
// **점수가 없을 때 이유가 갈린다.** `next_action`이 이미 그 경계를 답한다 —
// 마감 전 두 값(`can_edit_submission`·`needs_reverification`, #250 — 후자는
// 본인확인이 풀린 채 마감 전인 경우로, 마감 전이라는 사실 자체는 같아서 같은
// 문장을 쓴다)과 채점 대기(`awaiting_scoring`)는 자기 문장을 그대로 말하고,
// 그 셋이 아니면 Score가 있다는 뜻이라 조회한다. 자동
// 0%(ADR-0030/0031)의 사유는 백엔드가 이미 참가자용 한 문장으로 접어 보낸다
// (`OwnScoreOut.reasoning`, #246) — 여기서 `scoring_basis`를 다시 해석하지
// 않는다.
//
// **판정 근거 전문·이의 제기·인수 확인은 링크로 간다.** 이 화면이 그 내용을
// 다시 그리면 이의 화면(`/console/participation/{id}/appeal`)과 언젠가
// 어긋난다. 인수 링크는 `next_action === "awaiting_handover_release"`일
// 때만 보인다 — 서버가 준 상태값이 유일한 판정 근거다.
function ScoreSection({
  nextAction,
  score,
  submissionId,
}: {
  nextAction: NonNullable<SubmissionOut["next_action"]>;
  score: ScoreState;
  submissionId: number;
}) {
  return (
    <section
      className="flex flex-col gap-3 border-t border-rule pt-6"
      data-testid="submit-score-section"
    >
      <SectionHeading title="채점 결과" />

      {nextAction === "can_edit_submission" || nextAction === "needs_reverification" ? (
        <p data-testid="submit-score-before-deadline" className="text-sm text-ink/70">
          아직 마감 전이라 채점이 시작되지 않았습니다.
        </p>
      ) : nextAction === "awaiting_scoring" ? (
        <p data-testid="submit-score-awaiting" className="text-sm text-ink/70">
          마감되었고 채점을 기다리는 중입니다.
        </p>
      ) : score.status === "loading" ? (
        <p data-testid="submit-score-loading">불러오는 중...</p>
      ) : score.status === "error" ? (
        <ErrorNote>
          <span data-testid="submit-score-error">채점 결과를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.</span>
        </ErrorNote>
      ) : score.status === "ready" ? (
        <>
          <ScoreSummary
            score={score.data}
            testIdPrefix="submit-score"
            reasoningLink={{
              href: `/console/participation/${submissionId}/appeal`,
              label: "판정 근거 전문·이의 제기 보기 →",
            }}
          />
          {/* 인수는 지금 실제로 할 수 있을 때만 링크한다 — 서버가 준
              `next_action` 하나가 그 판단이다. */}
          {nextAction === "awaiting_handover_release" && (
            <Link
              className="text-sm underline"
              href={`/console/participation/${submissionId}/handover`}
              data-testid="submit-score-handover-link"
            >
              인수 자료 올리기 →
            </Link>
          )}
        </>
      ) : null}
    </section>
  );
}

// 본인확인이 필요한 이유 한 줄(#250) — 「제출할 것이 아무것도 없어 화면 전체를
// 막는 경우」와 「이미 낸 것은 읽히지만 새로 내거나 고치려면 다시 확인해야
// 하는 경우」 둘 다 같은 문구를 쓴다. 신원 파기(`expired`, ADR-0025)는
// `underage`가 아니므로 일반 안내로 떨어진다 — 다시 확인하면 그대로 통과한다.
//
// **`console/contests/new/page.tsx`에 거의 같은 블록이 이미 있다**(공모전
// 개최의 본인확인 게이트, `grill-verification-required` 등 testid를 쓴다) —
// 이 컴포넌트로 옮겨 공유하지 않는다. 그 화면의 testid는 이 화면과 다른
// 접두어(`grill-*`)를 쓰고 있어, 공유하려면 testid를 매개변수화하거나 그
// 화면의 e2e testid를 바꿔야 한다 — 이 티켓의 스코프는 이 제출 화면과
// `asset-kind-section.tsx`뿐이라(#250 지시), 관계없는 화면의 testid를
// 건드리는 대가를 감수하지 않는다. 셋째 자리가 또 생기면 그때 공유 위치를
// 만든다.
function VerificationReason({ verification }: { verification: VerificationStatusOut }) {
  return (
    <p className="text-sm text-ink" data-testid="verification-reason">
      {verification.status === "underage"
        ? verification.reason || "만 19세 미만은 본인확인을 완료할 수 없습니다."
        : "휴대폰 본인확인을 먼저 마쳐주세요."}
    </p>
  );
}

// 본인확인으로 가는 버튼 둘(dev fake·실물 PortOne) — 위 두 자리(전체 화면
// 안내, 읽기 전용 화면의 인라인 배너)가 같은 동작을 공유한다.
function VerifyActions({
  verification,
  verifying,
  verifyError,
  portOneConfig,
  onVerifyDev,
  onVerifyLive,
}: {
  verification: VerificationStatusOut;
  verifying: boolean;
  verifyError: string | null;
  portOneConfig: ReturnType<typeof getPortOneBrowserConfig>;
  onVerifyDev: () => void;
  onVerifyLive: () => void;
}) {
  return (
    <>
      {verification.status !== "underage" && (
        <button
          type="button"
          onClick={onVerifyDev}
          disabled={verifying}
          data-testid="verify-now-dev"
          className={buttonClass("secondary")}
        >
          {verifying ? "확인 중..." : "지금 본인확인하기(dev)"}
        </button>
      )}
      {verification.status !== "underage" && portOneConfig && (
        <button
          type="button"
          onClick={onVerifyLive}
          disabled={verifying}
          data-testid="verify-now-live"
          className={buttonClass("secondary")}
        >
          {verifying ? "확인 중..." : "실제 본인확인하기(PortOne)"}
        </button>
      )}
      {verifyError && (
        <ErrorNote>
          <span data-testid="verify-live-error">{verifyError}</span>
        </ErrorNote>
      )}
    </>
  );
}
