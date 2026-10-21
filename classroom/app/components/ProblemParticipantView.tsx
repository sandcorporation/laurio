"use client";

// 참여자가 실제로 보는 문제 화면(#286)의 조각 — 원래
// `app/classes/[id]/problems/[problemId]/submit/page.tsx` 하나에 통째로
// 있던 것을 #325에서 여기로 뽑았다. 그 라우트(참여자가 실제로 낸다)와 문제
// 만들기/편집의 「미리보기」 탭(강사가 내기 전에 확인만 한다, #325)이 **같은
// 조각**을 쓴다 — 미리보기를 따로 그리면 둘이 갈라지고, 갈라진 미리보기는
// 미리보기가 아니다(#325 body).
//
// `interactive`가 갈림길이다: 참이면 실제 제출 라우트로, 필요한 상태·핸들러를
// 호출부(`submit/page.tsx`)가 그대로 넘긴다. 거짓이면 미리보기다 — 제출
// 입력은 눌러도 아무 일도 하지 않고(`disabled`), 시도 목록은 항상 빈 채로
// 그려진다(미리보기에는 참여자 신원이 없어 「내 시도」가 애초에 존재하지
// 않는다 — 실제로 제출된 적 없는 초안이므로 빈 목록이 사실과도 맞는다).
import Link from "next/link";
import { createElement, useEffect, useState } from "react";
import type { ChangeEvent, FormEvent, ReactNode } from "react";

import { checkGithubRepositoryUrl, commitUrl, shortSha } from "@codemit/bff-client/repository-url";
import { MarkdownView } from "@codemit/markdown";

import { SubmissionVerdictList, judgedByLabel } from "@/app/components/SubmissionVerdictList";
import { TwoColumnFrame } from "@/app/components/TwoColumnFrame";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  buttonClass,
} from "@/app/components/ui";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { DueRows } from "@/app/components/DueLabel";
import { formatDueDateTime, withLate } from "@/lib/problems/due-dates";
import { requiredSummary, scoreJudgeLabel, syntaxLineReasoning, type RequiredSummary } from "@/lib/submissions/latest-attempts";
import type { UploadStatus } from "@/lib/submissions/use-source-upload";
import type { ClassroomSubmissionRow, SubmitBlockedReason } from "@/lib/submissions/api";
import { attemptIdFromHash } from "@/lib/submissions/attempt-fold";
import { attemptEntryLabel } from "@/lib/submissions/contest-entry";
import type { GradingStrictness, SubmissionFormat } from "@/lib/problems/api";
import { gradingStrictnessLabel } from "@/lib/problems/grading-guideline";

export type ParticipantChecklistItem = {
  id: number;
  label: string;
  required: boolean;
};

// 문법 검사 기본 항목의 고정 문구(#408, CONTEXT.md 「문법 검사」) — 강사가
// 바꿀 수 없다. 체크리스트 행으로 저장하지 않으므로(백엔드 `Problem.
// syntax_check_enabled`) 여기서 하드코딩한다.
const SYNTAX_CHECK_LABEL = "소스에 문법 오류가 없다";

type InteractiveProps = {
  interactive: true;
  /** 지금 새로 낼 수 없는 이유 하나, 낼 수 있으면 `null`(#439) — 우선순위
   *  (보관 → 내보냄 → 숨김)는 백엔드가 이미 정해서 내려주므로 여기서 다시
   *  계산하지 않는다. "viewing_as_instructor"는 이 폼이 신경 쓰지 않는다 —
   *  강사가 학생 화면으로 보는 경우는 위 `InstructorViewingBanner`가 이미
   *  알리고, 실제 제출은 호출부의 핸들러가 따로 막는다. */
  submitBlockedReason: SubmitBlockedReason;
  /** 소스 zip 업로드 상한(바이트, #671) — 운영자 정책 값 그대로, 드롭 칸이 MB 로 보인다. */
  maxSourceAssetBytes: number;
  repositoryUrl: string;
  onRepositoryUrlChange: (value: string) => void;
  onRepositorySubmit: (event: FormEvent<HTMLFormElement>) => void;
  onSourceFile: (event: ChangeEvent<HTMLInputElement>) => void;
  submitting: boolean;
  submitError: string | null;
  uploadStatus: UploadStatus;
  uploadError: string | null;
  /** 공모전 문제의 「공모전에도 내기」 칸(#549) — 제출 입력 위에 선다. 공모전 문제가 아니거나
   *  공모전이 지금 받지 않으면 비운다. */
  contestEntry?: ReactNode;
  /** 필수 항목이 Git 기록을 물어 zip 으로는 언제나 놓치는 문제인가(#587, 백엔드 판정) —
   *  zip 을 고르면 보이는 안내가 경고 띠로 바뀐다. */
  zipGitHistoryWarning?: boolean;
};

type PreviewProps = {
  interactive: false;
};

