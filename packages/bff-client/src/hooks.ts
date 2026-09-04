"use client";

// 인증 구역 화면의 loading/error/ready 상태기계 — 한 곳에 (#146, #122).
//
// 두 앱 합쳐 22벌이던 `useEffect` + `useState` + cancelled 플래그 + reload nonce + 페이지 이어붙이기가
// 이 두 훅으로 온다. TanStack Query 는 들이지 않는다 — e2e 가 「매 마운트마다 새로 읽는다」를
// 전제하고(ADR-0021), 캐시 의미론은 별개 결정이다. 그래서 `cache: "no-store"` 도 여기가 소유한다.

import { useCallback, useEffect, useState } from "react";

import type { BffClient } from "./client";
import type { ApiFailure } from "./result";

export type QueryState<T> =
  | { status: "loading" }
  | { status: "error"; failure: ApiFailure }
  | { status: "ready"; data: T };

export interface BackendQueryOptions<T> {
  /** 2xx 가 아닌 응답을 실패가 아니라 값으로 받고 싶을 때(예: 404 = 「아직 없다」는 정상적인 사실).
   * `undefined` 를 돌려주면 그대로 실패다. */
  onFailure?: (failure: ApiFailure) => T | undefined;
  /** 401 을 「세션이 죽었다」가 아니라 정상적인 답으로 받는다 — `BffRequestInit` 의 같은 이름 참고. */
  unauthorizedIsAnswer?: boolean;
  /** 이 값이 바뀌면 다시 읽는다. 경로가 그대로여도 다시 물어야 하는 자리(헤더의 세션 슬롯이
   * 경로 이동마다 다시 확인하는 것 — 로그인 직후에도 마운트가 유지되기 때문)를 위한 것이다. */
  refetchKey?: string | number;
}

/** 경로 하나를 읽는다. `path` 가 `null` 이면 아무것도 읽지 않고 loading 에 머문다(아직 무엇을 읽을지
 * 모르는 화면). `reload()` 는 같은 경로를 다시 읽는다. */
export function useBackendQuery<T>(
  client: BffClient,
  path: string | null,
  options: BackendQueryOptions<T> = {},
): { state: QueryState<T>; reload: () => void } {
  const [state, setState] = useState<QueryState<T>>({ status: "loading" });
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((current) => current + 1), []);
  const { onFailure, unauthorizedIsAnswer, refetchKey } = options;

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    void client.get<T>(path, { unauthorizedIsAnswer }).then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setState({ status: "ready", data: result.data });
        return;
      }
      const recovered = onFailure?.(result);
      if (recovered !== undefined) {
        setState({ status: "ready", data: recovered });
        return;
      }
      setState({ status: "error", failure: result });
    });
    return () => {
      cancelled = true;
    };
    // `onFailure` 는 호출부가 인라인으로 주는 함수라 의존성에 넣으면 매 렌더마다 다시 읽는다 —
    // 읽을 것은 경로와 nonce 로만 정해진다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, path, nonce, unauthorizedIsAnswer, refetchKey]);

  return { state, reload };
}

export type PagedListState<Row> =
  | { status: "loading" }
  | { status: "error"; failure: ApiFailure }
  | {
      status: "ready";
      rows: Row[];
      count: number;
      /** 아직 안 받은 페이지가 남았는가 — 남았는데 컨트롤이 없으면 그것들은 없는 것이 된다. */
      hasMore: boolean;
      /** 다음 페이지를 **이어 붙인다** — 갈아끼우면 「더 보기」가 앞 페이지를 지운다. */
      loadMore: () => void;
      loadingMore: boolean;
    };

interface PagedBody<Row> {
  items: Row[];
  count: number;
  /** 커서 모드에서만 온다 — 더 없으면 null. */
  next?: string | null;
}

export interface PagedListOptions {
  /** **커서(keyset) 모드**(#151). `?page=N` 대신 `?after=<커서>` 로 「마지막으로 본 행
   * 다음부터」를 묻고, 「더 있는가」를 받은 수와 전체 건수의 비교가 아니라 **서버가 준
   * 다음 커서의 유무**로 판정한다.
   *
   * 오프셋은 목록이 머리 쪽에서 자라면 조용히 틀린다 — 경계가 밀려 다음 묶음이 앞
   * 묶음의 행을 다시 돌려주고, 그 중복이 `rows.length` 를 부풀려 「더 보기」가 아직 안 본
   * 행을 남긴 채 사라진다(#150). 옛 모드를 함께 두는 것은 호출부를 한 번에 다 옮기지
   * 않기 위해서다 — 이관이 끝나면 옛 모드는 사라진다(#153). */
  cursor?: boolean;
}

