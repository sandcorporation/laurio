"use client";

// 참여자 명단 상태 (#281). 남의 클래스는 백엔드가 404를 준다 — 클래스 상세와
// 같은 이유로 "클래스를 찾을 수 없습니다"로 보여준다.
import { useCallback, useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { expelMember, fetchMembers, type MemberRow } from "./api";

export type MembersState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; members: MemberRow[]; expelError: boolean };

export function useMembers(classId: number) {
  const [state, setState] = useState<MembersState>({ status: "loading" });

  const reload = useCallback(() => {
    setState({ status: "loading" });
    fetchMembers(classId)
      .then((members) => setState({ status: "ready", members, expelError: false }))
      .catch((error: unknown) => {
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "notFound" });
        } else {
          setState({ status: "error" });
        }
      });
  }, [classId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const expel = useCallback(
    async (memberId: number) => {
      if (state.status !== "ready") return;
      try {
        const updated = await expelMember(classId, memberId);
        setState({
          status: "ready",
          members: state.members.map((m) => (m.id === updated.id ? updated : m)),
          expelError: false,
        });
      } catch {
        setState({ status: "ready", members: state.members, expelError: true });
      }
    },
    [classId, state],
  );

  return { state, expel };
}
