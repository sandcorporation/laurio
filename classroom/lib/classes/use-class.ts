"use client";

// 클래스 상세 상태 (#278/#279). 남의 클래스는 백엔드가 404를 준다 — 그 사실을
// "notFound"로 구별해 화면이 "클래스를 찾을 수 없습니다"를 보여준다.
import { useCallback, useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { archiveClass, fetchClass, regenerateJoinLink, unarchiveClass, type ClassRow } from "./api";

export type ClassDetailState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; classroom: ClassRow; regenerateError: boolean; archiveError: boolean };

export function useClass(classId: number) {
  const [state, setState] = useState<ClassDetailState>({ status: "loading" });

  function load() {
    let cancelled = false;
    fetchClass(classId)
      .then((classroom) => {
        if (!cancelled) {
          setState({ status: "ready", classroom, regenerateError: false, archiveError: false });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "notFound" });
        } else {
          setState((prev) => (prev.status === "ready" ? prev : { status: "error" }));
        }
      });
    return () => {
      cancelled = true;
    };
  }

  useEffect(() => {
    // 보고 있는 대상이 바뀔 때만 화면을 비운다 — 다시 불러오기(`reload`)는 새 응답이
    // 올 때까지 이미 그린 화면을 둔다(lib/rendering/refetch-keeps-screen.test.ts).
    setState({ status: "loading" });
    const cancel = load();
    return cancel;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId]);

  const regenerateJoinCode = useCallback(async () => {
    if (state.status !== "ready") return;
    try {
      const { join_code } = await regenerateJoinLink(classId);
      setState({
        status: "ready",
        classroom: { ...state.classroom, join_code },
        regenerateError: false,
        archiveError: state.archiveError,
      });
    } catch {
      setState({ ...state, regenerateError: true });
    }
  }, [classId, state]);

  // 보관·되돌리기(#294) — 하나가 다른 하나를 대체한다: 되돌리기는 늘
  // `unarchiveClass`를 부르고, 보관은 늘 `archiveClass`를 부른다. 강사가
  // 연달아 눌러도(더블클릭 등) 백엔드가 멱등이라 마지막 응답이 이긴다.
  //
  // regenerateError는 여기서 초기화한다 — 보관하면 가입 링크 섹션이 그
  // 오류를 숨기는데(#351), 초기화하지 않으면 되돌렸을 때 관계없는 옛
  // 실패가 그대로 되살아난다(#351 코드 리뷰가 잡은 것).
  const setArchived = useCallback(
    async (archived: boolean) => {
      if (state.status !== "ready") return;
      try {
        const classroom = await (archived ? archiveClass(classId) : unarchiveClass(classId));
        setState({ status: "ready", classroom, regenerateError: false, archiveError: false });
      } catch {
        setState({ ...state, archiveError: true });
      }
    },
    [classId, state],
  );

  return { state, reload: load, regenerateJoinCode, setArchived };
}
