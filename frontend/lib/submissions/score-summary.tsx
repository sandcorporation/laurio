import Link from "next/link";

// Score 요약(달성률·판정 모델·Requirement별 근거) — 세 화면이 같은 세 필드를
// 나란히 그린다(#210, #248): 과제 학생의 자기 점수 화면(app/assignments/[code]/
// page.tsx), 과제 강사의 제출 목록(app/console/assignments/[assignmentId]/
// page.tsx), 그리고 공모전 제출 화면(app/console/contests/[contestId]/submit/
// page.tsx). 백엔드도 같은 자리다 — `submissions.schemas.OwnScoreOut`(공모전·
// 과제 학생용)과 `contests.schemas.AssignmentSubmissionScoreOut`(과제 강사용)이
// 이의 관련 필드만 다르고 나머지는 같다. 화면이 갈려 있으면 채점 스키마가 바뀔 때
// 한쪽만 고쳐 문구가 갈릴 수 있다 — 그래서 여기 하나로 모은다.
//
// **원래 `lib/assignments/`에 있었다(#248 프리팩터).** 과제 전용 자리에 있던
// 컴포넌트를 공모전 제출 화면이 가져다 쓰려면 옮겨야 했다 — 과제 쪽이 먼저
// 생겼을 뿐 이 컴포넌트 자체는 과제 개념에 의존하지 않는다.
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
  reasoningLink,
}: {
  score: ScoreSummaryData;
  /** data-testid 접두어 — 학생 화면은 "assignment-score", 강사 목록의 한 행은
   * "assignment-submission-score"를 쓴다(기존 e2e·수기 검증이 이미 그 값을
   * 단언하고 있어 바꾸지 않는다). */
  testIdPrefix: string;
  /** Requirement별 근거를 이 자리에 나열하는 대신 다른 화면으로 링크한다
   * (#248). 공모전 제출 화면이 쓴다 — 이의 화면(`/console/participation/
   * {id}/appeal`)이 같은 근거를 이미 Requirement별로 전부 보여주므로, 여기서
   * 되풀이하면 채점 스키마가 바뀔 때 두 곳이 어긋날 수 있다("판정 근거
   * 전문·이의 폼·인수는 각자의 화면으로 링크만 탄다"). 과제 화면은 이 값을
   * 주지 않는다 — 과제에는 이의 화면 자체가 없어(ADR-0028) 여기가 유일한
   * 자리다. */
  reasoningLink?: { href: string; label: string };
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
