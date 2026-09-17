"use client";

// 「불러오는 중 / 오류 / 준비됨」 상태 기계 하나를 자리마다 손으로 새로
// 쓰던 것을 묶은 공용 불러오기 도우미 (#443, 부모 #432) — 템플릿 선택
// 시트의 탭 셋과 선택한 항목의 상세가 그랬다.
//
// `active`가 참인 동안 `deps`가 바뀔 때마다 다시 부른다 — 탭을 바꿔 같은
// 탭으로 되돌아와도 다시 부르므로 시트를 여는 동안 언제나 최신이다(예전
// 「내가 올린 것」·「내 다른 클래스에서」 탭은 처음 한 번만 불러오고 그
// 뒤로는 캐시를 썼다 — 의도된 절약이라기보다 손으로 쓴 상태 기계 세 벌이
// 서로 다른 습관을 가진 것에 더 가까웠다).
import { useEffect, useState } from "react";
import type { DependencyList } from "react";

export type LoadableState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; data: T };

export function useLoadable<T>(active: boolean, loader: () => Promise<T>, deps: DependencyList): LoadableState<T> {
  const [state, setState] = useState<LoadableState<T>>({ status: "idle" });

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setState({ status: "loading" });
    loader()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ...deps]);

  return state;
}