/** django-ninja PageNumberPagination(`?page=N` → `{items, count}`) 목록을 페이지 이어붙이기로 읽는다.
 *
 * 목록은 `page_size=20` 으로 잘린다. 1페이지만 그리면 그보다 많은 사람은 나머지에 **도달할 길이
 * 없는데**, 빈 상태 판정에 쓰는 `count` 는 전체 건수라 잘렸다는 사실이 화면에 드러나지도 않는다.
 * `-created_at` 정렬이라 잘리는 쪽이 오래된 것들이고, 그중 하나가 「내 차례」면 그 화면이 막으려던
 * 결과가 그대로 일어난다 — 그래서 `hasMore`·`loadMore` 가 상태의 일부다.
 *
 * `path` 가 `null` 이면 아무것도 읽지 않고 loading 에 머문다 — `useBackendQuery` 와 같은 규약이다.
 * 「아직 무엇을 읽을지 모른다」(세션 확인 전 등)를 호출부가 표현할 자리가 여기 말고 없다(#149):
 * 반환값만 loading 으로 덮으면 요청은 이미 나간 뒤라, 만료된 세션에서 401 이 세션 조회와 경합해
 * 로그인으로 튕기고, 그 사이 실패한 조회는 조건이 참이 돼도 **다시 시도되지 않는다**.
 */
export function usePagedList<Row>(
  client: BffClient,
  path: string | null,
  options: PagedListOptions = {},
): PagedListState<Row> {
  const cursorMode = options.cursor === true;
  const [phase, setPhase] = useState<"loading" | "error" | "ready" | "more">("loading");
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  // 커서 모드에서 다음에 물을 자리. `null` 은 「처음부터」, `undefined` 는 「더 없다」다 —
  // 그 둘을 하나로 뭉치면 끝에 도달한 목록이 처음부터 다시 읽힌다.
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  // **경로가 바뀌면 쌓아 둔 페이지를 버린다**(#149). 이 훅은 「더 보기」를 위해 페이지를
  // 이어 붙이는데, 그 상태가 경로에 딸린 것이라는 사실이 코드에 없었다 — 필터가 붙은
  // 경로로 이 훅을 쓰면 3페이지를 보던 중 필터를 바꿨을 때 **새 필터의 3페이지**를 받아
  // 옛 목록 뒤에 이어 붙인다. 지금까지의 호출부 둘(`/contests/mine`·`/submissions/mine`)이
  // 고정 경로라 드러나지 않았을 뿐이다.
  //
  // effect 가 아니라 렌더 도중에 되돌린다("Adjusting state when a prop changes", React)
  // — effect 는 이미 한 번 커밋된 뒤라 그 한 프레임이 화면에 그려진다.
  const [committedPath, setCommittedPath] = useState(path);
  if (path !== committedPath) {
    setCommittedPath(path);
    setRows([]);
    setCount(0);
    setPage(1);
    setCursor(null);
    setNextCursor(null);
    setPhase("loading");
  }

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    const separator = path.includes("?") ? "&" : "?";
    const query = cursorMode
      ? cursor === null
        ? ""
        : `${separator}after=${encodeURIComponent(cursor)}`
      : `${separator}page=${page}`;
    const first = cursorMode ? cursor === null : page === 1;
    void client.get<PagedBody<Row>>(`${path}${query}`).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setFailure(result);
        setPhase("error");
        return;
      }
      setRows((previous) => (first ? result.data.items : [...previous, ...result.data.items]));
      setCount(result.data.count);
      if (cursorMode) setNextCursor(result.data.next ?? null);
      setPhase("ready");
    });
    return () => {
      cancelled = true;
    };
  }, [client, path, page, cursor, cursorMode]);

  if (phase === "loading") return { status: "loading" };
  if (phase === "error") {
    return {
      status: "error",
      failure: failure ?? { ok: false, status: 0, code: "network", detail: "" },
    };
  }
  return {
    status: "ready",
    rows,
    count,
    // 커서 모드에서는 **서버가 다음 커서를 줬는가**로 판정한다. 받은 수와 전체 건수를
    // 비교하는 방식은 목록이 자라는 동안 틀린다 — 중복이 섞이면 아직 안 본 행이 남았는데도
    // 「더 보기」가 사라진다(#150).
    hasMore: cursorMode ? nextCursor !== null : rows.length < count,
    loadingMore: phase === "more",
    loadMore: () => {
      setPhase("more");
      if (cursorMode) {
        setCursor(nextCursor);
        return;
      }
      setPage((current) => current + 1);
    },
  };
}
