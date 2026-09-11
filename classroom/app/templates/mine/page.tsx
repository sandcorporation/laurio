"use client";

// 내가 올린 템플릿 관리 (#316/#319) — 내리기는 여기서 한다. 신고 큐와 달리
// 운영자가 아니라 올린 사람 본인의 화면이다. 「문제」·「클래스」 탭이 두 종류를
// 구별한다(#319 AC "목록에서 구별된다") — `/templates`와 같은 규율이다.
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Card, EmptyState, ErrorNote, Num, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import {
  fetchMyClassTemplates,
  takedownClassTemplate,
  type ClassTemplateRow,
} from "@/lib/class-templates/api";
import { fetchMyProblemTemplates, takedownProblemTemplate, type ProblemTemplateRow } from "@/lib/problem-templates/api";

type Kind = "problem" | "class";

type ProblemState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; templates: ProblemTemplateRow[] };

type ClassState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; templates: ClassTemplateRow[] };

export default function MyTemplatesPage() {
  const [kind, setKind] = useState<Kind>("problem");

  const [problemState, setProblemState] = useState<ProblemState>({ status: "loading" });
  const [classState, setClassState] = useState<ClassState>({ status: "loading" });

  const [takingDown, setTakingDown] = useState<string | null>(null);
  const [takedownError, setTakedownError] = useState<string | null>(null);

  function reloadProblems() {
    setProblemState({ status: "loading" });
    fetchMyProblemTemplates()
      .then((templates) => setProblemState({ status: "ready", templates }))
      .catch(() => setProblemState({ status: "error" }));
  }

  function reloadClasses() {
    setClassState({ status: "loading" });
    fetchMyClassTemplates()
      .then((templates) => setClassState({ status: "ready", templates }))
      .catch(() => setClassState({ status: "error" }));
  }

  useEffect(() => {
    reloadProblems();
    reloadClasses();
  }, []);

  async function handleTakedownProblem(shareCode: string) {
    setTakingDown(shareCode);
    setTakedownError(null);
    try {
      await takedownProblemTemplate(shareCode);
      reloadProblems();
    } catch {
      setTakedownError("내리지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setTakingDown(null);
    }
  }

  async function handleTakedownClass(shareCode: string) {
    setTakingDown(shareCode);
    setTakedownError(null);
    try {
      await takedownClassTemplate(shareCode);
      reloadClasses();
    } catch {
      setTakedownError("내리지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setTakingDown(null);
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="강의실 · 템플릿"
        title="내가 올린 템플릿"
        titleTestId="my-templates-heading"
        actions={
          <Link href="/templates" data-testid="my-templates-back-link" className={buttonClass("secondary")}>
            전체 목록
          </Link>
        }
      />

      <div
        role="tablist"
        aria-label="템플릿 종류"
        className="mb-5 flex items-end gap-0.5 border-b border-rule"
      >
        {(
          [
            ["problem", "문제", "my-templates-tab-problem"],
            ["class", "클래스", "my-templates-tab-class"],
          ] as const
        ).map(([key, label, testId]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={kind === key}
            data-testid={testId}
            onClick={() => setKind(key)}
            className={
              kind === key
                ? "-mb-px border border-rule border-b-surface bg-surface px-4 py-2 text-[13.5px] font-medium"
                : "px-4 py-2 text-[13.5px] text-ink/60 hover:text-ink"
            }
          >
            {label}
          </button>
        ))}
      </div>

      {takedownError ? (
        <div className="mb-3">
          <ErrorNote>
            <span data-testid="my-templates-takedown-error">{takedownError}</span>
          </ErrorNote>
        </div>
      ) : null}

      {kind === "problem" ? (
        problemState.status === "loading" ? (
          <p data-testid="my-problem-templates-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
        ) : problemState.status === "error" ? (
          <ErrorNote>
            <span data-testid="my-problem-templates-error">템플릿 목록을 불러오지 못했습니다.</span>
          </ErrorNote>
        ) : problemState.templates.length === 0 ? (
          <Card>
            <EmptyState>
              <span data-testid="my-problem-templates-empty-state">
                아직 올린 템플릿이 없습니다. 문제 편집 화면에서 공개할 수 있습니다.
              </span>
            </EmptyState>
          </Card>
        ) : (
          <Card>
            <ul data-testid="my-problem-templates-list" className="divide-y divide-rule">
              {problemState.templates.map((template) => (
                <li
                  key={template.share_code}
                  data-testid={`my-problem-template-row-${template.share_code}`}
                  className="flex flex-wrap items-center justify-between gap-3 px-4 py-4"
                >
                  <div className="min-w-0">
                    <Link
                      href={`/templates/${template.share_code}`}
                      className="text-[15px] font-medium text-ink hover:underline"
                    >
                      {template.title}
                    </Link>
                    <div className="mt-1 text-[12px] text-ink/45">
                      <Num>{new Date(template.created_at).toLocaleDateString("ko-KR")}</Num> 공개
                    </div>
                  </div>
                  {template.taken_down ? (
                    <Badge tone="neutral">내려짐</Badge>
                  ) : (
                    <button
                      type="button"
                      data-testid={`my-problem-template-row-${template.share_code}-takedown`}
                      onClick={() => handleTakedownProblem(template.share_code)}
                      disabled={takingDown === template.share_code}
                      className={buttonClass("danger", "sm")}
                    >
                      {takingDown === template.share_code ? "내리는 중..." : "내리기"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )
      ) : classState.status === "loading" ? (
        <p data-testid="my-class-templates-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      ) : classState.status === "error" ? (
        <ErrorNote>
          <span data-testid="my-class-templates-error">템플릿 목록을 불러오지 못했습니다.</span>
        </ErrorNote>
      ) : classState.templates.length === 0 ? (
        <Card>
          <EmptyState>
            <span data-testid="my-class-templates-empty-state">
              아직 올린 클래스 템플릿이 없습니다. 클래스 상세 화면에서 공개할 수 있습니다.
            </span>
          </EmptyState>
        </Card>
      ) : (
        <Card>
          <ul data-testid="my-class-templates-list" className="divide-y divide-rule">
            {classState.templates.map((template) => (
              <li
                key={template.share_code}
                data-testid={`my-class-template-row-${template.share_code}`}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-4"
              >
                <div className="min-w-0">
                  <Link
                    href={`/class-templates/${template.share_code}`}
                    className="text-[15px] font-medium text-ink hover:underline"
                  >
                    {template.name}
                  </Link>
                  <div className="mt-1 text-[12px] text-ink/45">
                    <Num>{new Date(template.created_at).toLocaleDateString("ko-KR")}</Num> 공개 ·{" "}
                    {template.problem_count}개 문제
                  </div>
                </div>
                {template.taken_down ? (
                  <Badge tone="neutral">내려짐</Badge>
                ) : (
                  <button
                    type="button"
                    data-testid={`my-class-template-row-${template.share_code}-takedown`}
                    onClick={() => handleTakedownClass(template.share_code)}
                    disabled={takingDown === template.share_code}
                    className={buttonClass("danger", "sm")}
                  >
                    {takingDown === template.share_code ? "내리는 중..." : "내리기"}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PageShell>
  );
}
