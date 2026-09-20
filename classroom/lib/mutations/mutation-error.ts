// `useMutationRequest`(#442)가 오류 문구를 고르는 순수 판단 — 훅 파일에서
// 떼어 둔다. 훅 파일은 react를 import 해서 이 저장소의 순수 함수 시임
// (ADR-0026, `vitest.shared.mts`의 `pureModuleGuard`)이 그것을 바로
// 테스트하지 못하게 막는다.
//
// 공유 클라이언트(#462) 위에서는 실패가 예외가 아니라 `ApiFailure` 값이다 —
// 네트워크 실패만 호출부가 정한 기본 문구를 쓰고, 그 밖(서버가 실제로 응답한
// 모든 실패)은 `ApiFailure.detail`을 그대로 쓴다 — 배열 detail 도 이미
// `normalizeDetail`(패키지)이 사람이 읽는 문자열로 좁혀 놓았다.
import type { ApiFailure } from "@codemit/bff-client";

export function resolveMutationErrorMessage(failure: ApiFailure, fallbackMessage: string): string {
  return failure.code === "network" ? fallbackMessage : failure.detail;
}
