"use client";

// 운영자가 막힌 지급을 진행시킨다 (#182). `POST /api/operator/payouts/{key}/retry`가
// 이미 있는 도메인 경로(수취인 재등록·실이체 재시도)를 그대로 태우는 표면이다 —
// 이 파일에는 재시도 로직이 없다. 서버 응답을 그대로 옮길 뿐이다.
import { bffClient } from "@/lib/bff/client";

/** 서버 문구를 그대로 쓴다 — 화면이 짐작해 다시 쓰면 언젠가 갈라진다. */
export async function retryPayoutForOperator(
  idempotencyKey: string,
): Promise<{ ok: true } | { ok: false; message: string }> {
  const result = await bffClient.post(`/api/backend/operator/payouts/${idempotencyKey}/retry`);
  if (result.ok) return { ok: true };
  if (result.code === "network") {
    return { ok: false, message: "요청을 보내지 못했습니다. 다시 시도해주세요." };
  }
  return { ok: false, message: result.detail };
}
