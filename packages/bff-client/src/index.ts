// @codemit/bff-client — 브라우저 쪽 BFF 클라이언트 (#146, #122).
//
// 서버 쪽 라우트 핸들러 기계는 `@codemit/bff-shared` 다 — 섞지 않는다(저쪽은 Next 라우트 안에서
// 경로 순회·Origin·허용목록을 검사하고, 이쪽은 브라우저에서 인증 구역 호출의 모양을 정한다).

export { createBffClient, toBffPath } from "./client";
export type { BffClient, BffClientOptions, BffRequestInit } from "./client";
export { useBackendQuery, usePagedList } from "./hooks";
export type { BackendQueryOptions, PagedListState, QueryState } from "./hooks";
export { FALLBACK_DETAIL, codeForStatus, normalizeDetail } from "./result";
export type { ApiFailure, ApiResult, ApiSuccess } from "./result";
export type { components, paths } from "./schema.gen";
