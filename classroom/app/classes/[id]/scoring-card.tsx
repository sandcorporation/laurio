"use client";

// 오른쪽 「채점」 카드(#633, 시안 v2) — 예전에 흩어져 있던 배너 넷(키 없음·거부됨·크레딧 소진·서버
// 연결 불가)이 이 카드의 상태 한 줄이다. 조건은 배너의 것을 그대로 읽는다(`scoring-status.ts`).
// 멀쩡할 때는 기본 모델·채점 횟수·사용량이 보이고, 문제가 있을 때만 붉은 배지와 갈 곳이 붙는다.
// 사용량은 누적 토큰이다 — OpenAI 키 연결이면 지금 설정으로 셈한 원화 어림이 따른다.
import Link from "next/link";

import { Badge, Card, buttonClass } from "@/app/components/ui";
import type { ClassRow } from "@/lib/classes/api";
import {
  SCORING_STATUS_LABEL,
  scoringStatus,
  scoringStatusTone,
  type ScoringStatus,
} from "@/lib/classes/scoring-status";
import { findCostRow, formatKrw, usageKrw } from "@/lib/scoring/cost";
import { useScoringCost } from "@/lib/scoring/use-scoring-cost";

function Row({ label, testId, children }: { label: string; testId: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[12.5px]" data-testid={testId}>
      <span className="text-ink/60">{label}</span>
      <span className="text-right font-mono">{children}</span>
    </div>
  );
}

function UsageRow({ classroom }: { classroom: ClassRow }) {
  const cost = useScoringCost(classroom.id);
  const tokens = classroom.token_usage_total;
  let won: string | null = null;
  if (cost.status === "ready" && cost.estimate.unit === "krw") {
    const krw = usageKrw(tokens, findCostRow(cost.estimate, classroom.default_model, classroom.default_reasoning_effort));
    if (krw !== null && krw > 0) won = formatKrw(krw);
  }
  return (
    <Row label="사용량" testId="scoring-card-usage">
      {tokens.toLocaleString("ko-KR")} 토큰
      {won ? ` · ${won}` : ""}
      {classroom.token_usage_estimated > 0 ? (
        <span data-testid="scoring-card-usage-estimated" className="ml-1.5 font-sans text-[11px] text-ink/45">
          어림 {classroom.token_usage_estimated.toLocaleString("ko-KR")}
        </span>
      ) : null}
    </Row>
  );
}

const PROBLEM_TESTID: Record<Exclude<ScoringStatus["kind"], "connected" | "missing">, string> = {
  rejected: "classroom-rejected-api-key-banner",
  exhausted: "classroom-exhausted-credit-banner",
  unreachable: "classroom-unreachable-server-banner",
};

export function ScoringCard({ classroom }: { classroom: ClassRow }) {
  const classId = classroom.id;
  const status = scoringStatus(classroom);
  const isOwner = classroom.role === "owner";
  const settings = `/classes/${classId}/settings`;

  return (
    <Card>
      <div className="flex items-center justify-between gap-3 border-b border-rule px-4 py-3">
        <h2 className="text-[15px] font-semibold tracking-[-0.005em]">채점</h2>
        <Link
          href={settings}
          data-testid="scoring-card-settings-link"
          className="whitespace-nowrap px-1 py-1 text-xs text-ink/60 underline underline-offset-[3px] hover:text-ink"
        >
          설정
        </Link>
      </div>
      <div className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2" data-testid="scoring-card-status">
          {status.kind === "connected" ? (
            <>
              <span data-testid="scoring-card-connected">
                <Badge tone="verified">{SCORING_STATUS_LABEL.connected}</Badge>
              </span>
              <span data-testid="scoring-card-connection" className="text-[12.5px] text-ink/60">
                {status.connection}
              </span>
            </>
          ) : (
            <span
              data-testid={
                status.kind === "missing" ? "classroom-missing-api-key-banner" : PROBLEM_TESTID[status.kind]
              }
            >
              <Badge tone={scoringStatusTone(status)}>{SCORING_STATUS_LABEL[status.kind]}</Badge>
            </span>
          )}
        </div>

        {status.kind === "connected" ? (
          <>
            <Row label="기본 모델" testId="scoring-card-model">
              {classroom.default_model}
            </Row>
            <Row label="채점" testId="scoring-card-count">
              {classroom.scored_attempt_count.toLocaleString("ko-KR")}회
            </Row>
            <UsageRow classroom={classroom} />
          </>
        ) : null}

        {/* 갈 곳은 키를 바꿀 수 있는 소유자에게만 — 공동 강사에게는 갈 곳 없는 버튼을 보이지 않는다(#561). */}
        {scoringStatusTone(status) === "attention" && isOwner ? (
          <div>
            <Link
              href={`${settings}#scoring-key`}
              data-testid={
                status.kind === "missing"
                  ? "classroom-missing-api-key-settings-link"
                  : status.kind === "rejected"
                    ? "classroom-rejected-api-key-settings-link"
                    : status.kind === "exhausted"
                      ? "classroom-exhausted-credit-settings-link"
                      : "classroom-unreachable-server-settings-link"
              }
              className={buttonClass(status.kind === "missing" ? "primary" : "secondary", "sm")}
            >
              {status.kind === "missing" ? "채점 연결 넣기" : "설정 열기"}
            </Link>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
