"use client";

// 내가 올린 템플릿 관리 (#316) — 내리기는 여기서 한다. 신고 큐와 달리
// 운영자가 아니라 올린 사람 본인의 화면이다.
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Card, EmptyState, ErrorNote, Num, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import { fetchMyProblemTemplates, takedownProblemTemplate, type ProblemTemplateRow } from "@/lib/problem-templates/api";

type State =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; templates: ProblemTemplateRow[] };

export default function MyProblemTemplatesPage() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [takingDown, setTakingDown] = useState<string | null>(null);
  const [takedownError, setTakedownError] = useState<string | null>(null);

  function reload() {
    setState({ status: "loading" });
    fetchMyProblemTemplates()
      .then((templates) => setState({ status: "ready", templates }))
      .catch(() => setState({ status: "error" }));
  }

  useEffect(() => {
    reload();
  }, []);

  async function handleTakedown(shareCode: string) {
    setTakingDown(shareCode);
    setTakedownError(null);
    try {
      await takedownProblemTemplate(shareCode);
      reload();
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
        titleTestId="my-problem-templates-heading"
        actions={
          <Link href="/templates" data-testid="my-problem-templates-back-link" className={buttonClass("secondary")}>
            전체 목록
          </Link>
        }
      />

      {state.status === "loading" ? (
        <p data-testid="my-problem-templates-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      ) : state.status === "error" ? (
        <ErrorNote>
          <span data-testid="my-problem-templates-error">템플릿 목록을 불러오지 못했습니다.</span>
        </ErrorNote>
      ) : state.templates.length === 0 ? (
        <Card>
          <EmptyState>
            <span data-testid="my-problem-templates-empty-state">
              아직 올린 템플릿이 없습니다. 문제 편집 화면에서 공개할 수 있습니다.
            </span>
          </EmptyState>
        </Card>
      ) : (
        <>
          {takedownError ? (
            <div className="mb-3">
              <ErrorNote>
                <span data-testid="my-problem-templates-takedown-error">{takedownError}</span>
              </ErrorNote>
            </div>
          ) : null}
          <Card>
            <ul data-testid="my-problem-templates-list" className="divide-y divide-rule">
              {state.templates.map((template) => (
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
                      onClick={() => handleTakedown(template.share_code)}
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
        </>
      )}
    </PageShell>
  );
}
