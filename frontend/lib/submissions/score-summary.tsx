import Link from "next/link";

// Score 요약(달성률·판정 모델·Requirement별 근거) — 공모전 제출 화면
// (app/console/contests/[contestId]/submit/page.tsx)이 쓴다(#210, #248, #251).
// 백엔드는 `submissions.schemas.OwnScoreOut`이 같은 필드를 준다.
//
// 둘도 같이 썼다 — #359, spec #358).** 과제 전용 자리에 있던 컴포넌트를
// 공모전 제출 화면이 가져다 쓰려면 옮겨야 했다 — 과제 쪽이 먼저 생겼을
// 뿐 이 컴포넌트 자체는 과제 개념에 의존하지 않는다.

// `submissions.scoring_basis.ScoringBasis`(#246)와 같은 세 값. 그 문자열
// 리터럴 유니온을 그대로 옮겨 적는다 — 이 파일이 이미 `percentage`·
// `model_version`도 생성 타입을 참조하지 않고 손으로 옮겨 적은 구조적
// 인터페이스라(호출부 셋의 서로 다른 스키마를 하나로 받기 위해), 여기만
// 생성 타입을 import하면 그 하나만 명목 타이핑이 섞인다.
export type ScoringBasis = "ai_judged" | "no_scoring_input" | "platform_failure";

export interface ScoreSummaryData {
  percentage: string;
  model_version: string;
  // 채점의 성격(#251) — 이 값으로만 갈린다. `model_version` 문자열을 다시
  // 해석해 "AI가 판정했는가"를 추측하지 않는다(#246이 백엔드에서 없앤
  // 커플링을 프론트에서 재도입하지 않는다).
  scoring_basis: ScoringBasis;
  reasoning: unknown[];
}

function reasoningTextOf(item: unknown): string {
  if (item && typeof item === "object" && "reasoning" in item) {
    return String((item as { reasoning?: unknown }).reasoning ?? "");
  }
  return "";
}

// 「판정 모델」 줄의 문구(#251) — 자동 0% 둘(ADR-0030 참가자 귀책·ADR-0031
// 플랫폼 귀책)은 AI가 이 제출을 보지 않았으므로 모델을 자처하는 문구를 내지
// 않는다. 내부 표식 문자열(`Score.model_version`의 sentinel,
// `platform-auto (...)`)도 노출하지 않는다 — 그 문자열은 append-only인
// `Score` 행과 운영자 심판 화면(`appeals.schemas.ScoreSnapshotOut`)을 위한
// 것이지 참가자가 읽을 라벨이 아니다. 두 사유는 문구 자체로 구별된다 — 뒤엣
// 것만 이의를 낼 사유이므로(플랫폼 탓) 섞이면 안 된다.
//
// **export하는 이유 — 이의 화면도 같은 줄을 쓴다.** `app/console/participation/
// [submissionId]/appeal/page.tsx`의 `ScoreSection`은 `ScoreSummary`를 쓰지
// 않고 자기 레이아웃(달성률·판정 모델·이의 기한·Requirement별 근거 전문)을
// 직접 그린다 — 근거를 전문으로 펼치는 화면이 여기뿐이라 `reasoningLink`
// 분기로 흡수되지 않는다. 그래도 「판정 모델」 문구가 갈리면 참가자가 두
// 화면에서 다른 사유를 읽는다 — 그래서 문구 함수만 공유한다.
export function modelLineOf(score: ScoreSummaryData): string {
  switch (score.scoring_basis) {
    case "ai_judged":
      return `판정 모델 ${score.model_version}`;
    case "no_scoring_input":
      return "AI가 판정하지 않았습니다 — 채점할 자료가 없었습니다";
    case "platform_failure":
      return "AI가 판정하지 않았습니다 — 채점이 반복 실패했습니다";
  }
}

export function ScoreSummary({
  score,
  testIdPrefix,
  reasoningLink,
}: {
  score: ScoreSummaryData;
  /** data-testid 접두어 — 호출부가 자기 화면에 맞는 값을 넘긴다(공모전 제출
   * 화면은 "submit-score"). */
  testIdPrefix: string;
  /** Requirement별 근거를 이 자리에 나열하는 대신 다른 화면으로 링크한다
   * (#248). 공모전 제출 화면이 쓴다 — 이의 화면(`/console/participation/
   * {id}/appeal`)이 같은 근거를 이미 Requirement별로 전부 보여주므로, 여기서
   * 되풀이하면 채점 스키마가 바뀔 때 두 곳이 어긋날 수 있다("판정 근거
   * 전문·이의 폼·인수는 각자의 화면으로 링크만 탄다"). */
  reasoningLink?: { href: string; label: string };
}) {
  return (
    <>
      <p className="text-lg">
        필수 요건 달성률{" "}
        <strong data-testid={`${testIdPrefix}-percentage`}>{score.percentage}%</strong>
      </p>
      <p className="text-sm text-ink/70" data-testid={`${testIdPrefix}-model`}>
        {modelLineOf(score)}
      </p>
      {reasoningLink ? (
        <Link
          className="text-sm underline"
          href={reasoningLink.href}
          data-testid={`${testIdPrefix}-reasoning-link`}
        >
          {reasoningLink.label}
        </Link>
      ) : (
        <ul className="flex flex-col gap-2" data-testid={`${testIdPrefix}-reasoning`}>
          {score.reasoning.map((item, index) => (
            <li key={index} className="rounded border border-rule p-3 text-sm">
              {reasoningTextOf(item)}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