type ProblemParticipantViewProps = (InteractiveProps | PreviewProps) & {
  /** 미리보기(#325)는 이 화면의 `h1`이 따로 있는 화면 안에 포개므로 `"h2"`를
   *  준다 — 실제 제출 라우트는 여기가 화면의 유일한 제목이라 기본값(`"h1"`)을
   *  그대로 쓴다. */
  headingLevel?: "h1" | "h2";
  /** 그 문제가 속한 클래스의 이름(#372 후속) — 기본값을 두지 않는다. 미리보기도
   *  참여자 화면과 같은 눈썹을 보여야 「참여자가 보는 화면 그대로」가 참이다. */
  eyebrow: string;
  /** 오른쪽 위 「문제 목록으로」의 주소 — 비우면 링크를 내지 않는다(미리보기). 강사가 볼 때는 클래스 상세(#429). */
  backHref?: string;
  title: string;
  titleTestId?: string;
  /** `undefined`면 통과 배지를 아예 내지 않는다 — 미리보기는 아직 아무도
   *  푼 적이 없으므로 「통과」/「미통과」 어느 쪽도 사실이 아니다. */
  passed?: boolean;
  /** 권장 기한·마감(#770) — 「제출」 카드 머리 아래 두 줄. 미리보기도 같은 자리에 그린다. */
  recommendedDueAt?: string | null;
  dueAt?: string | null;
  description: string;
  // 공모전 문제의 수업용 안내(#548) — 설명 위에 보인다. 공모전 문제가 아니면 빈 문자열.
  instructorNote?: string;
  checklistItems: ParticipantChecklistItem[];
  /** 문법 검사 기본 항목의 켜짐 여부(#408) — 참이면 체크리스트 맨 앞에
   *  「소스에 문법 오류가 없다」와 「기본」 표시를 둔다. */
  syntaxCheckEnabled: boolean;
  /** 채점 지침 단계(#388, CONTEXT.md 「채점 지침」) — 참여자가 어떤 기준으로
   *  판정되는지 알고 제출하도록 체크리스트 가까이 보여준다. */
  gradingStrictness: GradingStrictness;
  /** `gradingStrictness`가 "custom"일 때의 강사 문장 — 그 밖의 단계에서는
   *  쓰이지 않는다(단계→화면 문장 함수가 저장소 문장을 대신 쓴다). */
  gradingGuidelineCustomText: string;
  submissionFormats: SubmissionFormat[];
  submissions: ClassroomSubmissionRow[];
  /** 강사가 「학생 화면으로」를 눌러 이 화면을 열었는가(#429) — 참이면 맨 위에
   *  「강사로 보는 중」 배지 띠가 뜬다. 미리보기(`interactive={false}`)는
   *  이 값을 쓰지 않는다 — 미리보기는 애초에 참여자도 강사도 아닌, 아직
   *  아무도 아닌 화면이다. */
  viewingAsInstructor?: boolean;
  /** `viewingAsInstructor`가 참일 때만 뜻이 있다 — 띠가 몇 줄을 더 말할지
   *  상태 배지를 정한다(초안·숨김이면 배지 하나 더, 열림이면 「강사로 보는 중」뿐). */
  instructorProblemStatus?: "draft" | "open" | "hidden" | null;
};

/** 강사가 학생 화면을 열었을 때의 띠(#429) — 배지 둘(#660): 「강사로 보는 중」과 문제 상태
 *  (초안·숨김). 낼 수 있다는 것과 학생에게 보인다는 것은 다른 사실이라 상태 배지를 따로 둔다.
 *  보관된 클래스라 낼 수 없으면 그 이유는 제출 카드 자리의 한 줄이 말한다. */
function InstructorViewingBanner({
  status,
}: {
  status: "draft" | "open" | "hidden" | null | undefined;
}) {
  return (
    <div data-testid="instructor-viewing-banner" className="flex flex-wrap items-center gap-2">
      <Badge tone="attention">강사로 보는 중</Badge>
      {status === "draft" ? (
        <span data-testid="instructor-viewing-banner-draft">
          <Badge>초안</Badge>
        </span>
      ) : status === "hidden" ? (
        <span data-testid="instructor-viewing-banner-hidden">
          <Badge>숨김</Badge>
        </span>
      ) : null}
    </div>
  );
}

// 업로드 상한을 MB 로 — 정수가 아니면 소수 한 자리(서버가 막는 바이트 수와 같은 단위, 1MB = 1024²).
function formatMegabytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return Number.isInteger(mb) ? String(mb) : mb.toFixed(1);
}

