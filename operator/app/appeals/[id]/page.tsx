"use client";

// 이의 상세(#66) — 심판에 필요한 것을 한 화면에 모은다: 이의 사유, Score
// 스냅샷(재채점이 아니라 그때 실제로 일어난 판정, ADR-0006), 그리고 기본으로
// 접힌 소스(ADR-0022, lib/appeals/source-reveal.tsx). 심판이 아직 없는(pending)
// 이의는 인용/기각 폼을 보여주고(#67), 이미 심판된 이의는 그 폼 대신 확정된
// 결과를 읽기 전용으로 보여준다 — 서버의 409(조건부 UPDATE)와 이 화면이 폼을
// 아예 주지 않는 것, 둘 다 이중 심판을 막는 방어다.
import { useParams } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/lib/auth/use-session";
import { useAppealDetail } from "@/lib/appeals/use-appeal-detail";
import type { AppealRuling } from "@/lib/appeals/types";
import { appealStatusLabel } from "@/lib/appeals/types";
import { SourceReveal } from "@/lib/appeals/source-reveal";
import { RulingForm } from "@/lib/appeals/ruling-form";

export default function AppealDetailPage() {
  const params = useParams<{ id: string }>();
  const appealId = params.id;
  const session = useSession();
  const state = useAppealDetail(appealId, session.status === "authenticated");

  // 심판 직후 화면을 "확정된 심판을 보여주는 상태로" 바꾸기 위한 로컬 오버레이
  // (#67 AC). useAppealDetail은 마운트 시 한 번만 조회하므로, 심판 성공 뒤
  // 서버를 다시 조회하지 않고도 폼 대신 결과가 보이려면 이 상태가 필요하다.
  //
  // **어느 이의의 오버레이인지도 함께 들고 있는다(코드리뷰 지적).** appealId만
  // 보고 override를 무조건 쓰면, 이 이의를 심판한 뒤 상세→상세로 클라이언트
  // 내비게이션해 다른(아직 pending인) 이의를 열었을 때 useAppealDetail은 새
  // 이의를 다시 조회하는데 override는 이전 이의의 값 그대로 남아 있어 "다른
  // 이의의 심판 결과가 보이고 pending 이의에 폼이 안 뜨는" 사고가 난다.
  // override가 지금 보고 있는 appealId의 것일 때만 쓴다.
  const [ruledOverride, setRuledOverride] = useState<{
    appealId: string;
    ruling: AppealRuling;
  } | null>(null);

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
  // 심판 직후에는 서버를 다시 조회하지 않고 로컬 오버레이를 우선한다 — 화면이
  // "확정된 심판을 보여주는 상태로 바뀐다"는 AC를 즉시 만족시킨다(#67). 단,
  // 오버레이가 지금 appealId의 것일 때만 — 다른 이의를 심판한 뒤 이 이의로
  // 넘어온 경우까지 덮어써서는 안 된다(코드리뷰 지적).
  const activeOverride =
    ruledOverride && ruledOverride.appealId === appealId ? ruledOverride.ruling : null;
  const ruling = activeOverride ?? appeal.ruling;
  const status = activeOverride ? activeOverride.decision : appeal.status;

  return (
    <main>
      <h1 data-testid="appeal-detail-heading">이의 #{appeal.id}</h1>
      <p data-testid="appeal-detail-submission">Submission #{appeal.submission_id}</p>
      <p data-testid="appeal-detail-status">{appealStatusLabel(status)}</p>
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

      {/* 심판이 아직 없으면(pending) 인용/기각 폼을, 있으면 읽기 전용 결과를
          보여준다 — 이미 심판된 이의에는 폼이 아예 없다(#67 AC). 서버의 409
          (조건부 UPDATE)와 이 분기가 이중 심판을 막는 두 겹의 방어다. */}
      {!ruling && (
        <RulingForm
          appealId={appeal.id}
          onRuled={(newRuling) => setRuledOverride({ appealId, ruling: newRuling })}
        />
      )}

      {ruling && (
        <section data-testid="appeal-detail-ruling">
          <h2>심판 결과</h2>
          <p data-testid="appeal-detail-ruling-decision">{appealStatusLabel(ruling.decision)}</p>
          <p data-testid="appeal-detail-ruling-ruled-by">{ruling.ruled_by_username}</p>
          <p data-testid="appeal-detail-ruling-note">{ruling.note}</p>
          <p data-testid="appeal-detail-ruling-ruled-at">
            {new Date(ruling.ruled_at).toLocaleString("ko-KR")}
          </p>
          {ruling.correction_amount !== null && (
            <p data-testid="appeal-detail-ruling-correction-amount">{ruling.correction_amount}</p>
          )}
        </section>
      )}

      <SourceReveal appealId={appeal.id} />
    </main>
  );
}
