"use client";

// 개최 3단계 표시 — 브리프 · 요구사항 · 결제(유료) 또는 공개(무료, #415)
// (#111, 부모 #110, ADR-0048).
//
// 결제(또는 공개)가 문을 닫기 전까지 Sponsor 는 이 세 단계를 오갈 수 있다(spec
// #110 Implementation Decisions "단계를 화면에 드러낸다"). 이 컴포넌트는 그
// 자체로 내비게이션을 만들지 않는다 — 지금 어느 단계인지만 읽히면 된다. 실제
// 이동은 각 화면이 이미 가진 링크("결제하러 가기"/"공개하기", 결제 화면의
// "요구사항으로 돌아가기")가 담당한다. 공개가 끝난 뒤에는 이 컴포넌트를 아예
// 그리지 않는 화면이 있다(예: draft 화면의 already-published 상태) — 그것이
// "이동이 닫힌다"의 실제 구현이다.
//
// 마지막 단계 라벨만 `variant`로 갈린다 — 유료는 "결제", 무료는 "공개"(#415).
// 나머지 두 단계(브리프·요구사항)는 두 흐름이 완전히 같은 화면을 그대로
// 공유한다.
export type ContestStage = "brief" | "requirements" | "payment";
export type ContestStageVariant = "paid" | "free";

const STAGE_LABELS: Record<ContestStage, Record<ContestStageVariant, string>> = {
  brief: { paid: "브리프", free: "브리프" },
  requirements: { paid: "요구사항", free: "요구사항" },
  payment: { paid: "결제", free: "공개" },
};

const STAGE_KEYS: ContestStage[] = ["brief", "requirements", "payment"];

export function ContestStageStepper({
  current,
  variant = "paid",
}: {
  current: ContestStage;
  variant?: ContestStageVariant;
}) {
  const stages = STAGE_KEYS.map((key) => ({ key, label: STAGE_LABELS[key][variant] }));

  return (
    <ol
      className="flex items-center gap-2 text-xs text-ink/50"
      data-testid="contest-stage-stepper"
      aria-label="개최 단계"
    >
      {stages.map((stage, index) => {
        const isCurrent = stage.key === current;
        return (
          <li key={stage.key} className="flex items-center gap-2">
            <span
              data-testid={`contest-stage-${stage.key}`}
              data-current={isCurrent ? "true" : "false"}
              aria-current={isCurrent ? "step" : undefined}
              className={isCurrent ? "font-semibold text-ink" : "text-ink/40"}
            >
              {index + 1}. {stage.label}
            </span>
            {index < stages.length - 1 && <span aria-hidden="true">→</span>}
          </li>
        );
      })}
    </ol>
  );
}
