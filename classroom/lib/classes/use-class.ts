"use client";

// 클래스 상세 상태 (#278/#279). 남의 클래스는 백엔드가 404를 준다 — 그 사실을
// "notFound"로 구별해 화면이 "클래스를 찾을 수 없습니다"를 보여준다. 공유
// 클라이언트 위에 선다(#462) — 취소 플래그·401 처리는 `useBackendQuery`가
// 소유하고, 이 훅은 경로와 404 해석만 남는다.
import { useCallback, useMemo, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import { archiveClass, regenerateJoinLink, unarchiveClass, type ClassRow } from "./api";

export type ClassDetailState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; classroom: ClassRow; regenerateError: boolean; archiveError: boolean };

const NOT_FOUND = Symbol("class-not-found");

export function useClass(classId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<ClassRow | typeof NOT_FOUND>(
    bffClient,
    `/api/backend/classroom/classes/${classId}`,
    { onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined) },
  );
  // `refetchKeepsScreen` 규율(lib/rendering/refetch-keeps-screen.test.ts)이
  // 이 이름의 로컬 선언을 찾는다 — `useBackendQuery`가 이미 그 규율을
  // 지키므로 여기서는 그대로 다시 감싸 내보낸다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);
  const [regenerateError, setRegenerateError] = useState(false);
  const [archiveError, setArchiveError] = useState(false);

  // 새 객체를 매 렌더 만들면(useMemo 없이) 이 값을 그대로 effect 의존성으로
  // 쓰는 호출부(문제 편집 화면 등)가 매 렌더 다시 실행돼 폭주한다 — 실제로
  // 그렇게 났었다(#462 코드 리뷰). `queryState`가 안 바뀌면 이 객체도 그대로다.
  const state: ClassDetailState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : queryState.data === NOT_FOUND
            ? { status: "notFound" }
            : { status: "ready", classroom: queryState.data, regenerateError, archiveError },
    [queryState, regenerateError, archiveError],
  );

  const regenerateJoinCode = useCallback(async () => {
    const result = await regenerateJoinLink(classId);
    if (result.ok) {
      setRegenerateError(false);
      reload();
    } else {
      setRegenerateError(true);
    }
  }, [classId, reload]);

  // 보관·되돌리기(#294) — 하나가 다른 하나를 대체한다: 되돌리기는 늘
  // `unarchiveClass`를 부르고, 보관은 늘 `archiveClass`를 부른다. 강사가
  // 연달아 눌러도(더블클릭 등) 백엔드가 멱등이라 마지막 응답이 이긴다.
  //
  // regenerateError는 여기서도 초기화한다 — 보관하면 가입 링크 섹션이 그
  // 오류를 숨기는데(#351), 초기화하지 않으면 되돌렸을 때 관계없는 옛
  // 실패가 그대로 되살아난다(#351 코드 리뷰가 잡은 것).
  const setArchived = useCallback(
    async (archived: boolean) => {
      const result = await (archived ? archiveClass(classId) : unarchiveClass(classId));
      if (result.ok) {
        setRegenerateError(false);
        setArchiveError(false);
        reload();
      } else {
        setArchiveError(true);
      }
    },
    [classId, reload],
  );

  return { state, reload, regenerateJoinCode, setArchived };
}
