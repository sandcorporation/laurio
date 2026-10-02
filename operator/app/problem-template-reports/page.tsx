"use client";

// 신고된 템플릿 검토(#320 — 골간으로 옮긴다, #426/#421). 미리 심사하지 않고
// 바로 공개하되(#316) 신고로 내릴 수 있게 한 결정의 짝이다 — 사람이 판단하는
// 행위는 운영자 API로만 한다(Django admin은 쓰지 않는다, CLAUDE.md 「운영」).
//
// **내려도 이미 가져간 사람의 것은 그대로다.** 그건 설계의 결과이지 버그가
// 아니다 — 그 사실을 운영자가 오해하지 않도록 화면에 그대로 적어 둔다.
//
// **검토하면 목록에서 사라진다.** `decided`가 즉시 「처리했습니다」로 바꿔
// 보여주는 동안 `reload()`가 조회를 다시 하고, 그 결과(더 이상 신고 대기가
// 아니므로 서버가 돌려주지 않는다)가 도착하면 그 줄이 통째로 사라진다.
import { useState } from "react";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { ModerationForm } from "@/lib/problem-templates/moderation-form";
import { useReportedTemplates } from "@/lib/problem-templates/use-reported-templates";
import { MODERATION_DECISION_LABELS, type ModerationDecision } from "@/lib/problem-templates/types";

export default function ProblemTemplateReportsPage() {
  const session = useSession();
  const { state, reload } = useReportedTemplates(session.status === "authenticated");
  const [decided, setDecided] = useState<Record<number, ModerationDecision>>({});

  if (session.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  if (session.status === "unauthenticated") return null;

  return (
    <>
      <PageHeader
        crumb="할 일 · 신고된 템플릿"
        title="신고된 템플릿"
        description="내리면 이 목록에서 사라집니다 — 앞으로의 배포만 멈춥니다."
      />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        <p data-testid="problem-template-reports-note" className="text-[12.5px] text-ink/62">
          내려도 이미 가져간 사람의 문제·클래스는 영향을 받지 않습니다 — 사본이기
          때문입니다. 여기서 내리는 것은 앞으로의 배포를 멈추는 일입니다.
        </p>

        {state.status === "loading" && (
          <p data-testid="problem-template-reports-loading" className="text-[13px] text-ink/62">
            불러오는 중...
          </p>
        )}

        {state.status === "error" && (
          <p role="alert" data-testid="problem-template-reports-error" className="text-[13px] text-attention">
            불러오지 못했습니다.
          </p>
        )}

        {state.status === "loaded" && state.templates.length === 0 && (
          <p data-testid="problem-template-reports-empty" className="text-[13px] text-ink/62">
            확인할 신고가 없습니다.
          </p>
        )}

        {state.status === "loaded" && state.templates.length > 0 && (
          <div data-testid="problem-template-reports-list" className="border border-rule bg-surface">
            {state.templates.map((template, i) => (
              <div
                key={template.id}
                data-testid={`problem-template-report-row-${template.id}`}
                className={`flex flex-col gap-2.5 border-b border-rule px-4 py-3.5 last:border-b-0 ${
                  i % 2 === 1 ? "bg-ink/[2%]" : ""
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <h2
                    data-testid={`problem-template-report-row-${template.id}-title`}
                    className="text-[14px] font-semibold"
                  >
                    {template.title}
                  </h2>
                  <Badge testId={`problem-template-report-row-${template.id}-report-count`}>
                    신고 {template.report_count}건
                  </Badge>
                </div>
                <p
                  data-testid={`problem-template-report-row-${template.id}-publisher`}
                  className="text-[12.5px] text-ink/62"
                >
                  올린 사람: {template.publisher_display_name}
                </p>
                <p
                  data-testid={`problem-template-report-row-${template.id}-description`}
                  className="text-[13px] text-ink/62"
                >
                  {template.description}
                </p>
                <ul
                  data-testid={`problem-template-report-row-${template.id}-reasons`}
                  className="flex flex-wrap gap-1.5"
                >
                  {template.report_reasons.map((reason, index) => (
                    <li key={index}>
                      <Badge>{reason}</Badge>
                    </li>
                  ))}
                </ul>

                {decided[template.id] ? (
                  <p
                    data-testid={`problem-template-report-row-${template.id}-decided`}
                    className="text-[12.5px] text-ink/62"
                  >
                    {MODERATION_DECISION_LABELS[decided[template.id]]} 처리했습니다.
                  </p>
                ) : (
                  <ModerationForm
                    templateId={template.id}
                    onDecided={(decision) => {
                      setDecided((prev) => ({ ...prev, [template.id]: decision }));
                      reload();
                    }}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
