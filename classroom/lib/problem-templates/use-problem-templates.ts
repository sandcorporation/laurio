"use client";

// 공개 템플릿 검색 목록 상태 (#318). 항목이 많아져도 한 번에 전부 내려받지
// 않는다 — 페이지네이션을 그대로 상태로 든다. 공유 클라이언트 위에
// 선다(#462).
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
    fetchProblemTemplates({ q: q || undefined, page: 1 }).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setState({ status: "error" });
        return;
      }
      setState({
        status: "ready",
        items: result.data.items,
        count: result.data.count,
        page: 1,
        hasMore: result.data.items.length < result.data.count,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [q]);

  async function loadMore() {
    if (state.status !== "ready" || !state.hasMore) return;
    const nextPage = state.page + 1;
    const result = await fetchProblemTemplates({ q: q || undefined, page: nextPage });
    if (!result.ok) return;
    setState({
      status: "ready",
      items: [...state.items, ...result.data.items],
      count: result.data.count,
      page: nextPage,
      hasMore: state.items.length + result.data.items.length < result.data.count,
    });
  }

  return { state, loadMore, pageSize: PAGE_SIZE };
}
