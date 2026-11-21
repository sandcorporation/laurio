// 점수 정정 조회·걸기(#1183). 실패 문구는 서버 것을 그대로 쓴다.
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ScoreCorrectionList, ScoreCorrectionRequestResult } from "./types";

export function fetchScoreCorrections(contestId: string): Promise<ApiResult<ScoreCorrectionList>> {
  return bffClient.get<ScoreCorrectionList>(`/api/backend/operator/contests/${contestId}/score-corrections`);
}

export async function requestScoreCorrections(
  contestId: string,
  submissionIds: number[],
  reason: string,
): Promise<{ ok: true; result: ScoreCorrectionRequestResult } | { ok: false; message: string }> {
  const result = await bffClient.post<ScoreCorrectionRequestResult>(
    `/api/backend/operator/contests/${contestId}/score-corrections`,
    { reason, submission_ids: submissionIds },
  );
  if (result.ok) return { ok: true, result: result.data };
  if (result.code === "network") {
    return { ok: false, message: "요청을 보내지 못했습니다. 다시 시도해주세요." };
  }
  return { ok: false, message: result.detail };
}
