"use client";

// 이의 상세(#66, #423 — 골간으로 옮긴다) — 심판에 필요한 것을 한 화면에 모은다:
// 이의 사유, Score 스냅샷(재채점이 아니라 그때 실제로 일어난 판정, ADR-0006),
// 그리고 기본으로 접힌 소스(ADR-0022, lib/appeals/source-reveal.tsx). 심판이
// 아직 없는(pending) 이의는 인용/기각 폼을 보여주고(#67), 이미 심판된 이의는
// 그 폼 대신 확정된 결과를 읽기 전용으로 보여준다 — 서버의 409(조건부 UPDATE)와
// 이 화면이 폼을 아예 주지 않는 것, 둘 다 이중 심판을 막는 방어다.
//
// **왼쪽 근거 · 오른쪽 행동**(spec #421 「골간」). 왼쪽에 이의 사유·채점 결과
// (체크리스트별 판정)·소스를 열어 볼 수단을, 오른쪽에 심판 패널과 감사 추적을
// 둔다 — 시안 `docs/design/operator/Appeal.dc.html`의 골간을 쓰되 픽셀을 베끼지
// 않는다: 체크리스트 텍스트는 `Score.reasoning`이 `requirement_id`만 담고
// 설명을 담지 않아(운영자/lib/appeals/types.ts의 `parseReasoningItem` 주석)
// 그 식별자로만 행을 가리킨다.
import { useParams } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { useAppealDetail } from "@/lib/appeals/use-appeal-detail";
import type { AppealRuling } from "@/lib/appeals/types";
import { appealStatusLabel, parseReasoningItem } from "@/lib/appeals/types";
import { SourceReveal } from "@/lib/appeals/source-reveal";
import { RulingForm } from "@/lib/appeals/ruling-form";

