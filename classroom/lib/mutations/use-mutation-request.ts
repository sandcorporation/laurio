"use client";

// 「오류 지우기 → 호출 → 다시 불러오기 → 오류 문구」 반복을 묶는 공용 변경
// 도우미 (#442, 부모 #432). 문제 수정 화면의 핸들러(체크리스트 조작, 문제
// 열기·숨기기·다시 열기, 모델 재시도, 복사·템플릿 공개·내리기, 삭제)가
// 전부 이 훅을 거친다.
//
// 오류마다 화면 자리가 다르므로(체크리스트 오류, 열기 오류, 숨기기 오류...)
// 상태는 자리마다 따로 든다 — 호출부가 자리 수만큼 이 훅을 부른다. 오류
// 문구를 고르는 판단만 `./mutation-error`의 순수 함수로 뽑아 두었다 — 이
// 파일은 react를 import해 이 저장소의 순수 함수 시임(ADR-0026)이 직접
// 테스트하지 못한다(`use-scoring-models.ts`·`use-problem.ts`도 훅 자체는
// 테스트가 없다).
//
// 공유 클라이언트(#462) 위에서는 `action`이 던지지 않는다 — `ApiResult`를
// 돌려주고, 이 훅이 `.ok`를 갈라 성공이면 `data`를 `onSuccess`에 그대로
// 넘긴다. 호출부(`app/classes/[id]/problems/[problemId]/page.tsx` 등)는 바뀌지
// 않는다 — `action`이 반환하는 타입만 `Promise<T>`에서 `Promise<ApiResult<T>>`로
// 바뀌었을 뿐이다.
import { useCallback, useState } from "react";

import type { ApiResult } from "@codemit/bff-client";

import { resolveMutationErrorMessage } from "./mutation-error";

export type MutationRequestOptions<T> = {
  /** 네트워크 실패처럼 서버가 답하지 못한 경우에만 쓰는 문구. */
  fallbackMessage: string;
  /** 성공하면 서버 값을 다시 받아온다 — 없으면 안 받아온다(예: 삭제·복사처럼
   *  이 화면을 떠나는 경우). */
  reload?: () => void;
  /** 성공한 결과로 화면이 더 해야 할 일(내비게이션, 로컬 상태 갱신 등). */
  onSuccess?: (result: T) => void;
};

export function useMutationRequest() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async <T,>(action: () => Promise<ApiResult<T>>, options: MutationRequestOptions<T>) => {
      setPending(true);
      setError(null);
      const result = await action();
      if (result.ok) {
        options.reload?.();
        options.onSuccess?.(result.data);
      } else {
        setError(resolveMutationErrorMessage(result, options.fallbackMessage));
      }
      setPending(false);
    },
    [],
  );

  return { pending, error, run, setError };
}
