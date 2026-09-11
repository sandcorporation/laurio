"use client";

// 공개 템플릿 검색 목록 상태 (#318). 항목이 많아져도 한 번에 전부 내려받지
// 않는다 — 페이지네이션을 그대로 상태로 든다.
import { useEffect, useState } from "react";

import { fetchProblemTemplates, type ProblemTemplateListItem } from "./api";

export type ProblemTemplatesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: ProblemTemplateListItem[]; count: number; page: number; hasMore: boolean };

const PAGE_SIZE = 20;

export function useProblemTemplates(q: string) {
  const [state, setState] = useState<ProblemTemplatesState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchProblemTemplates({ q: q || undefined, page: 1 })
      .then((result) => {
        if (cancelled) return;
        setState({
          status: "ready",
          items: result.items,
          count: result.count,
          page: 1,
          hasMore: result.items.length < result.count,
        });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [q]);

  async function loadMore() {
    if (state.status !== "ready" || !state.hasMore) return;
    const nextPage = state.page + 1;
    const result = await fetchProblemTemplates({ q: q || undefined, page: nextPage });
    setState({
      status: "ready",
      items: [...state.items, ...result.items],
      count: result.count,
      page: nextPage,
      hasMore: state.items.length + result.items.length < result.count,
    });
  }

  return { state, loadMore, pageSize: PAGE_SIZE };
}
