"use client";

// 템플릿 미리보기 + 가져오기 + 신고 (#316/#320). 로그인은 middleware.ts가
// 이미 보장한다 — `/join/[code]`와 달리 needsLogin 분기가 없다.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

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
import { BackendError } from "@/lib/backend/client";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import { importProblemTemplate, reportProblemTemplate, takedownProblemTemplate } from "@/lib/problem-templates/api";
import { useTemplatePreview } from "@/lib/problem-templates/use-template-preview";

export default function ProblemTemplatePreviewPage() {
  const params = useParams<{ shareCode: string }>();
  const shareCode = params.shareCode;
  const router = useRouter();
  const { state, reload } = useTemplatePreview(shareCode);
  const myClassesState = useMyClasses();

  const [targetClassId, setTargetClassId] = useState("");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

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
    try {
      const problem = await importProblemTemplate(shareCode, Number(targetClassId));
      router.push(`/classes/${problem.classroom_id}/problems/${problem.id}`);
    } catch {
      setImportError("가져오지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setImporting(false);
    }
  }

  async function handleReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setReportError(null);
    setReportSubmitting(true);
    try {
      await reportProblemTemplate(shareCode, reportReason.trim());
      setReportDone(true);
      setReportOpen(false);
    } catch (err) {
      if (err instanceof BackendError) {
        setReportError(err.message);
      } else {
        setReportError("신고를 접수하지 못했습니다. 잠시 후 다시 시도해주세요.");
      }
    } finally {
      setReportSubmitting(false);
    }
  }

  async function handleTakedown() {
    setTakedownError(null);
    setTakingDown(true);
    try {
      await takedownProblemTemplate(shareCode);
      reload();
    } catch {
      setTakedownError("내리지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setTakingDown(false);
    }
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
              <p data-testid="template-preview-description" className="whitespace-pre-wrap text-[13.5px] leading-relaxed">
                {template.description || "설명이 없습니다."}
              </p>
              <p data-testid="template-preview-format" className="mt-3 text-[12.5px] text-ink/60">
                제출 형식: {template.submission_format === "source" ? "소스" : "저장소"}
              </p>
            </div>
          </Card>

          <Card>
            <CardHeader title="체크리스트" hint="필수를 전부 충족하면 「통과」" />
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
                  myClassesState.classes.length === 0 ? (
                    <p data-testid="template-import-no-target" className="text-[13px] text-ink/45">
                      가져올 클래스가 없습니다. 먼저 클래스를 열어주세요.
                    </p>
                  ) : (
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
                        {myClassesState.classes.map((c) => (
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
                    </form>
                  )
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
                      className={buttonClass("danger")}
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
