"use client";

// 공개 클래스 템플릿 검색 목록 상태 (#319) —
// `problem-templates/use-problem-templates.ts`와 같은 모양이다.
import { useEffect, useState } from "react";

import { fetchClassTemplates, type ClassTemplateListItem } from "./api";

export type ClassTemplatesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: ClassTemplateListItem[]; count: number; page: number; hasMore: boolean };

const PAGE_SIZE = 20;

export function useClassTemplates(q: string) {
  const [state, setState] = useState<ClassTemplatesState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchClassTemplates({ q: q || undefined, page: 1 })
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
    const result = await fetchClassTemplates({ q: q || undefined, page: nextPage });
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
