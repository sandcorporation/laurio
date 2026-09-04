"use client";

// Operator 목록 조회(#69). 세 가지 실패 상태를 서로 구별한다 — 빈 목록·403·요청
// 실패가 뭉개지면 화면이 거짓말을 한다:
//
// - **403(forbidden)**: 로그인은 됐지만 상위 등급이 아니다. "등급이 필요하다"고
//   말해야 한다 — 빈 목록도 깨진 화면도 아니다(#69 인수조건, 티켓의 "403은 빈
//   목록이 아니다"라는 요구).
// - **401**: 세션이 만료됐다. `use-queue-counts.ts`와 같은 원칙으로 로그인으로
//   돌려보낸다.
// - **그 외 실패(error)**: 알 수 없는 백엔드 오류. "불러오지 못했다"고 말한다.
//
// `reload()`는 생성·비활성화·재활성화 뒤에 목록을 다시 읽어 오는 데 쓴다 — 목록
// 화면이 자기가 만든 변화를 스스로 반영해야, 사용자가 방금 한 일이 실제로 반영됐는지
// 페이지를 새로고침하지 않고도 확인할 수 있다.
import { useCallback, useEffect, useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { OperatorAccount } from "./types";

export type OperatorsState =
  | { status: "loading" }
  | { status: "forbidden" }
  | { status: "error" }
  | { status: "loaded"; operators: OperatorAccount[] };

export function useOperators(enabled: boolean): { state: OperatorsState; reload: () => void } {
  const [state, setState] = useState<OperatorsState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    // 여기서 `setState({status:"loading"})`를 부르지 않는다(코드리뷰 지적).
    // 첫 조회는 `state`의 초기값이 이미 `{status:"loading"}`이라 그걸로
    // 충분하다. `reload()`(생성·비활성화·재활성화 뒤 재조회)가 매번 다시
    // "loading"으로 리셋하면, 페이지의 최상단 게이트(`state.status ===
    // "loading"`)가 이미 그려진 표와 생성 폼을 통째로 걷어내고 스피너로
    // 바꿔치기한다 — 방금 만든 계정의 행이 화면에서 사라졌다 다시 나타나는
    // 것처럼 보이고, 그 사이 폼·행의 로컬 상태(입력값·pending·에러 메시지)도
    // 전부 날아간다. 대신 이미 그려진 화면(loaded든 forbidden·error든)을
    // 그대로 유지한 채 조용히 다시 읽고, 응답이 오면 그 결과로만 갱신한다.

    void bffClient.get<OperatorAccount[]>("/api/backend/operator/operators").then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setState({ status: "loaded", operators: result.data });
        return;
      }
      // 401 은 클라이언트가 로그인으로 보낸다(#148). 403 은 다르다 — 로그인은 살아 있고 이
      // 계정에 권한이 없다는 뜻이라, 화면이 그렇게 말해야 한다.
      setState(result.status === 403 ? { status: "forbidden" } : { status: "error" });
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, version]);

  return { state, reload };
}
