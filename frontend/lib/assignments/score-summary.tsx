// Score 요약(달성률·판정 모델·Requirement별 근거) — 학생의 자기 점수 화면
// (app/assignments/[code]/page.tsx)과 강사의 제출 목록(app/console/assignments/
// [assignmentId]/page.tsx)이 같은 세 필드를 나란히 그린다(#210). 백엔드도 같은
// 자리다 — `submissions.schemas.OwnScoreOut`(학생용)과 `contests.schemas.
// AssignmentSubmissionScoreOut`(강사용)이 이의 관련 필드만 다르고 나머지는
// 같다. 화면이 둘로 갈려 있으면 채점 스키마가 바뀔 때 한쪽만 고쳐 문구가
// 갈릴 수 있다 — 그래서 여기 하나로 모은다.
export interface ScoreSummaryData {
  percentage: string;
  model_version: string;
  reasoning: unknown[];
}

function reasoningTextOf(item: unknown): string {
  if (item && typeof item === "object" && "reasoning" in item) {
    return String((item as { reasoning?: unknown }).reasoning ?? "");
  }
  return "";
}

export function ScoreSummary({
  score,
  testIdPrefix,
}: {
  score: ScoreSummaryData;
  /** data-testid 접두어 — 학생 화면은 "assignment-score", 강사 목록의 한 행은
   * "assignment-submission-score"를 쓴다(기존 e2e·수기 검증이 이미 그 값을
   * 단언하고 있어 바꾸지 않는다). */
  testIdPrefix: string;
}) {
  return (
    <>
      <p className="text-lg">
        필수 요건 달성률{" "}
        <strong data-testid={`${testIdPrefix}-percentage`}>{score.percentage}%</strong>
      </p>
      <p className="text-sm text-ink/70" data-testid={`${testIdPrefix}-model`}>
        판정 모델 {score.model_version}
      </p>
      <ul className="flex flex-col gap-2" data-testid={`${testIdPrefix}-reasoning`}>
        {score.reasoning.map((item, index) => (
          <li key={index} className="rounded border border-rule p-3 text-sm">
            {reasoningTextOf(item)}
          </li>
        ))}
      </ul>
    </>
  );
}
