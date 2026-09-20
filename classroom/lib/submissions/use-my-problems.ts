"use client";

// 참여자의 문제 목록 상태 (#288). 참여자가 아니면 백엔드가 404를 준다 —
// `use-my-problem.ts`와 같은 이유로 "notFound"로 구별한다. 공유 클라이언트
// 위에 선다(#462).
//
// **통과 표시가 새로고침 없이 바뀐다**(#382, ADR-0046). 이 클래스의
// `attempt-scored` 신호를 받으면 다시 불러온다 — 다른 클래스의 신호는
// 무시한다, 신호 안의 데이터를 직접 그리지 않고 기존 API를 다시 부른다
// (스트림은 진실의 출처가 아니다). 스트림이 끊기면 `decideStreamRefresh`가
// 정한 대로 폴링으로 물러나고, 다시 연결되면 한 번 재조회한다.
import { useCallback, useEffect, useMemo, useRef } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import { useEventStream } from "@/lib/events/stream-context";
import { decideStreamRefresh } from "@/lib/events/policy";
import { ATTEMPT_SCORED, type StreamConnectionState } from "@/lib/events/types";

import type { MyProblems, ProblemListItem } from "./api";

export type MyProblemsState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | {
      status: "ready";
      // 눈썹이 말할 클래스 이름(#372 후속).
      className: string;
      problems: ProblemListItem[];
      // 강사가 숨겼지만 이 참여자가 한 번이라도 낸 문제들(#406) — 목록
      // 아래 접힌 「숨겨진 문제」 섹션이 쓴다.
      hiddenProblems: ProblemListItem[];
      // 이름 편집 칸의 초기값과, 그 칸 자체를 숨길지 판단할 신호(#372) — 이
      // 클래스에서 지금 불리는 이름은 `list_my_problems`가 그대로 실어 준다,
      // 비정규화 없이 렌더될 때마다 서버 값을 다시 받는다.
      memberDisplayName: string;
      memberExpelled: boolean;
      archived: boolean;
    };

//: 스트림이 끊긴 동안 물러나는 간격 — 이 화면은 `use-my-problem.ts`(채점을
//: 기다리며 보는 화면)와 달리 "채점 중" 표시가 없어 체감 급박함이 낮다,
//: 벨(`use-unread-count.ts`)과 같은 30초로 잡는다.
const FALLBACK_POLL_MS = 30_000;

const NOT_FOUND = Symbol("my-problems-not-found");

export function useMyProblems(classId: number) {
  const { state: queryState, reload: refetch } = useBackendQuery<MyProblems | typeof NOT_FOUND>(
    bffClient,
    `/api/backend/classroom/classes/${classId}/problems/mine`,
    { onFailure: (failure) => (failure.status === 404 ? NOT_FOUND : undefined) },
  );
  // `refetch-keeps-screen.test.ts`가 이 이름의 로컬 선언을 찾는다.
  const reload = useCallback(() => {
    refetch();
  }, [refetch]);

  const { connectionState, subscribe } = useEventStream();
  const previousConnectionState = useRef<StreamConnectionState>(connectionState);

  // 이 클래스의 attempt-scored만 반응한다 — 다른 클래스의 신호는 무시한다
  // (각 화면은 자기와 관계있는 신호에만 반응한다, ADR-0046).
  useEffect(() => {
    return subscribe((event) => {
      if (event.kind !== ATTEMPT_SCORED) return;
      if (event.payload.class_id !== classId) return;
      reload();
    });
  }, [subscribe, reload, classId]);

  useEffect(() => {
    const decision = decideStreamRefresh(
      previousConnectionState.current,
      connectionState,
      FALLBACK_POLL_MS,
    );
    previousConnectionState.current = connectionState;
    if (decision.refetchNow) reload();
  }, [connectionState, reload]);

  useEffect(() => {
    if (connectionState === "open") return; // 연결됨: 폴링 없음.
    const timer = setInterval(reload, FALLBACK_POLL_MS);
    return () => clearInterval(timer);
  }, [connectionState, reload]);

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 effect 의존성으로 쓰는
  // 호출부가 폭주할 수 있다(#462 코드 리뷰).
  const state: MyProblemsState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : queryState.data === NOT_FOUND
            ? { status: "notFound" }
            : {
                status: "ready",
                className: queryState.data.class_name,
                problems: queryState.data.problems,
                hiddenProblems: queryState.data.hidden_problems,
                memberDisplayName: queryState.data.member_display_name,
                memberExpelled: queryState.data.member_expelled,
                archived: queryState.data.archived,
              },
    [queryState],
  );

  return { state, reload };
}
