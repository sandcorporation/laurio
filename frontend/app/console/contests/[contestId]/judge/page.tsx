"use client";

// 심사 비교 화면 — Requirement 축 매트릭스 + Award (FE-11, #36, ADR-0006, ADR-0014).
//
// 심사기간은 7일인데 앱 하나당 설치·가입·탐색에만 20~30분이 든다(REQUEST.md) —
// Sponsor가 일곱 건을 다 설치해볼 수 없으므로, Requirement를 행으로 Submission을
// 열로 놓고 각 칸에 Developer가 연결한 Evidence를 나란히 보여준다.
//
// 이 화면이 절대 어기면 안 되는 두 가지 — 둘 다 "보여주지 않는다"다:
//
//   1. 소스코드는 이 화면 어디에도 없다(선정 전이라 ADR-0014). 대신 "선정하면
//      소스가 열린다"는 것을 누르기 전에 알 수 있어야 한다.
//   2. AI 채점 점수(Score — 필수 요구사항 달성률)는 이 화면 어디에도 없다 — 선정은 Sponsor의
//      판단이고 Score는 무응답 배분 대상을 가릴 때만 쓰인다(ADR-0006).
//
// 완성도(#884 ADR-0072, #904 ADR-0073)는 Score 가 아니다 — 요구사항마다 AI 가 매긴 0~5 와 근거, 배점으로 합한
// 「37.4 / 45점」이다. 상금 배분에 쓰지 않는 참고 의견이라 개최자에게 보이고, 「완성도순」으로 열을 줄 세울 수 있다.
// 배점(1~10)은 마감 뒤에도 요구사항 행에서 고친다 — 서버가 AI 를 다시 부르지 않고 지금 배점으로 다시 계산한다.
//
// 두 값 모두 백엔드 comparison 스키마(submissions.schemas.ContestComparisonOut)
// 자체에 필드가 없다 — "존재하지만 안 보임"이 아니라 애초에 없다. 이 파일은 그
// 응답 객체를 그대로 신뢰해 렌더링만 한다 — 통째로 어딘가에 다시 직렬화해 넘기지
// 않는 한 하이드레이션 페이로드에도 새어나갈 값 자체가 없다.
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { ErrorNote, EmptyState, PageHeader, buttonClass } from "@/app/components/ui";
import { VideoLinkView } from "@/components/submissions/video-link-view";
import { requirementGradeLabel } from "@/lib/contests/grill-types";
import { BonusScoreEditor } from "./bonus-score-editor";
import { timestampSeconds, youtubeVideoId } from "@/lib/submissions/video-link";
import { badgeClass } from "@/lib/ui/classnames";
import { remainingTime, remainingTimeLabel } from "@/lib/contest-format";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import {
  EVIDENCE_KINDS,
  type AwardOut,
  type ComparisonSubmissionOut,
  type ContestComparisonOut,
} from "@/lib/submissions/types";
import {
  POINTS_OPTIONS,
  formatPoints,
  formatQualityTotal,
  orderSubmissions,
  type ComparisonQuality,
  type JudgeSortOrder,
} from "@/lib/submissions/quality";

type ContestMeta = { id: number; title: string; deadline_at: string; judging_ends_at: string | null };

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "forbidden"; message: string }
  | { status: "error"; message: string }
  | { status: "ready"; contest: ContestMeta; comparison: ContestComparisonOut };

type AwardState =
  | { status: "idle" }
  | { status: "confirming"; submissionId: number }
  | { status: "saving"; submissionId: number }
  | { status: "done"; result: AwardOut }
  | { status: "error"; message: string };

