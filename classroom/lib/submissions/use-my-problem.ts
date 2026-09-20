"use client";

// 참여자가 보는 문제+시도 목록 상태 (#286). 참여자가 아니거나 문제가 열려
// 있지 않으면 백엔드가 404를 준다 — `use-class.ts`와 같은 이유로 그 사실을
// "notFound"로 구별한다. 공유 클라이언트 위에 선다(#462).
//
// **새로고침 없이 「채점 완료」로 바뀐다**(#379, ADR-0046). 이 문제의
// `attempt-scored` 신호를 받으면 다시 불러온다 — 신호 안의 데이터를 직접
// 그리지 않고 기존 API를 다시 부른다(스트림은 진실의 출처가 아니다). 배선
// 자체는 `useRealtimeRefresh`(#467) 하나가 진다 — 「채점 중」 시도가 있는
// 동안만(`waiting`) 스트림이 끊긴 사이 짧게 폴링으로 물러나고, 다시
// 연결되면 한 번 재조회한다.
import { useCallback, useMemo } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";
import { ATTEMPT_SCORED, ATTEMPT_SUBMITTED, type StreamEvent } from "@/lib/events/types";

import type { ProblemSubmissions } from "./api";

export type MyProblemState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; data: ProblemSubmissions };

//: 「채점 중」 시도가 있을 때 스트림이 끊긴 동안 물러나는 간격 — 벨의 30초
//: (`use-unread-count.ts`)보다 짧게 잡는다: 이 화면은 사람이 결과를 기다리며
//: 보고 있는 화면이라 체감이 더 중요하다.
const FALLBACK_POLL_MS = 4_000;

const NOT_FOUND = Symbol("my-problem-not-found");

export function useMyProblem(classId: number, problemId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<
    ProblemSubmissions | typeof NOT_FOUND
  >(bffClient, `/api/backend/classroom/classes/${classId}/problems/${problemId}/mine`, {
    onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined),
  });
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  const hasPendingAttempt =
    queryState.status === "ready" &&
    queryState.data !== NOT_FOUND &&
    queryState.data.submissions.some((s) => s.status === "pending");

  // 이 문제의 attempt-submitted·attempt-scored만 반응한다 — 다른 문제·다른
  // 클래스의 신호는 무시한다(각 화면은 자기와 관계있는 신호에만 반응한다,
  // ADR-0046). attempt-submitted를 더한 이유는 #383 AC "다른 탭에서 낸
  // 시도가 나타난다" — 이 참여자가 다른 탭·기기에서 낸 시도도 새로고침
  // 없이 이 목록에 보여야 한다.
  const matches = useCallback(
    (event: StreamEvent) =>
      (event.kind === ATTEMPT_SCORED || event.kind === ATTEMPT_SUBMITTED) &&
      event.payload.class_id === classId &&
      event.payload.problem_id === problemId,
    [classId, problemId],
  );
  useRealtimeRefresh({ matches, waiting: hasPendingAttempt, fallbackPollMs: FALLBACK_POLL_MS, reload });

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰).
  const state: MyProblemState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : queryState.data === NOT_FOUND
            ? { status: "notFound" }
            : { status: "ready", data: queryState.data },
    [queryState],
  );

  return { state, reload };
}