interface AuditEntry {
  at: string;
  what: string;
}

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

  // 이 세션에서 실제로 일어난 소스 열람을 감사 추적에 쌓는다(#423 AC — "그
  // 자리에서 알려준다"). 서버는 열람 기록을 누가 봤는지 참가자에게 주지
  // 않을 뿐 운영자 표면에도 지금 세션 이전 열람을 되짚는 조회가 없으므로
  // (`appeals.api`에 그런 엔드포인트가 없다 — 이 티켓은 백엔드를 건드리지
  // 않는다), 지어내지 않고 실제로 관측한 사건만 더한다.
  const [sourceReadEvents, setSourceReadEvents] = useState<AuditEntry[]>([]);

  if (session.status === "loading") {
    return (
      <div className="p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  if (session.status === "unauthenticated") return null;

  if (state.status === "loading") {
    return (
      <div className="p-8">
        <p data-testid="appeal-detail-loading">불러오는 중...</p>
      </div>
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
      <div className="p-8">
        <p data-testid="appeal-detail-not-found">이의를 찾을 수 없습니다.</p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="p-8">
        <p role="alert" data-testid="appeal-detail-error">
          이의를 불러오지 못했습니다.
        </p>
      </div>
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

  // 언제순으로 보여준다 — 소스 열람이 심판보다 먼저 일어난 것이 보통이므로
  // (근거를 보고서야 심판하니까), 배열에 쌓인 순서(접수 → 심판 → 이 세션의
  // 열람들)를 그대로 쓰면 실제로는 먼저 일어난 열람이 심판 뒤에 나와 사건
  // 순서를 거짓으로 말하게 된다.
  const auditEntries: AuditEntry[] = [
    { at: appeal.created_at, what: "제출자가 이의 접수" },
    ...(ruling
      ? [
          {
            at: ruling.ruled_at,
            what: `${ruling.ruled_by_username}이(가) ${appealStatusLabel(ruling.decision)} 확정`,
          },
        ]
      : []),
    ...sourceReadEvents,
  ].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());

  return (
    <>
      <PageHeader
        crumb="할 일 · 이의 심판"
        title={`이의 #${appeal.id}`}
        titleTestId="appeal-detail-heading"
        description={
          ruling
            ? "이미 심판이 끝났습니다 — 결과는 원장에 남았습니다."
            : "확정하면 되돌릴 수 없다 — 원장에 남는다."
        }
      />
      <div className="flex flex-1 items-start gap-[18px] p-8">
        <div className="flex min-w-0 flex-1 flex-col gap-[18px]">
          <section
            data-testid="appeal-detail-reason-section"
            className="border border-rule bg-surface"
          >
            <div className="border-b border-rule px-4 py-3 text-[14px] font-semibold">
              이의 사유
            </div>
            <div className="flex flex-col gap-3 p-4">
              <div className="flex flex-wrap items-center gap-2.5 text-[12.5px] text-ink/62">
                <Badge tone="neutral" testId="appeal-detail-status">
                  {appealStatusLabel(status)}
                </Badge>
                <span data-testid="appeal-detail-submission">
                  Submission #{appeal.submission_id}
                </span>
                <span data-testid="appeal-detail-created-at">
                  {new Date(appeal.created_at).toLocaleString("ko-KR")}
                </span>
              </div>
              <p data-testid="appeal-detail-reason" className="text-[13.5px] leading-relaxed">
                {appeal.reason}
              </p>
              <p className="text-[12px] text-ink/45">
                제출자가 쓴 사유 그대로다 — 운영자가 고쳐 쓰지 않는다.
              </p>
            </div>
          </section>

          <section data-testid="appeal-detail-score" className="border border-rule bg-surface">
            <div className="border-b border-rule px-4 py-3 text-[14px] font-semibold">
              채점 결과
              <span className="ml-2.5 text-[12.5px] font-normal text-ink/45">
                점수 <span data-testid="appeal-detail-score-percentage">{appeal.score.percentage}%</span>{" "}
                · 모델 <span data-testid="appeal-detail-score-model-version">{appeal.score.model_version}</span>{" "}
                · 채점{" "}
                <span data-testid="appeal-detail-score-created-at">
                  {new Date(appeal.score.created_at).toLocaleString("ko-KR")}
                </span>
              </span>
            </div>
            {/* 체크리스트별 판정만 통과 초록·주의 빨강을 쓴다(#423 AC) — 대기·
                정보 배지는 이 화면 어디에도 이 색을 쓰지 않는다. `reasoning`이
                Requirement 텍스트를 담지 않아(위 파일 주석) 식별자로만 행을
                가리킨다. */}
            <div data-testid="appeal-detail-score-reasoning" className="flex flex-col">
              <div className="flex gap-3.5 border-b border-rule px-4 py-2 text-[11px] tracking-[0.06em] text-ink/30">
                <div className="w-[110px] shrink-0">체크리스트</div>
                <div className="w-[70px] shrink-0">AI 판정</div>
                <div className="min-w-0 flex-1">AI가 적은 사유</div>
              </div>
              {appeal.score.reasoning.map((raw, index) => {
                const item = parseReasoningItem(raw);
                return (
                  <div
                    key={index}
                    data-testid={`appeal-score-reasoning-item-${index}`}
                    className={`flex items-center gap-3.5 border-b border-rule px-4 py-2 text-[12.5px] ${
                      index % 2 === 1 ? "bg-ink/[2%]" : ""
                    }`}
                  >
                    <div className="w-[110px] shrink-0 truncate">
                      요건 {item.requirementId !== null ? `#${item.requirementId}` : "?"}
                    </div>
                    <div className="w-[70px] shrink-0">
                      {item.isMet === null ? (
                        <Badge tone="neutral">정보 없음</Badge>
                      ) : (
                        <Badge tone={item.isMet ? "pass" : "attention"}>
                          {item.isMet ? "충족" : "미충족"}
                        </Badge>
                      )}
                    </div>
                    <div className="min-w-0 flex-1 truncate text-ink/62">{item.reasoning}</div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="border border-rule bg-surface">
            <div className="border-b border-rule px-4 py-3 text-[14px] font-semibold">
              무엇을 보고 판단하나
            </div>
            {appeal.score.scored_assets.length > 0 && (
              <div className="flex flex-wrap gap-2 px-4 pt-3">
                {appeal.score.scored_assets.map((asset) => (
                  <Badge key={asset.asset_id} tone="neutral">
                    {asset.label}
                  </Badge>
                ))}
              </div>
            )}
            <SourceReveal
              appealId={appeal.id}
              onRevealed={() =>
                setSourceReadEvents((current) => [
                  ...current,
                  {
                    at: new Date().toISOString(),
                    what: `${session.user.username}이(가) 소스를 열어봄`,
                  },
                ])
              }
            />
          </section>
        </div>

        <div className="flex w-[420px] shrink-0 flex-col gap-[18px]">
          <section className="border border-rule bg-surface">
            <div className="border-b border-rule px-4 py-3 text-[14px] font-semibold">심판</div>

            {!ruling && (
              <RulingForm
                appealId={appeal.id}
                onRuled={(newRuling) => setRuledOverride({ appealId, ruling: newRuling })}
              />
            )}

            {ruling && (
              <div
                data-testid="appeal-detail-ruling"
                className="flex flex-col gap-2 p-4 text-[13px]"
              >
                <Badge tone="neutral" testId="appeal-detail-ruling-decision">
                  {appealStatusLabel(ruling.decision)}
                </Badge>
                <p data-testid="appeal-detail-ruling-ruled-by" className="text-ink/62">
                  {ruling.ruled_by_username}
                </p>
                <p data-testid="appeal-detail-ruling-note">{ruling.note}</p>
                <p data-testid="appeal-detail-ruling-ruled-at" className="text-[12px] text-ink/45">
                  {new Date(ruling.ruled_at).toLocaleString("ko-KR")}
                </p>
                {ruling.correction_amount !== null && (
                  <p data-testid="appeal-detail-ruling-correction-amount" className="font-mono">
                    {ruling.correction_amount}
                  </p>
                )}
              </div>
            )}
          </section>

          <section className="border border-rule bg-surface">
            <div className="border-b border-rule px-4 py-3 text-[14px] font-semibold">
              감사 추적
              <span className="ml-2.5 text-[12.5px] font-normal text-ink/45">append-only</span>
            </div>
            <div data-testid="appeal-detail-audit-trail" className="flex flex-col">
              <div className="flex gap-3.5 border-b border-rule px-4 py-2 text-[11px] tracking-[0.06em] text-ink/30">
                <div className="w-[130px] shrink-0">언제</div>
                <div className="min-w-0 flex-1">무엇</div>
              </div>
              {auditEntries.map((entry, index) => (
                <div
                  key={index}
                  data-testid={`appeal-audit-entry-${index}`}
                  className={`flex items-center gap-3.5 border-b border-rule px-4 py-2 text-[12.5px] ${
                    index % 2 === 1 ? "bg-ink/[2%]" : ""
                  }`}
                >
                  <div className="w-[130px] shrink-0 truncate font-mono">
                    {new Date(entry.at).toLocaleString("ko-KR")}
                  </div>
                  <div className="min-w-0 flex-1 truncate text-ink/62">{entry.what}</div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
