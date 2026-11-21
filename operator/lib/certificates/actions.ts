// 공모전 상장 목록 조회·취소(#1131). 실패 문구는 서버 것을 그대로 쓴다.
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { Certificate, CertificateList } from "./types";

export function fetchContestCertificates(contestId: string): Promise<ApiResult<CertificateList>> {
  return bffClient.get<CertificateList>(`/api/backend/operator/contests/${contestId}/certificates`);
}

export async function cancelCertificate(
  contestId: string,
  certificateId: number,
): Promise<{ ok: true; certificate: Certificate } | { ok: false; message: string }> {
  const result = await bffClient.post<Certificate>(
    `/api/backend/operator/contests/${contestId}/certificates/${certificateId}/cancel`,
  );
  if (result.ok) return { ok: true, certificate: result.data };
  if (result.code === "network") {
    return { ok: false, message: "요청을 보내지 못했습니다. 다시 시도해주세요." };
  }
  return { ok: false, message: result.detail };
}
