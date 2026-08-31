"use client";

// 이의 상세(#66) — 심판에 필요한 것을 한 화면에 모은다: 이의 사유, Score
// 스냅샷(재채점이 아니라 그때 실제로 일어난 판정, ADR-0006), 그리고 기본으로
// 접힌 소스(ADR-0022, lib/appeals/source-reveal.tsx). 이미 심판된 이의는 그
// 결과를 읽기 전용으로 보여줄 뿐, 심판 폼은 여기서 만들지 않는다 — 인용/기각
// 흐름은 별도 티켓(#67)의 몫이다.
import { useParams } from "next/navigation";

import { useSession } from "@/lib/auth/use-session";
import { useAppealDetail } from "@/lib/appeals/use-appeal-detail";
import { APPEAL_STATUS_LABELS } from "@/lib/appeals/types";
import { SourceReveal } from "@/lib/appeals/source-reveal";

export default function AppealDetailPage() {
  const params = useParams<{ id: string }>();
  const appealId = params.id;
  const session = useSession();
  const state = useAppealDetail(appealId, session.status === "authenticated");

  if (session.status === "loading") {
    return (
      <main>
        <p data-testid="session-loading">불러오는 중...</p>
      </main>
    );
  }
  if (session.status === "unauthenticated") return null;

  if (state.status === "loading") {
    return (
      <main>
        <p data-testid="appeal-detail-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "redirecting") {
    // 401을 만나 로그인으로 이동하는 중이다(코드리뷰 지적 — use-appeal-detail.ts
    // 참고) — 이 프레임에서는 아무것도 그리지 않는다. useSession의
    // "unauthenticated" 분기와 같은 자리다.
    return null;
  }

  if (state.status === "not-found") {
    return (
      <main>
        <p data-testid="appeal-detail-not-found">이의를 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main>
        <p role="alert" data-testid="appeal-detail-error">
          이의를 불러오지 못했습니다.
        </p>
      </main>
    );
  }

  const { appeal } = state;

  return (
    <main>
      <h1 data-testid="appeal-detail-heading">이의 #{appeal.id}</h1>
      <p data-testid="appeal-detail-submission">Submission #{appeal.submission_id}</p>
      <p data-testid="appeal-detail-status">{APPEAL_STATUS_LABELS[appeal.status]}</p>
      <p data-testid="appeal-detail-created-at">
        {new Date(appeal.created_at).toLocaleString("ko-KR")}
      </p>

      <section data-testid="appeal-detail-reason-section">
        <h2>이의 사유</h2>
        <p data-testid="appeal-detail-reason">{appeal.reason}</p>
      </section>

      <section data-testid="appeal-detail-score">
        <h2>Score 스냅샷</h2>
        <p data-testid="appeal-detail-score-percentage">{appeal.score.percentage}%</p>
        <p data-testid="appeal-detail-score-model-version">{appeal.score.model_version}</p>
        <p data-testid="appeal-detail-score-created-at">
          {new Date(appeal.score.created_at).toLocaleString("ko-KR")}
        </p>
        <pre data-testid="appeal-detail-score-reasoning">
          {JSON.stringify(appeal.score.reasoning, null, 2)}
        </pre>
      </section>

      {/* 심판 폼이 아니라 읽기 전용 결과다 — 심판이 이미 끝난 이의는 폼을 아예
          내주지 않는다(#66 스코프 펜스, #67이 실제 심판 흐름을 만든다). */}
      {appeal.ruling && (
        <section data-testid="appeal-detail-ruling">
          <h2>심판 결과</h2>
          <p data-testid="appeal-detail-ruling-decision">
            {APPEAL_STATUS_LABELS[appeal.ruling.decision]}
          </p>
          <p data-testid="appeal-detail-ruling-ruled-by">{appeal.ruling.ruled_by_username}</p>
          <p data-testid="appeal-detail-ruling-note">{appeal.ruling.note}</p>
          <p data-testid="appeal-detail-ruling-ruled-at">
            {new Date(appeal.ruling.ruled_at).toLocaleString("ko-KR")}
          </p>
          {appeal.ruling.correction_amount !== null && (
            <p data-testid="appeal-detail-ruling-correction-amount">
              {appeal.ruling.correction_amount}
            </p>
          )}
        </section>
      )}

      <SourceReveal appealId={appeal.id} />
    </main>
  );
}
