"use client";

// 공개 클래스 템플릿 검색 목록 상태 (#319) —
// `problem-templates/use-problem-templates.ts`와 같은 모양이다. 공유
// 클라이언트 위에 선다(#462).
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
    fetchClassTemplates({ q: q || undefined, page: 1 }).then((result) => {
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
    const result = await fetchClassTemplates({ q: q || undefined, page: nextPage });
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
