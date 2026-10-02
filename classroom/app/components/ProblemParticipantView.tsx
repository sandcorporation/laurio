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
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { MarkdownView } from "@codemit/markdown";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  PageHeader,
  buttonClass,
} from "@/app/components/ui";
import type { UploadStatus } from "@/lib/submissions/use-source-upload";
import type { ClassroomSubmissionRow, SubmitBlockedReason } from "@/lib/submissions/api";
import { attemptIdFromHash, splitAttempts } from "@/lib/submissions/attempt-fold";
import type { GradingStrictness, SubmissionFormat } from "@/lib/problems/api";
import { gradingGuidelineText, gradingStrictnessLabel } from "@/lib/problems/grading-guideline";

export type ParticipantChecklistItem = {
  id: number;
  label: string;
  required: boolean;
};

// 문법 검사 기본 항목의 고정 문구(#408, CONTEXT.md 「문법 검사」) — 강사가
// 바꿀 수 없다. 체크리스트 행으로 저장하지 않으므로(백엔드 `Problem.
// syntax_check_enabled`) 여기서 하드코딩한다.
const SYNTAX_CHECK_LABEL = "소스에 문법 오류가 없다";

// 판정 주체 표시(#409 AC "화면 근거에 파서 판정과 AI 판정이 구별되어
// 보인다") — 파서 판정은 신뢰도가 높고(파이썬 표준 파서·tree-sitter), AI
// 판정은 파서가 없는 언어이거나 크기·시간 제한에 걸렸을 때만 쓰인다.
export function judgedByLabel(judgedBy: "parser" | "ai"): string {
  return judgedBy === "parser" ? "파서 판정" : "AI 판정";
}

type InteractiveProps = {
  interactive: true;
  /** 지금 새로 낼 수 없는 이유 하나, 낼 수 있으면 `null`(#439) — 우선순위
   *  (보관 → 내보냄 → 숨김)는 백엔드가 이미 정해서 내려주므로 여기서 다시
   *  계산하지 않는다. "viewing_as_instructor"는 이 폼이 신경 쓰지 않는다 —
   *  강사가 학생 화면으로 보는 경우는 위 `InstructorViewingBanner`가 이미
   *  알리고, 실제 제출은 호출부의 핸들러가 따로 막는다. */
  submitBlockedReason: SubmitBlockedReason;
  repositoryUrl: string;
  onRepositoryUrlChange: (value: string) => void;
  onRepositorySubmit: (event: FormEvent<HTMLFormElement>) => void;
  onSourceFile: (event: ChangeEvent<HTMLInputElement>) => void;
  submitting: boolean;
  submitError: string | null;
  uploadStatus: UploadStatus;
  uploadError: string | null;
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
  title: string;
  titleTestId?: string;
  /** `undefined`면 통과 배지를 아예 내지 않는다 — 미리보기는 아직 아무도
   *  푼 적이 없으므로 「통과」/「미통과」 어느 쪽도 사실이 아니다. */
  passed?: boolean;
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
   *  「강사로 보고 있습니다」 띠가 뜬다. 미리보기(`interactive={false}`)는
   *  이 값을 쓰지 않는다 — 미리보기는 애초에 참여자도 강사도 아닌, 아직
   *  아무도 아닌 화면이다. */
  viewingAsInstructor?: boolean;
  /** `viewingAsInstructor`가 참일 때만 뜻이 있다 — 띠가 몇 줄을 더 말할지
   *  정한다(초안·숨김이면 한 줄 더, 열림이면 띠 한 줄뿐). */
  instructorProblemStatus?: "draft" | "open" | "hidden" | null;
};

/** 강사가 학생 화면을 열었을 때의 안내 문구(#429) — 기본 한 줄에 상태별로
 *  한 줄을 더한다. 판정 로직이 아니라 문구 조립이라 별도 순수 함수 시임을
 *  두지 않는다(#429 Testing Decisions).
 *
 *  **강사는 상태와 무관하게 낸다**(2026-09-17) — 그래서 첫 줄이 「지금 낼 수
 *  있는가」에 따라 갈린다(잠기는 것은 보관된 클래스뿐이다). 예전의 「제출은
 *  되지 않습니다」를 그대로 두면 화면이 거짓말을 한다 — 제출 칸이 실제로
 *  동작한다. 아래 두 줄(초안·숨김)은 그대로다: 낼 수 있다는 것과, 학생에게
 *  아직 보이지 않는다는 것은 서로 다른 사실이다. */