function evidenceKindLabel(kind: string): string {
  return EVIDENCE_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

export default function JudgeComparisonPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [award, setAward] = useState<AwardState>({ status: "idle" });
  const [sortOrder, setSortOrder] = useState<JudgeSortOrder>("submitted");
  const [pointsError, setPointsError] = useState<string | null>(null);
  const [savingPointsId, setSavingPointsId] = useState<number | null>(null);
  const [now, setNow] = useState(() => new Date());
  // 확인 위치(영상 타임스탬프)를 눌러 고른 재생 위치 — 제출작마다 하나(#910).
  const [playback, setPlayback] = useState<Record<number, { assetId: number; start: number }>>({});

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    // 실패의 뜻이 코드마다 다르다: 404 는 「없다」, 403 은 「남의 것」(서버 문구 그대로), 나머지는
    // 「못 불러왔다」. 401 은 클라이언트가 로그인으로 보낸다(#146).
    void Promise.all([
      bffClient.get<ContestMeta>(`/api/backend/contests/${contestId}`),
      bffClient.get<ContestComparisonOut>(`/api/backend/contests/${contestId}/submissions/compare`),
    ]).then(([contest, comparison]) => {
      if (cancelled) return;
      if (contest.ok && comparison.ok) {
        setLoad({ status: "ready", contest: contest.data, comparison: comparison.data });
        return;
      }
      if (contest.status === 404 || comparison.status === 404) {
        setLoad({ status: "not-found" });
        return;
      }
      if (!comparison.ok && comparison.status === 403) {
        setLoad({ status: "forbidden", message: comparison.detail });
        return;
      }
      setLoad({ status: "error", message: "심사 비교 정보를 불러오지 못했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, contestId]);

  const judgingEndsAt = load.status === "ready" ? load.contest.judging_ends_at : null;
  const judgingEnded = useMemo(
    () => (judgingEndsAt ? remainingTime(judgingEndsAt, now).status === "closed" : null),
    [judgingEndsAt, now],
  );

  async function changePoints(requirementId: number, points: number) {
    setPointsError(null);
    setSavingPointsId(requirementId);
    const saved = await bffClient.request<unknown>(
      `/api/backend/contests/${contestId}/requirements/${requirementId}/points`,
      { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ points }) },
    );
    if (!saved.ok) {
      setSavingPointsId(null);
      setPointsError(saved.detail);
      return;
    }
    // 합·만점·등수는 서버가 지금 배점으로 다시 계산한다 — 비교 응답을 다시 받는다.
    const comparison = await bffClient.get<ContestComparisonOut>(
      `/api/backend/contests/${contestId}/submissions/compare`,
    );
    setSavingPointsId(null);
    if (!comparison.ok) {
      setPointsError(comparison.detail);
      return;
    }
    setLoad((prev) => (prev.status === "ready" ? { ...prev, comparison: comparison.data } : prev));
  }

  // 가산(#905) — 마감 뒤 개최자가 제출작마다 매긴다. 합·등수가 바뀌니 비교 응답을 다시 받는다.
  async function rateBonus(submissionId: number, requirementId: number, score: number, memo: string) {
    const saved = await bffClient.request<unknown>(
      `/api/backend/contests/${contestId}/submissions/${submissionId}/bonus/${requirementId}`,
      { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ score, memo }) },
    );
    if (!saved.ok) return saved.detail || "저장하지 못했습니다.";
    const comparison = await bffClient.get<ContestComparisonOut>(
      `/api/backend/contests/${contestId}/submissions/compare`,
    );
    if (comparison.ok) {
      setLoad((prev) => (prev.status === "ready" ? { ...prev, comparison: comparison.data } : prev));
    }
    return null;
  }

  async function requestAward(submissionId: number) {
    setAward({ status: "saving", submissionId });
    const result = await bffClient.post<AwardOut>(`/api/backend/contests/${contestId}/award`, {
      submission_id: submissionId,
    });
    // 실패 문구는 서버가 준 것을 그대로 쓴다 — 심사기간이 지났다·이미 선정됐다는 각각 다른
    // 사실이고, 화면이 짐작해 다시 쓰면 갈라진다.
    if (!result.ok) {
      setAward({ status: "error", message: result.detail });
      return;
    }
    setAward({ status: "done", result: result.data });
  }

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="mx-auto max-w-6xl p-10">
        <p data-testid="compare-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "not-found") {
    return (
      <main className="mx-auto max-w-6xl p-10">
        <p data-testid="compare-not-found">공모전을 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (load.status === "forbidden") {
    return (
      <main className="mx-auto max-w-6xl p-10">
        <ErrorNote>
          <span data-testid="compare-forbidden">{load.message}</span>
        </ErrorNote>
      </main>
    );
  }

  if (load.status === "error") {
    return (
      <main className="mx-auto max-w-6xl p-10">
        <ErrorNote>
          <span data-testid="compare-load-error">{load.message}</span>
        </ErrorNote>
      </main>
    );
  }

  const { contest, comparison } = load;
  const columns = orderSubmissions(comparison.submissions, sortOrder);
  const awardedSubmissionId = award.status === "done" ? award.result.submission_id : null;

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 p-10">
      <div>
        <PageHeader title={`${contest.title} — 심사 비교`} titleTestId="compare-contest-title" />
        {judgingEndsAt ? (
          <div className="mt-2 flex flex-col gap-1">
            <p className="font-mono text-sm" data-testid="judging-deadline">
              심사 마감까지 {remainingTimeLabel(judgingEndsAt, now)}
              {judgingEnded ? " (심사기간 종료)" : ""}
            </p>
            <p className="text-sm text-ink" data-testid="judging-consequence-notice">
              심사기간 안에 선정하지 않으면, 그 이후 14일이 지나는 시점에 필수
              요구사항 달성률이 기준을 넘는 제출작들에게 상금 전액이 자동으로 1/N
              배분됩니다. 방치해도 상금이 개최자에게 돌아오지 않습니다.
            </p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-attention" data-testid="judging-not-started-notice">
            아직 심사기간이 시작되지 않았습니다 — 마감 후에 비교할 수 있습니다.
          </p>
        )}
      </div>

      <p className="text-sm text-ink" data-testid="source-hidden-notice">
        소스코드와 필수 요구사항 달성률은 이 화면 어디에도 표시되지 않습니다 — 소스는 선정
        전까지 공개되지 않고, 달성률은 무응답 배분 대상을 가릴 때만
        쓰입니다.
      </p>

      {comparison.submissions.length === 0 ? (
        <EmptyState>
          <span data-testid="compare-empty">아직 제출물이 없습니다.</span>
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex gap-2" role="group" aria-label="정렬" data-testid="judge-sort">
            <button
              type="button"
              className={buttonClass(sortOrder === "submitted" ? "primary" : "secondary", "sm")}
              aria-pressed={sortOrder === "submitted"}
              onClick={() => setSortOrder("submitted")}
              data-testid="judge-sort-submitted"
            >
              제출순
            </button>
            <button
              type="button"
              className={buttonClass(sortOrder === "quality" ? "primary" : "secondary", "sm")}
              aria-pressed={sortOrder === "quality"}
              onClick={() => setSortOrder("quality")}
              data-testid="judge-sort-quality"
            >
              완성도순
            </button>
          </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse" data-testid="comparison-matrix">
            <thead>
              <tr>
                <th className="border border-rule bg-surface p-3 text-left text-sm">
                  요구사항
                </th>
                {columns.map((submission) => (
                  <th
                    key={submission.submission_id}
                    className="border border-rule bg-surface p-3 text-left text-sm"
                    data-testid={`submission-header-${submission.submission_id}`}
                  >
                    <SubmissionColumnHeader
                      submission={submission}
                      isAwarded={awardedSubmissionId === submission.submission_id}
                      awardLocked={award.status === "done"}
                      award={award}
                      onAwardClick={() =>
                        setAward({ status: "confirming", submissionId: submission.submission_id })
                      }
                      onConfirm={() => requestAward(submission.submission_id)}
                      onCancel={() => setAward({ status: "idle" })}
                      playback={playback[submission.submission_id] ?? null}
                    />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr data-testid="quality-row">
                <th scope="row" className="border border-rule p-3 text-left align-top text-sm font-normal">
                  완성도
                </th>
                {columns.map((submission) => (
                  <td
                    key={submission.submission_id}
                    className="border border-rule p-3 align-top text-sm"
                    data-testid={`quality-${submission.submission_id}`}
                  >
                    <QualitySummary quality={submission.quality ?? null} />
                  </td>
                ))}
              </tr>
              {comparison.requirements.map((requirement) => {
                const isRequired = requirement.grade === "required";
                const isBonus = requirement.grade === "bonus";
                return (
                  <tr key={requirement.requirement_id} data-testid={`requirement-row-${requirement.requirement_id}`}>
                    <th
                      scope="row"
                      className="border border-rule p-3 text-left align-top text-sm font-normal"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={badgeClass(isRequired ? "attention" : "neutral")}
                          data-testid={`requirement-${requirement.requirement_id}-grade`}
                        >
                          {requirementGradeLabel(requirement.grade)}
                        </span>
                        <span>{requirement.text}</span>
                      </div>
                      <label className="mt-2 flex items-center gap-2 text-xs text-ink/70">
                        배점
                        <select
                          className="border border-rule bg-surface px-1 py-0.5 font-mono text-xs text-ink"
                          value={requirement.points}
                          disabled={savingPointsId === requirement.requirement_id}
                          onChange={(event) =>
                            void changePoints(requirement.requirement_id, Number(event.target.value))
                          }
                          data-testid={`requirement-${requirement.requirement_id}-points`}
                        >
                          {POINTS_OPTIONS.map((value) => (
                            <option key={value} value={value}>
                              {value}점
                            </option>
                          ))}
                        </select>
                      </label>
                    </th>
                    {columns.map((submission) => {
                      const qualityItem = submission.quality?.items.find(
                        (item) => item.item_id === requirement.requirement_id,
                      );
                      const entry = requirement.entries.find(
                        (e) => e.submission_id === submission.submission_id,
                      );
                      const isLinked = entry?.is_linked ?? false;
                      // 확인 위치는 판정과 무관한 안내다(#909, ADR-0074) — 충족 여부와 묶지 않고,
                      // 있으면 목록만 그린다. 비어 있다고 경고하지 않는다.
                      return (
                        <td
                          key={submission.submission_id}
                          className="border border-rule p-3 align-top text-sm"
                          data-testid={`cell-${requirement.requirement_id}-${submission.submission_id}`}
                          data-linked={isLinked ? "true" : "false"}
                          data-met={entry?.is_met ? "true" : "false"}
                        >
                          <div className="flex flex-col gap-1">
                            <p className={entry?.is_met ? "text-verified" : "text-ink"}>
                              {entry?.is_met ? "충족" : "미충족"}
                            </p>
                            {isLinked && (
                              <ul
                                className="flex flex-col gap-1"
                                data-testid={`cell-${requirement.requirement_id}-${submission.submission_id}-locations`}
                              >
                                {entry!.evidence.map((item, index) => {
                                  const text = `[${evidenceKindLabel(item.kind)}] ${item.value}`;
                                  const link =
                                    item.kind === "video_timestamp" && item.asset_id != null
                                      ? submission.assets.find(
                                          (a) => a.id === item.asset_id && a.kind === "video_link",
                                        )
                                      : undefined;
                                  const embedded = link != null && youtubeVideoId(link.value) !== null;
                                  return (
                                    <li key={index} className="font-mono text-xs text-ink">
                                      {link != null && embedded ? (
                                        <button
                                          type="button"
                                          className="text-left underline"
                                          data-testid={`evidence-play-${link.id}`}
                                          onClick={() =>
                                            setPlayback((prev) => ({
                                              ...prev,
                                              [submission.submission_id]: {
                                                assetId: link.id,
                                                start: timestampSeconds(item.value) ?? 0,
                                              },
                                            }))
                                          }
                                        >
                                          {text}
                                        </button>
                                      ) : link != null ? (
                                        <a
                                          href={link.value}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="underline"
                                          data-testid={`evidence-open-${link.id}`}
                                        >
                                          {text}
                                        </a>
                                      ) : (
                                        text
                                      )}
                                    </li>
                                  );
                                })}
                              </ul>
                            )}
                            {entry?.note && <p className="text-xs text-ink">{entry.note}</p>}
                          </div>
                          {isBonus ? (
                            <div className="mt-2 border-t border-rule pt-2">
                              <BonusScoreEditor
                                testId={`bonus-${requirement.requirement_id}-${submission.submission_id}`}
                                initialScore={
                                  submission.bonus_scores?.find((b) => b.requirement_id === requirement.requirement_id)
                                    ?.score ?? 0
                                }
                                initialMemo={
                                  submission.bonus_scores?.find((b) => b.requirement_id === requirement.requirement_id)
                                    ?.memo ?? ""
                                }
                                onSave={(score, memo) =>
                                  rateBonus(submission.submission_id, requirement.requirement_id, score, memo)
                                }
                              />
                            </div>
                          ) : qualityItem ? (
                            <div
                              className="mt-2 border-t border-rule pt-2"
                              data-testid={`quality-item-${requirement.requirement_id}-${submission.submission_id}`}
                            >
                              <p className="text-xs font-semibold">
                                항목 완성도 {qualityItem.score}/5 · {formatPoints(qualityItem.item_points)} /{" "}
                                {qualityItem.points}점
                              </p>
                              <p className="text-xs text-ink/70">{qualityItem.reasoning}</p>
                            </div>
                          ) : null}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </div>
      )}

      {award.status === "done" && (
        <p data-testid="award-success" className="text-sm text-verified">
          제출물 #{award.result.submission_id}을(를) 선정했습니다. 이 제출작의
          소스코드에 접근할 수 있습니다.
        </p>
      )}
      {pointsError && (
        <ErrorNote>
          <span data-testid="points-error">{pointsError}</span>
        </ErrorNote>
      )}
      {award.status === "error" && (
        <ErrorNote>
          <span data-testid="award-error">{award.message}</span>
        </ErrorNote>
      )}
    </main>
  );
}

function QualitySummary({ quality }: { quality: ComparisonQuality | null }) {
  if (quality === null) return <p className="text-ink/60">—</p>;
  return (
    <p>
      <strong className="font-mono text-base" data-testid="quality-completeness">
        {formatQualityTotal(quality.total, quality.max_total)}
      </strong>{" "}
      <span className="text-xs text-ink/70" data-testid="quality-rank">
        {quality.rank}등
      </span>
    </p>
  );
}

function SubmissionColumnHeader({
  submission,
  isAwarded,
  awardLocked,
  award,
  onAwardClick,
  onConfirm,
  onCancel,
  playback,
}: {
  submission: ComparisonSubmissionOut;
  isAwarded: boolean;
  awardLocked: boolean;
  award: AwardState;
  onAwardClick: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  playback: { assetId: number; start: number } | null;
}) {
  const isConfirming =
    award.status === "confirming" && award.submissionId === submission.submission_id;
  const isSaving = award.status === "saving" && award.submissionId === submission.submission_id;

  return (
    <div className="flex flex-col gap-2">
      {/* #165 — 공개 개발자 프로필(/developers/{id})로 가는 유일한 인바운드 링크.
          이 화면(심사 비교)을 골랐다: Sponsor가 이름만 보고 "이 사람이 누구인지"
          궁금해질 자리가 여기다 — 상금을 걸고 선정을 고민하는 시점이라 참가
          이력을 실제로 찾아볼 동기가 있다. 새 탭으로 연다 — 심사 중 이 표를
          벗어나면 비교 상태(award 확인창 등)를 잃는다.
          뺀 후보:
            - metrics/page.tsx(#107) — ContestMetricsOut 스키마 자체에
              developer_id 가 없다(lib/submissions/types.ts 상단 주석). 링크를
              달 값 자체가 없다.
            - console/participation/page.tsx — Developer 본인이 자기 제출 현황을
              보는 화면이다. 본인 이름을 자기 공개 프로필로 링크할 이유가 없다.
            - operator/app/payouts/page.tsx — 운영자가 보는 것은
              `developer_user_id`(정산 대상 식별자)뿐이고 표시 이름조차 없다
              ("개발자 #123"). 운영자는 내부 정산 상태를 보러 온 것이지 그
              사람이 누구인지 궁금해서 온 게 아니다 — 궁금해지는 자리가 아니다. */}
      <a
        href={`/developers/${submission.developer_id}`}
        target="_blank"
        rel="noreferrer"
        className="font-semibold underline"
        data-testid={`submission-${submission.submission_id}-developer-link`}
      >
        {submission.developer_display_name}
      </a>
      <p className="font-mono text-xs text-ink">
        확인 위치 {submission.completion.linked_requirement_count}/
        {submission.completion.total_requirement_count} · 권장 항목{" "}
        {[
          submission.completion.has_demo_video,
          submission.completion.has_demo_url,
          submission.completion.has_test_account,
        ].filter(Boolean).length}
        /3
      </p>
      {/* 데모는 여럿일 수 있다(#190) — 웹과 앱을 따로 낸 참가작이면 링크도 둘이다. */}
      {submission.assets
        .filter((asset) => asset.kind === "demo_url")
        .map((asset) => (
          <a
            key={asset.id}
            href={asset.value}
            target="_blank"
            rel="noreferrer"
            className="text-xs underline"
            data-testid={`submission-${submission.submission_id}-demo-url`}
          >
            {asset.label || "데모 보기"}
          </a>
        ))}

      {/* 시연 영상·스크린샷(#265) — 화면을 떠나지 않고 재생·열람한다. 자료가
          여럿이면(영상 둘, 스크린샷 여럿) 라벨로 구별된다. `download_url`은
          이미 presigned된 URL이라(`submissions.api._public_asset_summaries`)
          여기서 별도 요청 없이 바로 쓴다 — 이 화면은 이미 마감 후에만 열린다. */}
      {submission.assets
        .filter((asset) => asset.kind === "demo_video" && asset.download_url)
        .map((asset) => (
          <div key={asset.id} className="flex flex-col gap-1">
            <span className="text-xs text-ink/60">{asset.label || "시연 영상"}</span>
            <video
              controls
              preload="metadata"
              className="w-40 border border-rule"
              data-testid={`submission-${submission.submission_id}-demo-video-${asset.id}`}
            >
              <source src={asset.download_url!} />
            </video>
          </div>
        ))}
      {/* 시연 영상 링크(#910) — 유튜브는 nocookie 임베드, 그 밖은 새 창 링크. 확인 위치를
          누르면 그 영상이 그 시각부터 다시 재생된다. */}
      {submission.assets
        .filter((asset) => asset.kind === "video_link")
        .map((asset) => (
          <VideoLinkView
            key={asset.id}
            url={asset.value}
            label={asset.label || "시연 영상"}
            startSeconds={playback?.assetId === asset.id ? playback.start : 0}
            testId={`submission-${submission.submission_id}-video-link-${asset.id}`}
            className="w-56"
          />
        ))}
      {submission.assets
        .filter((asset) => asset.kind === "screenshot" && asset.download_url)
        .map((asset) => (
          // eslint-disable-next-line @next/next/no-img-element -- presigned URL, Next Image 최적화 대상이 아니다
          <img
            key={asset.id}
            src={asset.download_url!}
            alt={asset.label || "스크린샷"}
            className="w-40 border border-rule"
            data-testid={`submission-${submission.submission_id}-screenshot-${asset.id}`}
          />
        ))}
      {/* 보존 기간이 지나 파일이 파기된 자료는 **자리를 비우지 않는다**. 그냥
          빼면 심사자는 이 참가작이 애초에 영상을 안 냈다고 읽는다 — 실제로는
          냈고, 근거도 그것을 가리키고 있다. 사라진 것은 파일뿐이다. */}
      {submission.assets
        .filter((asset) => asset.expired)
        .map((asset) => (
          <p
            key={asset.id}
            className="text-xs text-ink/60"
            data-testid={`submission-${submission.submission_id}-asset-expired-${asset.id}`}
          >
            {asset.label || "시연 영상"} — 보존 기간이 지나 파일이 삭제되었습니다.
          </p>
        ))}

      {isAwarded && (
        <p className="text-xs font-semibold text-verified" data-testid={`awarded-badge-${submission.submission_id}`}>
          선정됨
        </p>
      )}

      {!awardLocked && (
        <>
          {/* 인수조건: "선정하면 소스가 열린다"는 것을 누르기 전에 알 수 있어야
              한다 — 그래서 이 안내는 버튼을 누르기 전부터 항상 보인다(조건부로
              클릭 후에만 나타나지 않는다). */}
          <p
            className="text-xs text-attention"
            data-testid={`award-source-notice-${submission.submission_id}`}
          >
            선정하면 이 제출작의 소스코드가 즉시 공개됩니다.
          </p>

          {!isConfirming ? (
            <button
              type="button"
              onClick={onAwardClick}
              disabled={isSaving}
              data-testid={`award-button-${submission.submission_id}`}
              className={`w-fit ${buttonClass("danger", "sm")}`}
            >
              이 제출물 선정
            </button>
          ) : (
            <div className="flex flex-col gap-1">
              <p className="text-xs" data-testid={`award-confirm-notice-${submission.submission_id}`}>
                정말 선정하시겠습니까? 소스코드가 즉시 공개되며 되돌릴 수 없습니다.
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={onConfirm}
                  disabled={isSaving}
                  data-testid={`award-confirm-${submission.submission_id}`}
                  className={buttonClass("dangerFilled", "sm")}
                >
                  {isSaving ? "선정 중..." : "확인 — 선정합니다"}
                </button>
                <button
                  type="button"
                  onClick={onCancel}
                  disabled={isSaving}
                  data-testid={`award-cancel-${submission.submission_id}`}
                  className={buttonClass("secondary", "sm")}
                >
                  취소
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
