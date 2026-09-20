"use client";

// 템플릿 미리보기 + 가져오기 + 신고 (#316/#320). 로그인은 middleware.ts가
// 이미 보장한다 — `/join/[code]`와 달리 needsLogin 분기가 없다.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

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
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { defaultCopyTarget, selectCopyTargets } from "@/lib/classes/copy-targets";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import { importProblemTemplate, reportProblemTemplate, takedownProblemTemplate } from "@/lib/problem-templates/api";
import { useTemplatePreview } from "@/lib/problem-templates/use-template-preview";
import { formatSubmissionFormats } from "@/lib/problems/api";
import { gradingGuidelineText, gradingStrictnessLabel } from "@/lib/problems/grading-guideline";

export default function ProblemTemplatePreviewPage() {
  const params = useParams<{ shareCode: string }>();
  const shareCode = params.shareCode;
  const router = useRouter();
  const { state, reload } = useTemplatePreview(shareCode);
  const myClassesState = useMyClasses();

  const [targetClassId, setTargetClassId] = useState("");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  useEffect(() => {
    if (myClassesState.status !== "ready") return;
    const target = defaultCopyTarget(myClassesState.classes);
    if (target) setTargetClassId(String(target.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [myClassesState]);

  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportDone, setReportDone] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const [takingDown, setTakingDown] = useState(false);
  const [takedownError, setTakedownError] = useState<string | null>(null);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="template-preview-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "gone") {
    return (
      <PageShell>
        <h1 data-testid="template-preview-gone-heading" className="text-[21px] font-semibold">
          이 템플릿은 더 이상 사용할 수 없습니다
        </h1>
        <p className="mt-3 text-[13.5px] leading-relaxed text-ink/60">
          올린 사람이 내렸거나 운영자가 내린 템플릿입니다. 이미 가져간 사람의 클래스는 영향을
          받지 않습니다.
        </p>
        <p className="mt-6">
          <Link href="/templates" data-testid="template-preview-back-link" className={buttonClass("secondary")}>
            목록으로
          </Link>
        </p>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="template-preview-error">템플릿을 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const { template } = state;

  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImportError(null);
    setImporting(true);
    const result = await importProblemTemplate(shareCode, Number(targetClassId));
    if (result.ok) {
      router.push(`/classes/${result.data.classroom_id}/problems/${result.data.id}`);
    } else {
      setImportError(result.detail);
      setImporting(false);
    }
  }

  async function handleReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setReportError(null);
    setReportSubmitting(true);
    const result = await reportProblemTemplate(shareCode, reportReason.trim());
    if (result.ok) {
      setReportDone(true);
      setReportOpen(false);
    } else {
      setReportError(result.detail);
    }
    setReportSubmitting(false);
  }

  async function handleTakedown() {
    setTakedownError(null);
    setTakingDown(true);
    const result = await takedownProblemTemplate(shareCode);
    if (result.ok) {
      reload();
    } else {
      setTakedownError(result.detail);
    }
    setTakingDown(false);
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스 · 템플릿"
        title={template.title}
        titleTestId="template-preview-heading"
        actions={
          template.taken_down ? <Badge tone="neutral">내려짐</Badge> : <Badge tone="verified">공개중</Badge>
        }
      />

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <Card>
            <CardHeader title="설명" />
            <div className="p-4">
              <p data-testid="template-preview-publisher" className="mb-3 text-[12.5px] text-ink/60">
                {template.publisher_display_name} 올림 ·{" "}
                {new Date(template.created_at).toLocaleDateString("ko-KR")}
              </p>
              {/* 참여자 화면·문제 편집의 미리보기와 **같은 렌더러**다(2026-09-16,
                  `@codemit/markdown`) — 여기만 `whitespace-pre-wrap` 한 덩이로 남아 있어
                  `##` 과 표가 글자로 보였다. 가져오기 전에 「이 문제가 실제로 어떻게
                  보이나」를 확인하는 자리이므로 복사·파일로 저장 버튼까지 그대로 준다
                  (#325 의 「미리보기는 미리보기여야 한다」와 같은 논리).
                  `MarkdownView` 는 설명이 비면 아무것도 그리지 않으므로(null) 그
                  자리에 쓰던 문구를 그대로 유지한다 — 「설명이 없다」와 「불러오기가
                  덜 됐다」가 구별돼야 한다. */}
              <div data-testid="template-preview-description">
                {template.description.trim() === "" ? (
                  <p className="text-[13.5px] leading-relaxed">설명이 없습니다.</p>
                ) : (
                  <MarkdownView markdown={template.description} fileBaseName={template.title} />
                )}
              </div>
              <p data-testid="template-preview-format" className="mt-3 text-[12.5px] text-ink/60">
                제출 형식: {formatSubmissionFormats(template.submission_formats)}
              </p>
            </div>
          </Card>

          <Card>
            <CardHeader title="체크리스트" hint="필수를 전부 충족하면 「통과」" />
            <div
              data-testid="template-preview-grading-guideline"
              className="flex flex-col gap-1 border-b border-rule px-4 py-3"
            >
              <div className="flex items-center gap-2">
                <Badge>{gradingStrictnessLabel(template.grading_strictness)}</Badge>
                <span className="text-[12px] font-medium text-ink/60">채점 지침</span>
              </div>
              <p
                data-testid="template-preview-grading-guideline-text"
                className="text-[12.5px] leading-relaxed text-ink/60"
              >
                {gradingGuidelineText(template.grading_strictness, template.grading_guideline_text)}
              </p>
            </div>
            {template.syntax_check_enabled ? (
              <div
                data-testid="template-preview-syntax-check"
                className="flex items-center gap-3 border-b border-rule px-4 py-3 text-[13.5px]"
              >
                <span className="flex-1">소스에 문법 오류가 없다</span>
                <span className="flex shrink-0 gap-1.5">
                  <Badge>기본</Badge>
                  <Badge tone="attention">필수</Badge>
                </span>
              </div>
            ) : null}
            {template.checklist_items.length === 0 ? (
              <EmptyState>
                <span data-testid="template-preview-checklist-empty">아직 항목이 없습니다.</span>
              </EmptyState>
            ) : (
              <ul data-testid="template-preview-checklist" className="divide-y divide-rule">
                {template.checklist_items.map((item, index) => (
                  <li key={index} className="flex items-center gap-2.5 px-4 py-3 text-[13.5px]">
                    <span className="w-4 shrink-0 font-mono text-[11.5px] text-ink/30">{index + 1}</span>
                    <span className="flex-1">{item.label}</span>
                    {item.required ? <Badge tone="attention">필수</Badge> : <Badge tone="neutral">선택</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-5 lg:w-[380px]">
          {template.taken_down ? (
            <Note>
              <span data-testid="template-preview-taken-down-notice">
                이 템플릿은 내려갔습니다. 이미 가져간 사람의 클래스에는 영향이 없습니다.
              </span>
            </Note>
          ) : (
            <Card>
              <CardHeader title="내 클래스로 가져오기" />
              <div className="flex flex-col gap-2.5 p-4">
                {myClassesState.status === "ready" ? (
                  (() => {
                    const selection = selectCopyTargets(myClassesState.classes);
                    if (selection.kind === "no-classes") {
                      return (
                        <div className="flex flex-col items-start gap-2.5">
                          <p data-testid="template-import-no-target" className="text-[13px] text-ink/45">
                            가져올 클래스가 없습니다. 먼저 클래스를 열어주세요.
                          </p>
                          <Link
                            href="/classes/new"
                            data-testid="template-import-no-target-new-class-link"
                            className={buttonClass("secondary", "sm")}
                          >
                            새 클래스 열기
                          </Link>
                        </div>
                      );
                    }
                    if (selection.kind === "all-archived") {
                      return (
                        <p data-testid="template-import-all-archived" className="text-[13px] text-ink/45">
                          내 클래스가 모두 보관되어 있어 가져올 수 없습니다.
                        </p>
                      );
                    }
                    return (
                      <form onSubmit={handleImport} className="flex flex-col gap-2.5">
                        <label htmlFor="template-import-target">
                          <FieldLabel>대상 클래스</FieldLabel>
                        </label>
                        <select
                          id="template-import-target"
                          data-testid="template-import-target-select"
                          value={targetClassId}
                          onChange={(event) => setTargetClassId(event.target.value)}
                          className={INPUT_CLASS}
                        >
                          <option value="" data-testid="template-import-target-option-empty">
                            클래스를 선택하세요
                          </option>
                          {selection.classes.map((c) => (
                            <option key={c.id} value={c.id} data-testid={`template-import-target-option-${c.id}`}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                        <button
                          type="submit"
                          data-testid="template-import-submit"
                          disabled={importing || targetClassId === ""}
                          className={buttonClass("primary")}
                        >
                          {importing ? "가져오는 중..." : "가져오기"}
                        </button>
                        {targetClassId === "" ? (
                          <p data-testid="template-import-target-hint" className="text-[12px] text-ink/45">
                            가져올 클래스를 먼저 고르세요
                          </p>
                        ) : null}
                      </form>
                    );
                  })()
                ) : (
                  <p data-testid="template-import-classes-loading" className="text-[13px] text-ink/45">
                    클래스 목록을 불러오는 중...
                  </p>
                )}
                {importError ? (
                  <ErrorNote>
                    <span data-testid="template-import-error">{importError}</span>
                  </ErrorNote>
                ) : null}
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  체크리스트가 순서 그대로 옵니다. 채점 모델은 이 템플릿을 만든 사람 것이 아니라
                  대상 클래스의 기본값을 따릅니다. 가져온 문제는 초안으로 들어옵니다.
                </span>
              </div>
            </Card>
          )}

          {template.is_mine ? (
            <Card>
              <CardHeader title="내 템플릿" />
              <div className="flex flex-col gap-2.5 p-4">
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  내려도 이미 가져간 사람의 클래스는 그대로입니다.
                </span>
                {template.taken_down ? null : (
                  <button
                    type="button"
                    data-testid="template-takedown-button"
                    onClick={handleTakedown}
                    disabled={takingDown}
                    className={buttonClass("danger")}
                  >
                    {takingDown ? "내리는 중..." : "내리기"}
                  </button>
                )}
                {takedownError ? (
                  <ErrorNote>
                    <span data-testid="template-takedown-error">{takedownError}</span>
                  </ErrorNote>
                ) : null}
              </div>
            </Card>
          ) : (
            <Card>
              <CardHeader title="신고" />
              <div className="flex flex-col gap-2.5 p-4">
                {reportDone ? (
                  <Note>
                    <span data-testid="template-report-done">신고가 접수되었습니다. 운영자가 확인합니다.</span>
                  </Note>
                ) : reportOpen ? (
                  <form onSubmit={handleReport} className="flex flex-col gap-2.5">
                    <label htmlFor="template-report-reason">
                      <FieldLabel>신고 사유</FieldLabel>
                    </label>
                    <textarea
                      id="template-report-reason"
                      data-testid="template-report-reason-input"
                      value={reportReason}
                      onChange={(event) => setReportReason(event.target.value)}
                      rows={3}
                      required
                      className={`${INPUT_CLASS} resize-y`}
                    />
                    <button
                      type="submit"
                      data-testid="template-report-submit"
                      disabled={reportSubmitting || reportReason.trim() === ""}
                      className={buttonClass("secondary")}
                    >
                      {reportSubmitting ? "접수하는 중..." : "신고하기"}
                    </button>
                  </form>
                ) : (
                  <button
                    type="button"
                    data-testid="template-report-open"
                    onClick={() => setReportOpen(true)}
                    className={buttonClass("secondary")}
                  >
                    부적절한 템플릿 신고
                  </button>
                )}
                {reportError ? (
                  <ErrorNote>
                    <span data-testid="template-report-error">{reportError}</span>
                  </ErrorNote>
                ) : null}
              </div>
            </Card>
          )}
        </div>
      </div>
    </PageShell>
  );
}
