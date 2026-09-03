"use client";

// 개최 3단계 표시 — 브리프 · 요구사항 · 결제 (#111, 부모 #110).
//
// 결제가 문을 닫기 전까지 Sponsor 는 이 세 단계를 오갈 수 있다(spec #110
// Implementation Decisions "단계를 화면에 드러낸다"). 이 컴포넌트는 그 자체로
// 내비게이션을 만들지 않는다 — 지금 어느 단계인지만 읽히면 된다. 실제 이동은
// 각 화면이 이미 가진 링크("결제하러 가기", 결제 화면의 "요구사항으로
// 돌아가기")가 담당한다. 결제가 끝난 뒤에는 이 컴포넌트를 아예 그리지 않는
// 화면이 있다(예: draft 화면의 already-published 상태) — 그것이 "이동이
// 닫힌다"의 실제 구현이다.
export type ContestStage = "brief" | "requirements" | "payment";

const STAGES: { key: ContestStage; label: string }[] = [
  { key: "brief", label: "브리프" },
  { key: "requirements", label: "요구사항" },
  { key: "payment", label: "결제" },
];

export function ContestStageStepper({ current }: { current: ContestStage }) {
  return (
    <ol
      className="flex items-center gap-2 text-xs text-ink/50"
      data-testid="contest-stage-stepper"
      aria-label="개최 단계"
    >
      {STAGES.map((stage, index) => {
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
            {index < STAGES.length - 1 && <span aria-hidden="true">→</span>}
          </li>
        );
      })}
    </ol>
  );
}
