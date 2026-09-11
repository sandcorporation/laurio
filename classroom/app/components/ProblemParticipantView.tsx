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
import type { ChangeEvent, FormEvent } from "react";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  PageHeader,
  buttonClass,
} from "@/app/components/ui";
import { ProblemDescription } from "@/app/components/ProblemDescription";
import type { UploadStatus } from "@/lib/submissions/use-source-upload";
import type { ClassroomSubmissionRow } from "@/lib/submissions/api";
import type { SubmissionFormat } from "@/lib/problems/api";

export type ParticipantChecklistItem = {
  id: number;
  label: string;
  required: boolean;
};

type InteractiveProps = {
  interactive: true;
  memberExpelled: boolean;
  /** 클래스가 보관됐는가(#294, #338) — 참이면 내보내진 사람과 같은 모양으로
   *  제출 수단을 숨기고 수업이 끝났다는 이유를 보여준다. 보관과 내보냄이
   *  동시에 참이어도 보관 쪽 문구가 우선한다 — "수업 자체가 끝났다"가 더
   *  근본적인 이유이고, 되돌리면(#294) 내보냄 여부만으로 다시 갈린다. */
  archived: boolean;
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
  eyebrow?: string;
  title: string;
  titleTestId?: string;
  /** `undefined`면 통과 배지를 아예 내지 않는다 — 미리보기는 아직 아무도
   *  푼 적이 없으므로 「통과」/「미통과」 어느 쪽도 사실이 아니다. */
  passed?: boolean;
  description: string;
  checklistItems: ParticipantChecklistItem[];
  submissionFormat: SubmissionFormat;
  submissions: ClassroomSubmissionRow[];
};

export function ProblemParticipantView(props: ProblemParticipantViewProps) {
  const {
    headingLevel = "h1",
    eyebrow = "클래스 · 문제",
    title,
    titleTestId,
    passed,
    description,
    checklistItems,
    submissionFormat,
    submissions,
  } = props;

  const checklistLabelById = new Map(checklistItems.map((item) => [item.id, item.label]));
  const requiredCount = checklistItems.filter((item) => item.required).length;

  return (
    <div className="flex flex-col gap-5">
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

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          {description.trim() === "" ? null : (
            <Card>
              <CardHeader title="설명" />
              <div className="p-4" data-testid="my-problem-description">
                <ProblemDescription markdown={description} />
              </div>
            </Card>
          )}

          <Card>
            <CardHeader title="체크리스트" hint={`필수 ${requiredCount}개를 전부 충족하면 통과`} />
            <ul data-testid="my-problem-checklist" className="divide-y divide-rule">
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
            <CardHeader title="내 시도" hint={submissions.length > 0 ? `${submissions.length}회` : undefined} />
            {submissions.length === 0 ? (
              <EmptyState>
                <span data-testid="submissions-empty-state">아직 낸 시도가 없습니다.</span>
              </EmptyState>
            ) : (
              <ol data-testid="submissions-list" className="divide-y divide-rule">
                {/* `id`는 채점 완료 알림(#329)이 특정 시도를 가리킬 때 쓰는
                    앵커다 — `lib/notifications/link.ts`가 같은 이름을 짓는다. */}
                {submissions.map((submission) => (
                  <li
                    key={submission.id}
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

                    {submission.status === "pending" && submission.pending_reason === "no_api_key" ? (
                      <p
                        data-testid={`submission-row-${submission.id}-no-api-key-note`}
                        className="mt-2.5 text-[12.5px] leading-relaxed text-ink/60"
                      >
                        강사가 아직 채점 키를 설정하지 않아 잠시 멈췄습니다.{" "}
                        <b className="font-medium text-ink">
                          당신의 잘못이 아니고, 다시 낼 필요도 없습니다.
                        </b>{" "}
                        강사가 채점 키를 넣으면 이어서 채점됩니다.
                      </p>
                    ) : null}

                    {submission.status === "scored" && submission.score ? (
                      <ul
                        data-testid={`submission-row-${submission.id}-verdicts`}
                        className="mt-3 flex flex-col gap-2 border-t border-rule pt-3"
                      >
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
                ))}
              </ol>
            )}
          </Card>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-4 lg:w-[380px]">
          <Card>
            <CardHeader title="제출" />
            <div className="flex flex-col gap-3.5 p-4">
              {props.interactive ? (
                <InteractiveSubmissionForm {...props} submissionFormat={submissionFormat} />
              ) : (
                <PreviewSubmissionForm submissionFormat={submissionFormat} />
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function InteractiveSubmissionForm(
  props: InteractiveProps & { submissionFormat: SubmissionFormat },
) {
  const {
    memberExpelled,
    archived,
    repositoryUrl,
    onRepositoryUrlChange,
    onRepositorySubmit,
    onSourceFile,
    submitting,
    submitError,
    uploadStatus,
    uploadError,
    submissionFormat,
  } = props;

  return (
    <>
      {archived ? (
        // 보관된 클래스는 내보내진 사람과 같은 모양으로 제출 수단을 숨긴다
        // (#294, #338 AC) — 지난 시도는 위 "내 시도" 카드에 그대로 남아
        // 있다. 되돌리면(POST .../unarchive) 이 분기를 벗어나 폼이 다시
        // 보인다.
        <ErrorNote>
          <span data-testid="class-archived-note">
            이 클래스는 보관되어 새 제출을 받지 않습니다. 지난 시도와 판정은 계속 볼 수
            있습니다.
          </span>
        </ErrorNote>
      ) : memberExpelled ? (
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
      ) : (
        <>
          {submissionFormat === "repository" ? (
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
function PreviewSubmissionForm({ submissionFormat }: { submissionFormat: SubmissionFormat }) {
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
