// `useMutationRequest`(#442)가 오류 문구를 고르는 순수 판단 — 훅 파일에서
// 떼어 둔다. 훅 파일은 react를 import 해서 이 저장소의 순수 함수 시임
// (ADR-0026, `vitest.shared.mts`의 `pureModuleGuard`)이 그것을 바로
// 테스트하지 못하게 막는다.
import { BackendError } from "../backend/client";

/** `BackendError`면 서버가 준 문구를 그대로 쓰고, 그 밖의 오류(네트워크
 *  끊김 등)면 호출부가 정한 기본 문구를 쓴다. */
export function resolveMutationErrorMessage(err: unknown, fallbackMessage: string): string {
  return err instanceof BackendError ? err.message : fallbackMessage;
}
