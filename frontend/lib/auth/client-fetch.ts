"use client";

// 세션이 필요한 BFF 호출의 클라이언트 쪽 래퍼 (FE-07 #32) — 되살리기·단일 비행·재시도·401 처리는
// `@laurio/bff-client` 로 옮겨 갔다(#146). 아직 이 함수를 부르는 console 페이지들이 #147 에서
// 패키지 훅/클라이언트로 옮겨 가면 이 파일은 지운다.

import { bffClient } from "@/lib/bff/client";

export function sessionFetch(path: string, init?: RequestInit): Promise<Response> {
  return bffClient.fetch(path, init);
}
