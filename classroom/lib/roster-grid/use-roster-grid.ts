"use client";

// 참여자 × 문제 격자 상태 (#290). 남의 클래스는 백엔드가 404를 준다 — 클래스
// 상세와 같은 이유로 "클래스를 찾을 수 없습니다"로 보여준다.
// 공유 클라이언트 위에 선다(#462).
//
// **새로고침 없이 갱신된다**(#467, ADR-0046). 참여자가 내거나(attempt-
// submitted) 채점이 끝나면(attempt-scored) 강사에게도 이미 그 클래스의
// 신호가 가고 있었는데 이 격자는 그것을 안 쓰고 있었다 — 이제 이 클래스의
// 신호를 받으면 다시 불러온다. 배선은 `useRealtimeRefresh` 하나가 진다.
import { useCallback, useMemo, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";
import { ATTEMPT_SCORED, ATTEMPT_SUBMITTED, type StreamEvent } from "@/lib/events/types";

import { expelMember } from "@/lib/members/api";

import type { RosterGrid } from "./api";

export type RosterGridState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; grid: RosterGrid };

//: 「채점 중」 표시가 없는 개요 화면이라 참여자 문제 목록(`use-my-problems.ts`)
//: 과 같은 30초로 잡는다 — 격자 전체는 늘 기다리는 셈이다.
const FALLBACK_POLL_MS = 30_000;

const NOT_FOUND = Symbol("roster-grid-not-found");

export function useRosterGrid(classId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<RosterGrid | typeof NOT_FOUND>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/roster-grid`,
    { onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined) },
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  // 내보내기(#634) — 합친 참여자 탭의 ⋮ 메뉴가 부른다. 성공하면 격자를 다시 읽는다.
  const [expelError, setExpelError] = useState(false);
  const expel = useCallback(
    async (memberId: number) => {
      const result = await expelMember(classId, memberId);
      setExpelError(!result.ok);
      if (result.ok) reload();
      return result.ok;
    },
    [classId, reload],
  );

  // 이 클래스의 attempt-submitted·attempt-scored만 반응한다 — 다른
  // 클래스의 신호는 무시한다(각 화면은 자기와 관계있는 신호에만 반응한다,
  // ADR-0046).
  const matches = useCallback(
    (event: StreamEvent) =>
      (event.kind === ATTEMPT_SUBMITTED || event.kind === ATTEMPT_SCORED) &&
      event.payload.class_id === classId,
    [classId],
  );
  useRealtimeRefresh({ matches, waiting: true, fallbackPollMs: FALLBACK_POLL_MS, reload });

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰).
  const state: RosterGridState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : queryState.data === NOT_FOUND
            ? { status: "notFound" }
            : { status: "ready", grid: queryState.data },
    [queryState],
  );

  return { state, reload, expel, expelError };
}