export function ProblemParticipantView(props: ProblemParticipantViewProps) {
  const {
    headingLevel = "h1",
    eyebrow,
    title,
    titleTestId,
    passed,
    recommendedDueAt = null,
    dueAt = null,
    description,
    instructorNote = "",
    checklistItems,
    syntaxCheckEnabled,
    gradingStrictness,
    gradingGuidelineCustomText,
    submissionFormats,
    submissions,
    viewingAsInstructor,
    instructorProblemStatus,
    backHref,
  } = props;

  const checklistLabelById = new Map(checklistItems.map((item) => [item.id, item.label]));
  const sorted = [...submissions].sort((a, b) => b.attempt_number - a.attempt_number);
  // 체크리스트 카드가 품는 판정 — 가장 최근에 **채점이 끝난** 시도 하나. 그 시도의 줄에도
  // 다른 채점된 줄처럼 접힌 「판정 보기」가 있다(#660) — 처음부터 펼쳐 두지만 않는다.
  const judged = sorted.find((submission) => submission.status === "scored" && submission.score) ?? null;
  // 분모는 채점 전후 모두 `syntaxCheckEnabled` 로 센다(#670) — `requiredSummary` 하나가 정한다.
  const judgedSummary = judged ? requiredSummary(judged, checklistItems, syntaxCheckEnabled) : null;
  const requiredCount = requiredSummary({ status: "pending", score: null }, checklistItems, syntaxCheckEnabled).total;

  // 알림 링크(`#submission-{id}`)가 가리키는 시도의 판정을 펼치고 그 줄로 옮긴다 — 시도
  // 목록은 늦게 도착하므로 목록이 바뀔 때마다 다시 본다.
  const [openIds, setOpenIds] = useState<ReadonlySet<number>>(new Set());
  const submissionIds = sorted.map((submission) => submission.id).join(",");
  useEffect(() => {
    function openForHash() {
      const targetId = attemptIdFromHash(window.location.hash);
      if (targetId === null || !submissionIds.split(",").includes(String(targetId))) return;
      setOpenIds((current) => new Set(current).add(targetId));
      requestAnimationFrame(() => {
        document.getElementById(`submission-${targetId}`)?.scrollIntoView({ block: "start" });
      });
    }
    openForHash();
    window.addEventListener("hashchange", openForHash);
    return () => window.removeEventListener("hashchange", openForHash);
  }, [submissionIds]);

  const mainTop = (
    <>
      {instructorNote.trim() === "" ? null : (
        <Card>
          <CardHeader title="수업용 안내" />
          <div className="p-4" data-testid="my-problem-instructor-note">
            <MarkdownView markdown={instructorNote} fileBaseName={title} />
          </div>
        </Card>
      )}
      {description.trim() === "" ? null : (
        <Card>
          <CardHeader title="설명" />
          <div className="p-4" data-testid="my-problem-description">
            <MarkdownView markdown={description} fileBaseName={title} />
          </div>
        </Card>
      )}

      <ChecklistWithVerdict
        items={checklistItems}
        syntaxCheckEnabled={syntaxCheckEnabled}
        strictnessLabel={gradingStrictnessLabel(gradingStrictness)}
        customGuideline={gradingStrictness === "custom" ? gradingGuidelineCustomText : ""}
        judged={judged}
        judgedSummary={judgedSummary}
      />
    </>
  );

  const attempts = (
    <>
      <Card>
        <CardHeader title="내 시도" hint={submissions.length > 0 ? `${submissions.length}회` : undefined} />
        {submissions.length === 0 ? (
          <EmptyState>
            <span data-testid="submissions-empty-state">아직 낸 시도가 없습니다.</span>
          </EmptyState>
        ) : (
          <ol data-testid="submissions-list" className="divide-y divide-rule">
            {sorted.map((submission) => (
              <AttemptRow
                key={submission.id}
                submission={submission}
                items={checklistItems}
                syntaxCheckEnabled={syntaxCheckEnabled}
                checklistLabelById={checklistLabelById}
                open={openIds.has(submission.id)}
                onToggle={() =>
                  setOpenIds((current) => {
                    const next = new Set(current);
                    if (!next.delete(submission.id)) next.add(submission.id);
                    return next;
                  })
                }
              />
            ))}
          </ol>
        )}
      </Card>
    </>
  );

  // 마감이 지나 참여자가 새로 낼 수 없다(#769 `submit_blocked_reason`, 강사가 학생 화면으로 보면 막히지 않는다).
  const deadlinePassed = props.interactive && props.submitBlockedReason === "deadline_passed";

  const side = (
    <>
      <Card>
        {deadlinePassed ? (
          <>
            <div className="flex items-center justify-between gap-3 border-b border-rule px-4 py-3">
              <h2 className="text-[15px] font-semibold tracking-[-0.005em]">제출</h2>
              <span data-testid="submit-deadline-passed">
                <Badge tone={passed === true ? "neutral" : "attention"}>마감 지남</Badge>
              </span>
            </div>
            {dueAt ? (
              <div
                data-testid="submit-due-rows-due"
                className="flex justify-between gap-3 border-b border-rule px-4 py-2.5 text-[12.5px] text-ink/60"
              >
                <span>마감</span>
                <span className="font-mono">{formatDueDateTime(dueAt)}</span>
              </div>
            ) : null}
          </>
        ) : (
          <>
            <CardHeader title="제출" />
            <DueRows
              problem={{ recommended_due_at: recommendedDueAt, due_at: dueAt }}
              passed={passed === true}
              testId="submit-due-rows"
            />
          </>
        )}
        <div
          data-testid="submit-form-area"
          aria-disabled={deadlinePassed || undefined}
          // 마감 뒤에는 끌어다 놓기·저장소 칸·「제출하기」가 흐려진 채 남고 누를 수 없다(#770).
          className={`flex flex-col gap-3.5 p-4 ${deadlinePassed ? "pointer-events-none opacity-45" : ""}`}
        >
          {props.interactive ? (
            <InteractiveSubmissionForm {...props} submissionFormats={submissionFormats} />
          ) : (
            <PreviewSubmissionForm submissionFormats={submissionFormats} />
          )}
        </div>
      </Card>
      {props.interactive ? (
        <ProblemProgressCard
          met={judgedSummary?.met ?? null}
          total={judgedSummary?.total ?? requiredCount}
        />
      ) : null}
    </>
  );

  return (
    <div className="flex flex-col gap-5">
      {viewingAsInstructor ? (
        <InstructorViewingBanner status={instructorProblemStatus} />
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="text-[11px] tracking-[0.08em] text-ink/45">{eyebrow} › 문제</div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            {createElement(
              headingLevel,
              { className: "text-[22px] font-semibold tracking-[-0.01em]", "data-testid": titleTestId },
              title,
            )}
            {passed === undefined ? null : (
              <span data-testid="my-problem-passed-status">
                <Badge tone={passed ? "verified" : "attention"}>{passed ? "통과" : "아직 미통과"}</Badge>
              </span>
            )}
          </div>
        </div>
        {backHref ? (
          <Link
            href={backHref}
            data-testid="my-problem-back-link"
            className={buttonClass("secondary", "sm")}
          >
            문제 목록으로
          </Link>
        ) : null}
      </div>

      {props.interactive ? (
        <TwoColumnFrame
          main={
            <>
              {mainTop}
              {attempts}
            </>
          }
          side={side}
          sideTestId="my-problem-side"
          wideSide
        />
      ) : (
        // 미리보기는 문제 편집 화면의 한 열 안에 포개져 두 열을 나눌 폭이 없다 — 한 열로 쌓는다
        // (설명 → 체크리스트 → 제출 → 내 시도).
        <div className="flex flex-col gap-5">
          {mainTop}
          {side}
          {attempts}
        </div>
      )}
    </div>
  );
}

// 체크리스트 카드(#640) — 가장 최근 채점의 판정을 품는다. 머리에 어느 시도의 판정인지와 미통과·필수 m/n,
// 항목마다 충족/미충족 표식과 AI 의 사유. 판정이 아직 없으면 항목만.
function ChecklistWithVerdict({
  items,
  syntaxCheckEnabled,
  strictnessLabel,
  customGuideline,
  judged,
  judgedSummary,
}: {
  items: ParticipantChecklistItem[];
  syntaxCheckEnabled: boolean;
  strictnessLabel: string;
  /** 지침이 「직접 작성」일 때의 강사 문장 — 그 밖의 단계는 빈 문자열. */
  customGuideline: string;
  judged: ClassroomSubmissionRow | null;
  judgedSummary: RequiredSummary | null;
}) {
  const score = judged?.score ?? null;
  const verdictById = new Map((score?.reasoning ?? []).map((verdict) => [verdict.checklist_item_id, verdict]));
  const syntax = score?.syntax_check ?? null;
  // 문법 결과 없이 만든 자동 미달 점수(#674·#679) — 줄의 판정은 `requiredSummary` 가, 사유는 그 점수의 공통 문구가.
  const autoFailReasoning = syntaxLineReasoning(score);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 px-4 py-3">
        <h2 className="text-[15px] font-semibold tracking-[-0.005em]">
          체크리스트
          <span
            data-testid="my-problem-checklist-meta"
            className="ml-2.5 text-[12.5px] font-normal text-ink/45"
          >
            {judged ? `시도 ${judged.attempt_number} 의 판정 · ${formatRelativeTime(score?.created_at ?? null)} · ` : ""}
            지침 「{strictnessLabel}」
          </span>
        </h2>
        {judged && judgedSummary ? (
          <span data-testid="my-problem-checklist-badge">
            <Badge tone={judged.passed ? "verified" : "attention"}>
              {judged.passed ? "통과" : "미통과"} · 필수 {judgedSummary.met}/{judgedSummary.total}
            </Badge>
          </span>
        ) : null}
      </div>
      {customGuideline.trim() === "" ? null : (
        <p
          data-testid="my-problem-grading-guideline-text"
          className="border-t border-rule px-4 py-2.5 text-[12.5px] leading-relaxed text-ink/60"
        >
          {customGuideline}
        </p>
      )}
      <ul data-testid="my-problem-checklist" className="divide-y divide-rule border-t border-rule">
        {syntaxCheckEnabled ? (
          <ChecklistLine testId="checklist-item-syntax-check" met={judgedSummary?.syntaxMet ?? null}>
            <div className="text-[13.5px]">
              {SYNTAX_CHECK_LABEL} <Badge>기본</Badge>
              {syntax ? (
                <>
                  {" "}
                  <Badge>{judgedByLabel(syntax.judged_by)}</Badge>
                </>
              ) : null}
            </div>
            {syntax ? (
              <>
                <div className="mt-1 text-[12.5px] leading-[1.65] text-ink/60">{syntax.reasoning}</div>
                {syntax.findings.map((finding, index) => (
                  <div
                    key={index}
                    data-testid={`my-problem-checklist-syntax-check-finding-${index}`}
                    className="font-mono text-[12px] text-ink/60"
                  >
                    {finding.path}
                    {finding.line !== null ? `:${finding.line}` : ""} — {finding.message}
                  </div>
                ))}
              </>
            ) : autoFailReasoning ? (
              <div className="mt-1 text-[12.5px] leading-[1.65] text-ink/60">{autoFailReasoning}</div>
            ) : null}
          </ChecklistLine>
        ) : null}
        {items.map((item) => {
          const verdict = verdictById.get(item.id);
          return (
            <ChecklistLine
              key={item.id}
              testId={`checklist-item-${item.id}`}
              met={verdict ? verdict.is_met : null}
            >
              <div className="text-[13.5px]">
                {item.label}
                {item.required ? null : (
                  <>
                    {" "}
                    <Badge>선택</Badge>
                  </>
                )}
              </div>
              {verdict ? (
                <div className="mt-1 text-[12.5px] leading-[1.65] text-ink/60">{verdict.reasoning}</div>
              ) : null}
            </ChecklistLine>
          );
        })}
      </ul>
      {score ? (
        <div
          data-testid="my-problem-checklist-footer"
          className="border-t border-rule px-4 py-2.5 text-[11.5px] text-ink/45"
        >
          {scoreJudgeLabel(score)} · {formatRelativeTime(score.created_at)}
        </div>
      ) : null}
    </Card>
  );
}

// 항목 한 줄 — 표식은 충족(채움) · 미충족(붉은 테두리) · 아직 판정 없음(옅은 테두리). 글자로도 읽히게 sr-only.
function ChecklistLine({
  testId,
  met,
  children,
}: {
  testId: string;
  met: boolean | null;
  children: ReactNode;
}) {
  const marker =
    met === null ? "border-rule" : met ? "border-verified bg-verified" : "border-attention";
  return (
    <li data-testid={testId} className="flex items-start gap-3 px-4 py-3">
      <span aria-hidden className={`mt-1 h-[14px] w-[14px] shrink-0 border ${marker}`} />
      {met === null ? null : <span className="sr-only">{met ? "충족" : "미충족"}</span>}
      <div className="min-w-0 flex-1 leading-relaxed">{children}</div>
    </li>
  );
}

// 「이 문제의 진행 m/n」 — 가장 최근 채점의 필수 충족 수. 채점된 시도가 아직 없으면 0.
function ProblemProgressCard({
  met,
  total,
}: {
  met: number | null;
  total: number;
}) {
  const shown = met ?? 0;
  return (
    <Card>
      <div data-testid="my-problem-progress" className="px-4 py-3.5">
        <div className="mb-2 text-[12px] text-ink/60">이 문제의 진행</div>
        <div className="flex items-center gap-2.5">
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={shown}
            className="relative h-1.5 w-full max-w-[200px] border border-rule bg-paper"
          >
            <div
              className="absolute inset-y-0 left-0 bg-ink"
              style={{ width: `${total > 0 ? (shown / total) * 100 : 0}%` }}
            />
          </div>
          <span data-testid="my-problem-progress-count" className="font-mono text-[13px] font-semibold">
            {shown}/{total}
          </span>
        </div>
      </div>
    </Card>
  );
}

/** 「내 시도」의 한 줄 — 시도 번호 · 배지 · 필수 m/n · 시각, 접힌 판정은 「판정 보기」로 펼친다. */
function AttemptRow({
  submission,
  items,
  syntaxCheckEnabled,
  checklistLabelById,
  open,
  onToggle,
}: {
  submission: ClassroomSubmissionRow;
  items: ParticipantChecklistItem[];
  syntaxCheckEnabled: boolean;
  checklistLabelById: Map<number, string>;
  open: boolean;
  onToggle: () => void;
}) {
  // `id`는 채점 완료 알림(#329)이 특정 시도를 가리킬 때 쓰는 앵커다 —
  // `lib/notifications/link.ts`가 같은 이름을 짓는다.
  const scored = submission.status === "scored" && submission.score !== null;
  const summary = scored ? requiredSummary(submission, items, syntaxCheckEnabled) : null;
  const waitingOnInstructor =
    submission.status === "pending" &&
    (submission.pending_reason === "no_api_key" || submission.pending_reason === "model_rejected");
  return (
    <li
      id={`submission-${submission.id}`}
      data-testid={`submission-row-${submission.id}`}
      className="scroll-mt-4 px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5">
        <span
          data-testid={`submission-row-${submission.id}-attempt`}
          className="w-12 shrink-0 font-mono text-[12.5px] text-ink/45"
        >
          시도 {submission.attempt_number}
        </span>
        <span data-testid={`submission-row-${submission.id}-status`}>
          {submission.status === "pending" ? (
            <Badge>{submission.pending_reason ? "채점 대기" : "채점 중"}</Badge>
          ) : (
            <Badge tone={submission.passed ? "verified" : "attention"}>
              {withLate(submission.passed ? "통과" : "미통과", submission.late)}
            </Badge>
          )}
        </span>
        <span className="flex min-w-0 flex-1 basis-40 flex-wrap items-center gap-x-3 gap-y-0.5 text-[12.5px] text-ink/60">
          {summary && summary.met !== null ? (
            <>
              <span data-testid={`submission-row-${submission.id}-required`} className="shrink-0">
                필수 {summary.met}/{summary.total}
              </span>
              {summary.unmet.length > 0 ? (
                <span title={summary.unmet.join(", ")} className="max-w-full min-w-0 truncate">
                  {summary.unmet.join(", ")}
                </span>
              ) : null}
            </>
          ) : null}
          {waitingOnInstructor ? (
            // 키가 아예 없는 것(#346)과 거부된 것, 채점 모델을 그 키로 못 쓰는 것(#403)을 여기서는
            // 구별하지 않는다 — 강사가 설정을 고쳐야 풀리는 사유라 참여자에게는 같은 한 줄이다.
            <span data-testid={`submission-row-${submission.id}-no-api-key-note`} className="min-w-0 truncate">
              강사의 채점 설정 때문에 멈췄습니다 — 다시 낼 필요 없습니다
            </span>
          ) : null}
          {scored ? (
            <button
              type="button"
              data-testid={`submission-row-${submission.id}-verdict-toggle`}
              aria-expanded={open}
              onClick={onToggle}
              className="shrink-0 whitespace-nowrap underline"
            >
              판정 보기
            </button>
          ) : null}
          {submission.submission_format === "repository" ? (
            <>
              <a
                href={submission.value}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 text-attention hover:underline"
              >
                저장소
              </a>
              {/* 고정 커밋(#777) — 브랜치·커밋으로 낸 시도만. 낸 주소 옆에 짧은 SHA 를 커밋 링크로. */}
              {submission.commit_sha ? (
                <a
                  href={commitUrl(submission.value, submission.commit_sha)}
                  target="_blank"
                  rel="noreferrer"
                  data-testid={`submission-row-${submission.id}-commit`}
                  className="shrink-0 font-mono text-[12px] text-ink/60 hover:underline"
                >
                  {shortSha(submission.commit_sha)}
                </a>
              ) : null}
            </>
          ) : submission.download_url ? (
            <a
              href={submission.download_url}
              data-testid={`submission-row-${submission.id}-download`}
              className="shrink-0 text-attention hover:underline"
            >
              다운로드
            </a>
          ) : null}
        </span>
        <span className="shrink-0 text-[11.5px] text-ink/45">
          {formatRelativeTime(submission.created_at)}
        </span>
      </div>

      {submission.contest_entry ? (
        <p
          data-testid={`submission-row-${submission.id}-contest-entry`}
          className={`mt-1.5 text-[12.5px] leading-relaxed ${
            submission.contest_entry.status === "rejected" ? "text-attention" : "text-ink/60"
          }`}
        >
          {attemptEntryLabel(submission.contest_entry)}
        </p>
      ) : null}

      {open && scored && submission.score ? (
        <div className="mt-3 border-t border-rule pt-3">
          <SubmissionVerdictList
            score={submission.score}
            checklistLabelById={checklistLabelById}
            testIdPrefix={`submission-row-${submission.id}`}
          />
        </div>
      ) : null}
    </li>
  );
}

function InteractiveSubmissionForm(
  props: InteractiveProps & { submissionFormats: SubmissionFormat[] },
) {
  const {
    submitBlockedReason,
    maxSourceAssetBytes,
    repositoryUrl,
    onRepositoryUrlChange,
    onRepositorySubmit,
    onSourceFile,
    submitting,
    submitError,
    uploadStatus,
    uploadError,
    submissionFormats,
    contestEntry,
    zipGitHistoryWarning = false,
  } = props;

  // 둘 다 열린 문제는 형식 선택을 먼저 보인다(#373 AC) — 하나만 열린
  // 문제는 고르는 단계 없이 그 형식의 입력만 보인다.
  const [chosenFormat, setChosenFormat] = useState<SubmissionFormat | null>(
    submissionFormats.length === 1 ? submissionFormats[0] : null,
  );
  const resolvedFormat = chosenFormat ?? submissionFormats[0];
  const repositoryCheck = checkGithubRepositoryUrl(repositoryUrl);
  const locked = submitBlockedReason === "deadline_passed";
  const needsFormatChoice = !locked && submissionFormats.length > 1 && chosenFormat === null;

  // 낼 수 없는 이유는 제출 카드 자리에 한 줄이다 — 지난 시도와 판정은 옆 열에 그대로 남는다.
  // 백엔드가 보관 → 내보냄 → 숨김 → 마감 순서로 이유를 하나만 정해 주므로(#439, #769) 그 값을 그대로
  // 분기한다. 마감(`deadline_passed`)만은 문장이 아니다 — 카드 머리의 「마감 지남」 배지와 흐려진 칸이 말한다.
  if (submitBlockedReason === "archived") {
    return (
      <p data-testid="class-archived-note" className="text-[13px] text-attention">
        이 클래스는 보관되어 새 제출을 받지 않습니다.
      </p>
    );
  }
  if (submitBlockedReason === "expelled") {
    return (
      <p data-testid="member-expelled-note" className="text-[13px] text-attention">
        이 클래스에서 내보내져 새로 제출할 수 없습니다.
      </p>
    );
  }
  if (submitBlockedReason === "hidden") {
    return (
      <p data-testid="problem-hidden-note" className="text-[13px] text-attention">
        강사가 숨긴 문제라 새로 낼 수 없습니다.
      </p>
    );
  }

  if (needsFormatChoice) {
    return (
      <>
        {contestEntry}
        <div data-testid="submission-format-picker" className="flex flex-col gap-2.5">
          <FieldLabel>낼 형식을 고르세요</FieldLabel>
          <div className="flex flex-col gap-2">
            <button
              type="button"
              data-testid="submission-format-option-source"
              onClick={() => setChosenFormat("source")}
              className={buttonClass("secondary")}
            >
              zip 파일
            </button>
            <button
              type="button"
              data-testid="submission-format-option-repository"
              onClick={() => setChosenFormat("repository")}
              className={buttonClass("secondary")}
            >
              GitHub 저장소
            </button>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {submissionFormats.length > 1 ? (
        <button
          type="button"
          data-testid="submission-format-change"
          onClick={() => setChosenFormat(null)}
          className="self-start text-[12px] text-ink/45 hover:underline"
        >
          다른 형식으로 내기
        </button>
      ) : null}

      {contestEntry}

      {resolvedFormat === "repository" ? (
        <form onSubmit={onRepositorySubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="repository-url">
              <FieldLabel>GitHub 저장소 주소</FieldLabel>
            </label>
            {/* type=url 이면 SSH 주소(git@…)를 브라우저가 제 말로 막아 아래 안내가 묻힌다 —
                글 칸으로 두고 판정은 `checkGithubRepositoryUrl` 이 한다. */}
            <input
              id="repository-url"
              data-testid="repository-url-input"
              type="text"
              inputMode="url"
              autoCapitalize="off"
              spellCheck={false}
              placeholder="https://github.com/owner/repo"
              value={repositoryUrl}
              onChange={(event) => onRepositoryUrlChange(event.target.value)}
              disabled={locked}
              required
              aria-invalid={repositoryCheck !== null && !repositoryCheck.ok}
              className={`${INPUT_CLASS} font-mono`}
            />
            {repositoryCheck !== null && !repositoryCheck.ok ? (
              <p data-testid="repository-url-invalid" className="text-[12px] leading-relaxed text-attention">
                {repositoryCheck.message}
                {repositoryCheck.suggestion ? (
                  <>
                    {" "}
                    <button
                      type="button"
                      data-testid="repository-url-suggestion"
                      onClick={() => onRepositoryUrlChange(repositoryCheck.suggestion ?? "")}
                      className="font-mono underline"
                    >
                      {repositoryCheck.suggestion}
                    </button>
                    로 바꾸기
                  </>
                ) : null}
              </p>
            ) : null}
          </div>
          <button
            type="submit"
            data-testid="submit-repository"
            disabled={locked || submitting || repositoryCheck === null || !repositoryCheck.ok}
            className={`${buttonClass("primary")} w-full`}
          >
            {submitting ? "제출하는 중..." : "제출하기"}
          </button>
        </form>
      ) : (
        <div className="flex flex-col gap-2">
          {zipGitHistoryWarning ? (
            <Note tone="attention">
              <div data-testid="zip-git-history-warning" className="flex flex-col gap-2">
                <p className="text-attention">
                  {submissionFormats.includes("repository")
                    ? "이 문제는 커밋 기록을 봅니다. zip 에는 Git 기록(.git)이 들어가지 않으니 저장소로 내세요."
                    : "이 문제는 커밋 기록을 봅니다. zip 에는 Git 기록(.git)이 들어가지 않아 그 항목은 충족되지 않습니다."}
                </p>
                {submissionFormats.includes("repository") ? (
                  <button
                    type="button"
                    data-testid="zip-git-history-use-repository"
                    onClick={() => setChosenFormat("repository")}
                    className={`${buttonClass("secondary", "sm")} self-start`}
                  >
                    저장소로 내기
                  </button>
                ) : null}
              </div>
            </Note>
          ) : (
            <p data-testid="zip-git-history-note" className="text-[12px] leading-relaxed text-ink/55">
              zip 에는 Git 기록(.git)이 들어가지 않습니다. 커밋 기록을 보여야 하는 문제는 저장소로 내세요.
            </p>
          )}
          {/* 드롭 칸 — 투명한 파일 입력이 칸 전체를 덮어 끌어다 놓기와 고르기를 함께 받는다. */}
          <div className="relative border border-dashed border-rule bg-paper px-5 py-6 text-center text-[13.5px] text-ink/60">
            소스 zip 을 끌어다 놓거나 <span className="text-attention">고르기</span>
            <div data-testid="source-file-max-size" className="mt-1 text-[11.5px] text-ink/45">
              최대 {formatMegabytes(maxSourceAssetBytes)}MB
            </div>
            <input
              id="source-file"
              data-testid="source-file-input"
              type="file"
              aria-label="소스 파일"
              onChange={onSourceFile}
              disabled={locked || submitting || uploadStatus === "uploading"}
              className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
            />
          </div>
          {uploadStatus === "uploading" ? (
            <p data-testid="source-upload-progress" className="text-[12.5px] text-ink/45">
              업로드하는 중...
            </p>
          ) : null}
          {uploadStatus === "error" ? (
            <ErrorNote>
              <span data-testid="source-upload-error">{uploadError}</span>
            </ErrorNote>
          ) : null}
        </div>
      )}

      {submitError ? (
        <ErrorNote>
          <span data-testid="submit-error">{submitError}</span>
        </ErrorNote>
      ) : null}
    </>
  );
}

/** 미리보기 전용 — 참여자가 볼 제출 칸의 **모양**만 보여준다. 입력은
 *  `disabled`라 아무 값도 못 받고, 누를 버튼 자체가 없다(#325 AC "미리보기에서는
 *  실제로 제출되지 않는다"). */
function PreviewSubmissionForm({ submissionFormats }: { submissionFormats: SubmissionFormat[] }) {
  if (submissionFormats.length === 0) {
    return (
      <p data-testid="preview-submission-no-format-notice" className="text-[12.5px] text-ink/45">
        아직 제출 형식을 고르지 않았습니다.
      </p>
    );
  }

  if (submissionFormats.length > 1) {
    return (
      <>
        <div data-testid="submission-format-picker" className="flex flex-col gap-2.5">
          <FieldLabel>낼 형식을 고르세요</FieldLabel>
          <div className="flex flex-col gap-2">
            <button type="button" disabled className={`${buttonClass("secondary")} opacity-60`}>
              zip 파일
            </button>
            <button type="button" disabled className={`${buttonClass("secondary")} opacity-60`}>
              GitHub 저장소
            </button>
          </div>
        </div>
        <p
          className="text-[11.5px] leading-relaxed text-ink/45"
          data-testid="preview-submission-disabled-note"
        >
          미리보기입니다 — 여기서는 실제로 제출되지 않습니다.
        </p>
      </>
    );
  }

  const submissionFormat = submissionFormats[0];
  return (
    <>
      {submissionFormat === "repository" ? (
        <div className="flex flex-col gap-1.5">
          <FieldLabel>GitHub 저장소 주소</FieldLabel>
          <input
            data-testid="preview-repository-url-input"
            type="url"
            placeholder="https://github.com/owner/repo"
            disabled
            className={`${INPUT_CLASS} font-mono opacity-60`}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <FieldLabel>소스 파일</FieldLabel>
          <input
            data-testid="preview-source-file-input"
            type="file"
            disabled
            className="w-full border border-dashed border-rule bg-paper px-3 py-6 text-[13px] text-ink/60 opacity-60"
          />
        </div>
      )}
      <p className="text-[11.5px] leading-relaxed text-ink/45" data-testid="preview-submission-disabled-note">
        미리보기입니다 — 여기서는 실제로 제출되지 않습니다.
      </p>
    </>
  );
}
