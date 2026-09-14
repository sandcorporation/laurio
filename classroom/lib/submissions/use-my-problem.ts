"use client";

// 참여자가 보는 문제+시도 목록 상태 (#286). 참여자가 아니거나 문제가 열려
// 있지 않으면 백엔드가 404를 준다 — `use-class.ts`와 같은 이유로 그 사실을
// "notFound"로 구별한다.
//
// **새로고침 없이 「채점 완료」로 바뀐다**(#379, ADR-0046). 이 문제의
// `attempt-scored` 신호를 받으면 다시 불러온다 — 신호 안의 데이터를 직접
// 그리지 않고 기존 API를 다시 부른다(스트림은 진실의 출처가 아니다). 스트림이
// 끊기면(`decideStreamRefresh`) 「채점 중」 시도가 있는 동안만 짧게 폴링으로
// 물러나고, 다시 연결되면 한 번 재조회한다.
import { useCallback, useEffect, useRef, useState } from "react";

import { BackendError } from "@/lib/backend/client";
import { useEventStream } from "@/lib/events/stream-context";
import { decideStreamRefresh } from "@/lib/events/policy";
import {
  ATTEMPT_SCORED,
  ATTEMPT_SUBMITTED,
  type StreamConnectionState,
} from "@/lib/events/types";

import { fetchMyProblem, type ProblemSubmissions } from "./api";

export type MyProblemState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; data: ProblemSubmissions };

//: 「채점 중」 시도가 있을 때 스트림이 끊긴 동안 물러나는 간격 — 벨의 30초
//: (`use-unread-count.ts`)보다 짧게 잡는다: 이 화면은 사람이 결과를 기다리며
//: 보고 있는 화면이라 체감이 더 중요하다.
const FALLBACK_POLL_MS = 4_000;

export function useMyProblem(classId: number, problemId: number) {
  const [state, setState] = useState<MyProblemState>({ status: "loading" });
  const { connectionState, subscribe } = useEventStream();
  const previousConnectionState = useRef<StreamConnectionState>(connectionState);

  const reload = useCallback(() => {
    fetchMyProblem(classId, problemId)
      .then((data) => setState({ status: "ready", data }))
      .catch((error: unknown) => {
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "notFound" });
        } else {
          setState((prev) => (prev.status === "ready" ? prev : { status: "error" }));
        }
      });
  }, [classId, problemId]);

  useEffect(() => {
    // 보고 있는 대상이 바뀔 때만 화면을 비운다 — 다시 불러오기(`reload`)는 새 응답이
    // 올 때까지 이미 그린 화면을 둔다(lib/rendering/refetch-keeps-screen.test.ts).
    setState({ status: "loading" });
    reload();
  }, [reload]);

  // 이 문제의 attempt-submitted·attempt-scored만 반응한다 — 다른 문제·다른
  // 클래스의 신호는 무시한다(각 화면은 자기와 관계있는 신호에만 반응한다,
  // ADR-0046). attempt-submitted를 더한 이유는 #383 AC "다른 탭에서 낸
  // 시도가 나타난다" — 이 참여자가 다른 탭·기기에서 낸 시도도 새로고침
  // 없이 이 목록에 보여야 한다.
  useEffect(() => {
    return subscribe((event) => {
      if (event.kind !== ATTEMPT_SCORED && event.kind !== ATTEMPT_SUBMITTED) return;
      if (event.payload.class_id !== classId || event.payload.problem_id !== problemId) return;
      reload();
    });
  }, [subscribe, reload, classId, problemId]);

  const hasPendingAttempt =
    state.status === "ready" && state.data.submissions.some((s) => s.status === "pending");

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
    if (!hasPendingAttempt) return; // 기다릴 것이 없으면 이 화면은 조용히 있는다.
    const timer = setInterval(reload, FALLBACK_POLL_MS);
    return () => clearInterval(timer);
  }, [connectionState, hasPendingAttempt, reload]);

  return { state, reload };
}
