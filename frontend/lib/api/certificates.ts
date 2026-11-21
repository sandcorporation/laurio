// 공개 상장 확인(#1128) — `GET /api/certificates/verify/{token}`(auth=None).
// 없는 토큰은 백엔드가 404 로 답한다. 그 상태 코드만 null 로 옮겨 호출부가 `notFound()` 를
// 부르게 하고, 그 외 실패는 예외로 던진다.
import { backendClient } from "./client";
import type { CertificateVerification } from "@/lib/certificates/verify";

export async function fetchCertificateVerification(token: string): Promise<CertificateVerification | null> {
  const res = await backendClient.GET("/api/certificates/verify/{token}", {
    params: { path: { token } },
    cache: "no-store",
  });

  if (res.response.status === 404) {
    return null;
  }
  if (!res.response.ok || !res.data) {
    throw new Error(`상장 확인 조회가 ${res.response.status} 로 실패했다`);
  }
  return res.data;
}
