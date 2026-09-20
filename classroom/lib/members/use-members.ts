"use client";

// 참여자 명단 상태 (#281). 남의 클래스는 백엔드가 404를 준다 — 클래스 상세와
// 같은 이유로 "클래스를 찾을 수 없습니다"로 보여준다. 공유 클라이언트 위에
// 선다(#462).
import { useCallback, useMemo, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import { expelMember, type MemberRow } from "./api";

export type MembersState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; members: MemberRow[]; expelError: boolean };

const NOT_FOUND = Symbol("members-not-found");

export function useMembers(classId: number) {
  const { state: queryState, reload } = useBackendQuery<MemberRow[] | typeof NOT_FOUND>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/members`,
    { onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined) },
  );
  const [expelError, setExpelError] = useState(false);

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰, use-class.ts와 같은 이유).
  const state: MembersState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : queryState.data === NOT_FOUND
            ? { status: "notFound" }
            : { status: "ready", members: queryState.data, expelError },
    [queryState, expelError],
  );

  const expel = useCallback(
    async (memberId: number) => {
      const result = await expelMember(classId, memberId);
      if (result.ok) {
        setExpelError(false);
        reload();
      } else {
        setExpelError(true);
      }
    },
    [classId, reload],
  );

  return { state, expel };
}
