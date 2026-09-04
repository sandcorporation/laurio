// FE-06(#31) — 개발자 공개 프로필. `GET /api/developers/{developer_id}/profile` 도
// auth=None 공개 표면이다(ADR-0015) — contests.ts 와 같은 패턴을 그대로 따른다.
//
// 반환 타입 `DeveloperPublicProfileOut`/`PublicSubmissionOut` 은 @laurio/bff-client/schema 에서
// 온다. 이 스키마 자체에 source_object_key·test_account 필드가 없다
// (backend/submissions/schemas.py) — 백엔드가 애초에 그 값을 내려주지 않으므로,
// 이 타입을 쓰는 한 프론트가 실수로 그 필드를 렌더링할 수조차 없다. 그래도
// app/developers/[id]/page.tsx 는 이 객체를 통째로 클라이언트 컴포넌트에 넘기지
// 않는다 — 이 페이지 자체가 서버 컴포넌트뿐이라 하이드레이션 페이로드가 생기지
// 않는다(ADR-0015, "use client" 없음).
import { backendClient } from "./client";
import type { components } from "@laurio/bff-client/schema";

export type DeveloperPublicProfile = components["schemas"]["DeveloperPublicProfileOut"];
export type PublicSubmission = components["schemas"]["PublicSubmissionOut"];

// 존재하지 않는 developer_id 는 백엔드가 이미 404 로 답한다
// (submissions.api.get_developer_public_profile) — 여기서 null 로 옮겨 호출부가
// `notFound()` 를 부르게 한다. contests.ts#fetchContest 와 같은 패턴이다.
export async function fetchDeveloperProfile(id: number): Promise<DeveloperPublicProfile | null> {
  const res = await backendClient.GET("/api/developers/{developer_id}/profile", {
    params: { path: { developer_id: id } },
  });

  if (res.response.status === 404) {
    return null;
  }
  if (!res.response.ok) {
    throw new Error(
      `GET /api/developers/${id}/profile 실패: ${res.response.status} ${res.response.statusText}`,
    );
  }
  if (res.data === undefined) {
    throw new Error(`GET /api/developers/${id}/profile: 2xx 인데 응답 본문이 비어 있다`);
  }
  return res.data;
}
