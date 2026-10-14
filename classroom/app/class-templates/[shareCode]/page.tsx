"use client";

// 클래스 템플릿 미리보기 + 가져오기 (#319) — 문제 템플릿 미리보기
// (`app/templates/[shareCode]/page.tsx`)과 같은 규율이다. 신고는 #319 AC에
// 없어 만들지 않는다.
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
import { importClassTemplate, takedownClassTemplate, type ClassTemplateRow } from "@/lib/class-templates/api";
import { useClassTemplatePreview } from "@/lib/class-templates/use-class-template-preview";
import { formatSubmissionFormats } from "@/lib/problems/api";
import { gradingGuidelineText, gradingStrictnessLabel } from "@/lib/problems/grading-guideline";

export default function ClassTemplatePreviewPage() {
  const params = useParams<{ shareCode: string }>();
  const shareCode = params.shareCode;
  const router = useRouter();
  const { state, reload } = useClassTemplatePreview(shareCode);

  const [name, setName] = useState("");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // 읽은 템플릿 이름으로 칸을 맞추는 일은 렌더 중에 한다(#675) — 효과로 넣으면 빈 칸이 먼저 그려져
  // 그 틈에 친 이름을 덮는다.
  const [seededTemplate, setSeededTemplate] = useState<ClassTemplateRow | null>(null);
  if (state.status === "ready" && state.template !== seededTemplate) {
    setSeededTemplate(state.template);
    setName(state.template.name);
  }

  const [takingDown, setTakingDown] = useState(false);
  const [takedownError, setTakedownError] = useState<string | null>(null);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="class-template-preview-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      </PageShell>
    );
  }

  if (state.status === "gone") {
    return (
      <PageShell>
        <h1 data-testid="class-template-preview-gone-heading" className="text-[21px] font-semibold">
          이 템플릿은 더 이상 사용할 수 없습니다
        </h1>
        <p className="mt-3 text-[13.5px] leading-relaxed text-ink/60">
          올린 사람이 내렸거나 운영자가 내린 템플릿입니다. 이미 가져간 사람의 클래스는 영향을
          받지 않습니다.
        </p>
        <p className="mt-6">
          <Link href="/templates" data-testid="class-template-preview-back-link" className={buttonClass("secondary")}>
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
          <span data-testid="class-template-preview-error">템플릿을 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const { template } = state;

  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImportError(null);
    setImporting(true);
    const result = await importClassTemplate(shareCode, name.trim());
    if (result.ok) {
      router.push(`/classes/${result.data.id}`);
    } else {
      setImportError(result.detail);
      setImporting(false);
    }
  }

  async function handleTakedown() {
    setTakedownError(null);
    setTakingDown(true);
    const result = await takedownClassTemplate(shareCode);
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
        eyebrow="클래스 템플릿"
        title={template.name}
        titleTestId="class-template-preview-heading"
        actions={
          template.taken_down ? <Badge tone="neutral">내려짐</Badge> : <Badge tone="verified">공개중</Badge>
        }
      />

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <Card>
            <CardHeader
              title="문제"
              hint={`${template.problem_count}개 · 순서 그대로 담깁니다`}
            />
            <p data-testid="class-template-preview-publisher" className="px-4 pt-4 text-[12.5px] text-ink/60">
              {template.publisher_display_name} 올림 ·{" "}
              {new Date(template.created_at).toLocaleDateString("ko-KR")}
            </p>
            {template.problems.length === 0 ? (
              <EmptyState>
                <span data-testid="class-template-preview-problems-empty">아직 문제가 없습니다.</span>
              </EmptyState>
            ) : (
              <ol data-testid="class-template-preview-problems" className="divide-y divide-rule">
                {template.problems.map((problem, index) => (
                  <li key={index} className="px-4 py-3.5">
                    <div className="flex items-center gap-2.5">
                      <span className="w-5 shrink-0 font-mono text-[12px] text-ink/30">{index + 1}</span>
                      <span data-testid={`class-template-preview-problem-${index}-title`} className="flex-1 text-[14px] font-medium">
                        {problem.title}
                      </span>
                      <span
                        data-testid={`class-template-preview-problem-${index}-formats`}
                        className="shrink-0 text-[12px] text-ink/45"
                      >
                        {formatSubmissionFormats(problem.submission_formats)}
                      </span>
                    </div>
                    <div
                      data-testid={`class-template-preview-problem-${index}-grading-guideline`}
                      className="mt-2 flex items-center gap-2 pl-8 text-[12px] text-ink/60"
                    >
                      <Badge>{gradingStrictnessLabel(problem.grading_strictness)}</Badge>
                      <span>
                        {gradingGuidelineText(problem.grading_strictness, problem.grading_guideline_text)}
                      </span>
                    </div>
                    {problem.syntax_check_enabled || problem.checklist_items.length > 0 ? (
                      <ul
                        data-testid={`class-template-preview-problem-${index}-checklist`}
                        className="mt-2 flex flex-col gap-1 pl-8"
                      >
                        {problem.syntax_check_enabled ? (
                          <li
                            data-testid={`class-template-preview-problem-${index}-syntax-check`}
                            className="flex items-center gap-2 text-[12.5px] text-ink/60"
                          >
                            <span className="flex-1">소스에 문법 오류가 없다</span>
                            <Badge>기본</Badge>
                            <Badge tone="attention">필수</Badge>
                          </li>
                        ) : null}
                        {problem.checklist_items.map((item, itemIndex) => (
                          <li key={itemIndex} className="flex items-center gap-2 text-[12.5px] text-ink/60">
                            <span className="flex-1">{item.label}</span>
                            {item.required ? <Badge tone="attention">필수</Badge> : <Badge tone="neutral">선택</Badge>}
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

        <div className="flex w-full shrink-0 flex-col gap-5 lg:w-[380px]">
          {template.taken_down ? (
            <Note>
              <span data-testid="class-template-preview-taken-down-notice">
                이 템플릿은 내려갔습니다. 이미 가져간 사람의 클래스에는 영향이 없습니다.
              </span>
            </Note>
          ) : (
            <Card>
              <CardHeader title="내 클래스로 가져오기" />
              <div className="flex flex-col gap-2.5 p-4">
                <form onSubmit={handleImport} className="flex flex-col gap-2.5">
                  <label htmlFor="class-template-import-name">
                    <FieldLabel>새 클래스 이름</FieldLabel>
                  </label>
                  <input
                    id="class-template-import-name"
                    data-testid="class-template-import-name-input"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    required
                    placeholder={template.name}
                    className={INPUT_CLASS}
                  />
                  <button
                    type="submit"
                    data-testid="class-template-import-submit"
                    disabled={importing || name.trim() === ""}
                    className={buttonClass("primary")}
                  >
                    {importing ? "가져오는 중..." : "가져오기"}
                  </button>
                  {name.trim() === "" ? (
                    <p data-testid="class-template-import-name-hint" className="text-[12px] text-ink/45">
                      새 클래스 이름을 입력하세요
                    </p>
                  ) : null}
                </form>
                {importError ? (
                  <ErrorNote>
                    <span data-testid="class-template-import-error">{importError}</span>
                  </ErrorNote>
                ) : null}
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  가져오면 새 클래스가 만들어집니다 — 문제와 체크리스트가 순서 그대로 오되
                  초안으로 들어오고, 참여자·제출물·판정·채점 키·채점 모델은 담기지 않습니다.
                  새 클래스는 자기만의 새 가입 코드를 갖습니다.
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
                    data-testid="class-template-takedown-button"
                    onClick={handleTakedown}
                    disabled={takingDown}
                    className={buttonClass("danger")}
                  >
                    {takingDown ? "내리는 중..." : "내리기"}
                  </button>
                )}
                {takedownError ? (
                  <ErrorNote>
                    <span data-testid="class-template-takedown-error">{takedownError}</span>
                  </ErrorNote>
                ) : null}
              </div>
            </Card>
          ) : null}
        </div>
      </div>
    </PageShell>
  );
}
