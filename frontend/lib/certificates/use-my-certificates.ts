"use client";

// 받는 사람의 상장(#1130) — 내 참가 현황이 제출 행마다 붙인다.

import { type ApiResult, useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { MyCertificate } from "./recipient";

export function useMyCertificates() {
  return useBackendQuery<MyCertificate[]>(bffClient, "/api/backend/certificates/mine");
}

/** PDF 는 BFF 프록시가 `application/pdf` 그대로 넘긴다. */
export function certificatePdfPath(certificateId: number): string {
  return `/api/backend/certificates/${certificateId}/pdf`;
}

export async function setCertificateHidden(
  certificateId: number,
  hidden: boolean,
): Promise<{ ok: true } | { ok: false; message: string }> {
  const result: ApiResult<MyCertificate> = await bffClient.post(
    `/api/backend/certificates/${certificateId}/visibility`,
    { hidden },
  );
  return result.ok ? { ok: true } : { ok: false, message: result.detail };
}