function InstructorViewingBanner({
  status,
  canSubmit,
}: {
  status: "draft" | "open" | "hidden" | null | undefined;
  canSubmit: boolean;
}) {
  return (
    <Note tone="attention">
      <div className="flex flex-col gap-1">
        <span data-testid="instructor-viewing-banner">
          {canSubmit
            ? "강사로 보고 있습니다 — 직접 내 볼 수 있고, 학생 명단에는 들어가지 않습니다."
            : "강사로 보고 있습니다 — 제출은 되지 않습니다."}
        </span>
        {status === "draft" ? (
          <span data-testid="instructor-viewing-banner-draft">
            아직 초안이니 학생에게는 이 화면이 보이지 않습니다.
          </span>
        ) : status === "hidden" ? (
          <span data-testid="instructor-viewing-banner-hidden">
            숨긴 문제입니다 — 이미 낸 학생만 봅니다.
          </span>
        ) : null}
      </div>
    </Note>
  );
}

export function ProblemParticipantView(props: ProblemParticipantViewProps) {
  const {
    headingLevel = "h1",
    eyebrow,
    title,
    titleTestId,
    passed,
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
  } = props;

  const checklistLabelById = new Map(checklistItems.map((item) => [item.id, item.label]));
  const { latest, older } = splitAttempts(submissions);
  const [olderOpen, setOlderOpen] = useState(false);

  // 알림 링크(`#submission-{id}`)가 접힌 지난 시도를 가리키면 펼치고 그 줄로
  // 옮긴다 — 접힌 줄은 그려지지 않아 브라우저가 앵커를 찾지 못한다. 시도
  // 목록은 늦게 도착하므로 목록이 바뀔 때마다 다시 본다.
  const olderIds = older.map((submission) => submission.id).join(",");
  useEffect(() => {
    function openForHash() {
      const targetId = attemptIdFromHash(window.location.hash);
      if (targetId === null || !olderIds.split(",").includes(String(targetId))) return;
      setOlderOpen(true);
      requestAnimationFrame(() => {
        document.getElementById(`submission-${targetId}`)?.scrollIntoView({ block: "start" });
      });
    }
    openForHash();
    window.addEventListener("hashchange", openForHash);
    return () => window.removeEventListener("hashchange", openForHash);
  }, [olderIds]);
  // 문법 검사 기본 항목(#408)도 필수라 힌트 숫자에 함께 셈한다.
  const requiredCount =
    checklistItems.filter((item) => item.required).length + (syntaxCheckEnabled ? 1 : 0);

  return (
    <div className="flex flex-col gap-5">
      {viewingAsInstructor ? (
        <InstructorViewingBanner
          status={instructorProblemStatus}
          canSubmit={props.interactive ? props.submitBlockedReason === null : false}
        />
      ) : null}
      <PageHeader
        headingLevel={headingLevel}
        eyebrow={eyebrow}
        title={title}
        titleTestId={titleTestId}
        actions={
          passed === undefined ? null : (
            <span data-testid="my-problem-passed-status">
              <Badge tone={passed ? "verified" : "neutral"}>
                {passed ? "이 문제를 통과했습니다" : "아직 통과하지 못했습니다"}
              </Badge>
            </span>
          )
        }
      />

      {/* 한 열로 쌓는다(2026-09-15) — 예전에는 오른쪽 380px 열에 제출 카드를 따로 뒀는데,
          설명·체크리스트를 읽고 → 내고 → 결과를 보는 흐름이 좌우로 갈라졌다. 순서는
          설명 → 체크리스트 → 제출 → 내 시도다: 시도가 쌓여도 제출 칸이 밀려나지 않는다. */}
      <div className="flex flex-col gap-5">
        <div className="flex min-w-0 flex-col gap-5">
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

          <Card>
            <CardHeader title="체크리스트" hint={`필수 ${requiredCount}개를 전부 충족하면 통과`} />
            <div
              data-testid="my-problem-grading-guideline"
              className="flex flex-col gap-1 border-b border-rule px-4 py-3"
            >
              <div className="flex items-center gap-2">
                <Badge>{gradingStrictnessLabel(gradingStrictness)}</Badge>
                <span className="text-[12px] font-medium text-ink/60">채점 지침</span>
              </div>
              <p
                data-testid="my-problem-grading-guideline-text"
                className="text-[12.5px] leading-relaxed text-ink/60"
              >
                {gradingGuidelineText(gradingStrictness, gradingGuidelineCustomText)}
              </p>
            </div>
            <ul data-testid="my-problem-checklist" className="divide-y divide-rule">
              {syntaxCheckEnabled ? (
                <li
                  data-testid="checklist-item-syntax-check"
                  className="flex items-start gap-3 px-4 py-3 text-[13.5px] leading-relaxed"
                >
                  <span className="flex-1">{SYNTAX_CHECK_LABEL}</span>
                  <span className="flex shrink-0 gap-1.5">
                    <Badge>기본</Badge>
                    <Badge tone="attention">필수</Badge>
                  </span>
                </li>
              ) : null}
              {checklistItems.map((item) => (
                <li
                  key={item.id}
                  data-testid={`checklist-item-${item.id}`}
                  className="flex items-start gap-3 px-4 py-3 text-[13.5px] leading-relaxed"
                >
                  <span className="flex-1">{item.label}</span>
                  <span className="shrink-0">
                    <Badge tone={item.required ? "attention" : "neutral"}>
                      {item.required ? "필수" : "선택"}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader title="제출" />
            <div className="flex flex-col gap-3.5 p-4">
              {props.interactive ? (
                <InteractiveSubmissionForm {...props} submissionFormats={submissionFormats} />
              ) : (
                <PreviewSubmissionForm submissionFormats={submissionFormats} />
              )}
            </div>
          </Card>

          <Card>
            <CardHeader title="내 시도" hint={submissions.length > 0 ? `${submissions.length}회` : undefined} />
            {submissions.length === 0 ? (
              <EmptyState>
                <span data-testid="submissions-empty-state">아직 낸 시도가 없습니다.</span>
              </EmptyState>
            ) : (
              <>
                <ol data-testid="submissions-list" className="divide-y divide-rule">
                  {latest ? (
                    <SubmissionRow submission={latest} checklistLabelById={checklistLabelById} />
                  ) : null}
                  {olderOpen
                    ? older.map((submission) => (
                        <SubmissionRow
                          key={submission.id}
                          submission={submission}
                          checklistLabelById={checklistLabelById}
                        />
                      ))
                    : null}
                </ol>
                {older.length > 0 ? (
                  <button
                    type="button"
                    data-testid="submissions-older-toggle"
                    aria-expanded={olderOpen}
                    onClick={() => setOlderOpen((open) => !open)}
                    className="flex w-full items-center gap-1.5 border-t border-rule px-4 py-2.5 text-left text-[12.5px] text-ink/60 hover:bg-paper"
                  >
                    {olderOpen ? (
                      <ChevronDown aria-hidden="true" size={14} />
                    ) : (
                      <ChevronRight aria-hidden="true" size={14} />
                    )}
                    {olderOpen ? "지난 시도 접기" : `지난 시도 ${older.length}개 보기`}
                  </button>
                ) : null}
              </>
            )}
          </Card>
        </div>

      </div>
    </div>
  );
}

/** 「내 시도」의 한 줄 — 최근 시도와 펼친 지난 시도가 같은 모양이다. */
function SubmissionRow({
  submission,
  checklistLabelById,
}: {
  submission: ClassroomSubmissionRow;
  checklistLabelById: Map<number, string>;
}) {
  // `id`는 채점 완료 알림(#329)이 특정 시도를 가리킬 때 쓰는 앵커다 —
  // `lib/notifications/link.ts`가 같은 이름을 짓는다.
  return (
    <li
      id={`submission-${submission.id}`}
      data-testid={`submission-row-${submission.id}`}
      className="scroll-mt-4 px-4 py-4"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span
          data-testid={`submission-row-${submission.id}-attempt`}
          className="font-mono text-[12.5px] text-ink/45"
        >
          시도 {submission.attempt_number}
        </span>

        {submission.status === "pending" ? (
          <span data-testid={`submission-row-${submission.id}-status`}>
            <Badge>{submission.pending_reason ? "채점 대기" : "채점 중"}</Badge>
          </span>
        ) : (
          <span data-testid={`submission-row-${submission.id}-status`}>
            <Badge tone={submission.passed ? "verified" : "attention"}>
              채점 완료 · {submission.passed ? "통과" : "미통과"}
            </Badge>
          </span>
        )}

        <span className="ml-auto shrink-0 text-[12.5px]">
          {submission.submission_format === "repository" ? (
            <a
              href={submission.value}
              target="_blank"
              rel="noreferrer"
              className="text-attention hover:underline"
            >
              {submission.value}
            </a>
          ) : submission.download_url ? (
            <a
              href={submission.download_url}
              data-testid={`submission-row-${submission.id}-download`}
              className="text-attention hover:underline"
            >
              다운로드
            </a>
          ) : null}
        </span>
      </div>

      {submission.status === "pending" && submission.pending_reason === "budget_exhausted" ? (
        <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink/60">
          이 클래스의 채점 예산이 소진되어 잠시 멈췄습니다.{" "}
          <b className="font-medium text-ink">제출은 저장됐으니 다시 낼 필요는 없습니다.</b>{" "}
          예산이 채워지면 순서대로 이어서 채점됩니다.
        </p>
      ) : null}

      {submission.status === "pending" &&
      (submission.pending_reason === "no_api_key" ||
        submission.pending_reason === "model_rejected") ? (
        // 키가 아예 없는 것과 거부된 것(#355), 채점 모델을 그
        // 키로 못 쓰는 것(#403)을 여기서는 구별하지 않는다 —
        // 셋 다 강사가 설정을 고쳐야 풀리는 사유라, 참여자에게는
        // 같은 안내를 보인다(#403 AC).
        <p
          data-testid={`submission-row-${submission.id}-no-api-key-note`}
          className="mt-2.5 text-[12.5px] leading-relaxed text-ink/60"
        >
          강사의 채점 설정 문제로 잠시 멈췄습니다.{" "}
          <b className="font-medium text-ink">
            당신의 잘못이 아니고, 다시 낼 필요도 없습니다.
          </b>{" "}
          강사가 설정을 고치면 이어서 채점됩니다.
        </p>
      ) : null}

      {submission.status === "scored" && submission.score ? (
        <ul
          data-testid={`submission-row-${submission.id}-verdicts`}
          className="mt-3 flex flex-col gap-2 border-t border-rule pt-3"
        >
          {submission.score.syntax_check ? (
            <li
              data-testid={`submission-row-${submission.id}-syntax-check`}
              className="flex gap-2.5"
            >
              <span
                aria-hidden
                className={`mt-1 h-[13px] w-[13px] shrink-0 border ${
                  submission.score.syntax_check.is_met
                    ? "border-verified bg-verified"
                    : "border-attention"
                }`}
              />
              <span className="text-[13px] leading-relaxed">
                <Badge>기본</Badge>{" "}
                <span
                  data-testid={`submission-row-${submission.id}-syntax-check-judged-by`}
                >
                  <Badge tone="neutral">{judgedByLabel(submission.score.syntax_check.judged_by)}</Badge>
                </span>{" "}
                {SYNTAX_CHECK_LABEL}
                <span className="text-ink/45">
                  {" "}
                  — {submission.score.syntax_check.is_met ? "충족" : "미충족"}
                </span>
                <span className="block text-ink/60">
                  {submission.score.syntax_check.reasoning}
                </span>
                {submission.score.syntax_check.findings.map((finding, index) => (
                  <span
                    key={index}
                    data-testid={`submission-row-${submission.id}-syntax-check-finding-${index}`}
                    className="block font-mono text-[12px] text-ink/60"
                  >
                    {finding.path}
                    {finding.line !== null ? `:${finding.line}` : ""} — {finding.message}
                  </span>
                ))}
              </span>
            </li>
          ) : null}
          {submission.score.reasoning.map((verdict) => (
            <li key={verdict.checklist_item_id} className="flex gap-2.5">
              <span
                aria-hidden
                className={`mt-1 h-[13px] w-[13px] shrink-0 border ${
                  verdict.is_met ? "border-verified bg-verified" : "border-attention"
                }`}
              />
              <span className="text-[13px] leading-relaxed">
                {checklistLabelById.get(verdict.checklist_item_id) ?? "항목"}
                <span className="text-ink/45"> — {verdict.is_met ? "충족" : "미충족"}</span>
                <span className="block text-ink/60">{verdict.reasoning}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function InteractiveSubmissionForm(
  props: InteractiveProps & { submissionFormats: SubmissionFormat[] },
) {
  const {
    submitBlockedReason,
    repositoryUrl,
    onRepositoryUrlChange,
    onRepositorySubmit,
    onSourceFile,
    submitting,
    submitError,
    uploadStatus,
    uploadError,
    submissionFormats,
  } = props;

  // 둘 다 열린 문제는 형식 선택을 먼저 보인다(#373 AC) — 하나만 열린
  // 문제는 고르는 단계 없이 그 형식의 입력만 보인다.
  const [chosenFormat, setChosenFormat] = useState<SubmissionFormat | null>(
    submissionFormats.length === 1 ? submissionFormats[0] : null,
  );
  const resolvedFormat = chosenFormat ?? submissionFormats[0];
  const needsFormatChoice = submissionFormats.length > 1 && chosenFormat === null;

  return (
    <>
      {submitBlockedReason === "archived" ? (
        // 보관된 클래스는 내보내진 사람과 같은 모양으로 제출 수단을 숨긴다
        // (#294, #338 AC) — 지난 시도는 위 "내 시도" 카드에 그대로 남아
        // 있다. 되돌리면(POST .../unarchive) 이 분기를 벗어나 폼이 다시
        // 보인다. 백엔드가 이미 보관 → 내보냄 → 숨김 순서로 이유를 하나만
        // 정해 주므로(#439) 여기서는 그 값을 그대로 분기한다.
        <ErrorNote>
          <span data-testid="class-archived-note">
            이 클래스는 보관되어 새 제출을 받지 않습니다. 지난 시도와 판정은 계속 볼 수
            있습니다.
          </span>
        </ErrorNote>
      ) : submitBlockedReason === "expelled" ? (
        // 내보내진 사람에게는 제출 수단 자체를 보이지 않고, 왜
        // 낼 수 없는지를 말해 준다(#300 AC) — 지난 시도는 위
        // "내 시도" 카드에 그대로 남아 있다. 「다시 낼 수 있다」 안내는 이
        // 분기 밖에 있었다면 여기서도 그대로 떴을 것이다(#337) — 그래서
        // 그 안내는 아래에서 실제로 낼 수 있는 분기 안에만 둔다.
        <ErrorNote>
          <span data-testid="member-expelled-note">
            이 클래스에서 내보내져 더 이상 새로 제출할 수 없습니다. 지난 시도와 판정은
            계속 볼 수 있습니다.
          </span>
        </ErrorNote>
      ) : submitBlockedReason === "hidden" ? (
        // 강사가 이 문제를 숨겼다(#405) — 여기 닿았다는 것 자체가 이미 한
        // 번은 냈다는 뜻이다(안 낸 참여자는 애초에 이 화면 자체가 404다).
        // 지난 시도와 판정은 위 "내 시도" 카드에 그대로 남는다.
        <ErrorNote>
          <span data-testid="problem-hidden-note">
            강사가 숨긴 문제라 새로 낼 수 없습니다. 지난 시도와 판정은 계속 볼 수 있습니다.
          </span>
        </ErrorNote>
      ) : needsFormatChoice ? (
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
      ) : (
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

          {resolvedFormat === "repository" ? (
            <form onSubmit={onRepositorySubmit} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="repository-url">
                  <FieldLabel>GitHub 저장소 주소</FieldLabel>
                </label>
                <input
                  id="repository-url"
                  data-testid="repository-url-input"
                  type="url"
                  placeholder="https://github.com/owner/repo"
                  value={repositoryUrl}
                  onChange={(event) => onRepositoryUrlChange(event.target.value)}
                  required
                  className={`${INPUT_CLASS} font-mono`}
                />
              </div>
              <button
                type="submit"
                data-testid="submit-repository"
                disabled={submitting || repositoryUrl.trim() === ""}
                className={`${buttonClass("primary")} w-full`}
              >
                {submitting ? "제출하는 중..." : "제출하기"}
              </button>
            </form>
          ) : (
            <div className="flex flex-col gap-2">
              <label htmlFor="source-file">
                <FieldLabel>소스 파일</FieldLabel>
              </label>
              <input
                id="source-file"
                data-testid="source-file-input"
                type="file"
                onChange={onSourceFile}
                disabled={submitting || uploadStatus === "uploading"}
                className="w-full cursor-pointer border border-dashed border-rule bg-paper px-3 py-6 text-[13px] text-ink/60 file:mr-3 file:cursor-pointer file:border file:border-rule file:bg-surface file:px-3 file:py-1.5 file:text-[12.5px] file:text-ink disabled:cursor-not-allowed disabled:opacity-45"
              />
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

          <p className="text-[11.5px] leading-relaxed text-ink/45">
            내면 바로 채점이 시작되고, <b className="font-medium text-ink">끝나면 알림이 옵니다.</b>{" "}
            한 번이라도 통과하면 계속 통과로 남으니, 안 되면 몇 번이든 고쳐서 다시 낼 수
            있습니다.
          </p>
        </>
      )}
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
