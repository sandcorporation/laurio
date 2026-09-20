"use client";

// 강사가 보는 제출 현황 상태 (#291). 강사 본인의 클래스가 아니거나 문제를
// 찾을 수 없으면 백엔드가 404를 준다 — `use-my-problem.ts`와 같은 이유로 그
// 사실을 "notFound"로 구별한다. 그 클래스의 강사만 200을 받는다(#291 AC) — 이
// 요청 자체는 어디에도 기록되지 않는다(ADR-0040, 참여자의 소스 열람 이력이
// 없는 것과 같은 이유). 공유 클라이언트 위에 선다(#462).
//
// **새 제출과 채점 결과가 새로고침 없이 나타난다**(#383, ADR-0046). 이
// 문제의 `attempt-submitted`(새 시도가 생겼다)·`attempt-scored`(그 시도의
// 채점이 끝났다) 둘 다 받으면 다시 불러온다 — 신호 안의 데이터를 직접
// 그리지 않고 기존 API를 다시 부른다. 스트림이 끊기면 「채점 중」 시도가
// 있는 동안만 `use-my-problem.ts`와 같은 간격으로 폴링으로 물러나고, 다시
// 연결되면 한 번 재조회한다.
import { useCallback, useEffect, useMemo, useRef } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import { useEventStream } from "@/lib/events/stream-context";
import { decideStreamRefresh } from "@/lib/events/policy";
import {
  ATTEMPT_SCORED,
  ATTEMPT_SUBMITTED,
  type StreamConnectionState,
} from "@/lib/events/types";

import type { InstructorSubmissionRow } from "./api";

export type ProblemSubmissionsState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; submissions: InstructorSubmissionRow[] };

//: 「채점 중」 시도가 있을 때 스트림이 끊긴 동안 물러나는 간격 —
//: `use-my-problem.ts`의 FALLBACK_POLL_MS와 같은 값·같은 이유다.
const FALLBACK_POLL_MS = 4_000;

const NOT_FOUND = Symbol("problem-submissions-not-found");

export function useProblemSubmissions(classId: number, problemId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<
    InstructorSubmissionRow[] | typeof NOT_FOUND
  >(bffClient, `/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`, {
    onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined),
  });
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  const { connectionState, subscribe } = useEventStream();
  const previousConnectionState = useRef<StreamConnectionState>(connectionState);

  // 이 문제의 attempt-submitted·attempt-scored만 반응한다 — 다른 문제·다른
  // 클래스의 신호는 무시한다(각 화면은 자기와 관계있는 신호에만 반응한다,
  // ADR-0046).
  useEffect(() => {
    return subscribe((event) => {
      if (event.kind !== ATTEMPT_SUBMITTED && event.kind !== ATTEMPT_SCORED) return;
      if (event.payload.class_id !== classId || event.payload.problem_id !== problemId) return;
      reload();
    });
  }, [subscribe, reload, classId, problemId]);

  useEffect(() => {
    const decision = decideStreamRefresh(
      previousConnectionState.current,
      connectionState,
      FALLBACK_POLL_MS,
    );
    previousConnectionState.current = connectionState;
    if (decision.refetchNow) reload();
  }, [connectionState, reload]);

  const hasPendingAttempt =
    queryState.status === "ready" &&
    queryState.data !== NOT_FOUND &&
    queryState.data.some((s) => s.status === "pending");

  useEffect(() => {
    if (connectionState === "open") return; // 연결됨: 폴링 없음.
    if (!hasPendingAttempt) return; // 기다릴 것이 없으면 이 화면은 조용히 있는다.
    const timer = setInterval(reload, FALLBACK_POLL_MS);
    return () => clearInterval(timer);
  }, [connectionState, hasPendingAttempt, reload]);

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰).
  const state: ProblemSubmissionsState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : queryState.data === NOT_FOUND
            ? { status: "notFound" }
            : { status: "ready", submissions: queryState.data },
    [queryState],
  );

  return { state, reload };
}
