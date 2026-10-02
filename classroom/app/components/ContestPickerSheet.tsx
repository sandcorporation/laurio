"use client";

// 새 문제 화면의 「공모전에서 들여오기」 시트(#548, CONTEXT.md 「공모전 문제」). 개최자가 클래스에서
// 들여오기를 허용한 공개 중 · 마감 전 무료 공모전을 고르면 지금 이 클래스에 초안으로 들어온다.
// 템플릿 가져오기와 달리 제목·설명·체크리스트가 공모전을 **따라간다** — 개최자가 고치면 함께 바뀌고
// 강사는 고치지 못한다. 그 사실을 고르기 전에 말한다.
import { useEffect, useRef, useState } from "react";

import { EmptyState, ErrorNote, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { formatPickerDate } from "@/lib/problem-templates/picker-selection";
import {
  fetchImportableContests,
  importContestProblem,
  type ImportableContestRow,
  type ProblemRow,
} from "@/lib/problems/api";

type ListState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: ImportableContestRow[]; next: string | null; loadingMore: boolean };

export function ContestPickerSheet({
  classId,
  onClose,
  onImported,
}: {
  classId: number;
  onClose: () => void;
  onImported: (problem: ProblemRow) => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  // 공모전이 많을 수 있다 — 제목으로 찾고, 마감 빠른 순 20개씩 「더 보기」로 이어 받는다.
  const [query, setQuery] = useState("");
  const [state, setState] = useState<ListState>({ status: "loading" });
  // 검색어를 빠르게 바꾸면 늦게 온 옛 응답이 새 목록을 덮지 않게 한다.
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    setState({ status: "loading" });
    const timer = window.setTimeout(async () => {
      const result = await fetchImportableContests(classId, { query });
      if (id !== requestId.current) return;
      setState(
        result.ok
          ? { status: "ready", items: result.data.items, next: result.data.next, loadingMore: false }
          : { status: "error" },
      );
    }, 250);
    return () => window.clearTimeout(timer);
  }, [classId, query]);

  async function loadMore() {
    if (state.status !== "ready" || state.next === null || state.loadingMore) return;
    const id = requestId.current;
    setState({ ...state, loadingMore: true });
    const result = await fetchImportableContests(classId, { query, after: state.next });
    if (id !== requestId.current) return;
    if (!result.ok) {
      setState({ ...state, loadingMore: false });
      return;
    }
    setState({
      status: "ready",
      items: [...state.items, ...result.data.items],
      next: result.data.next,
      loadingMore: false,
    });
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  async function handleImport() {
    if (selected === null) return;
    setImporting(true);
    setImportError(null);
    const result = await importContestProblem(classId, selected);
    setImporting(false);
    if (!result.ok) {
      setImportError(result.detail);
      return;
    }
    onImported(result.data);
  }

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/40 p-4">
      <button type="button" aria-label="닫기" onClick={onClose} className="fixed inset-0 cursor-default" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="공모전에서 들여오기"
        data-testid="contest-picker-sheet"
        className="relative flex max-h-[85vh] w-full max-w-[640px] flex-col border border-rule bg-surface"
      >
        <div className="flex items-start justify-between gap-3 border-b border-rule p-5">
          <div>
            <h2 className="text-[17px] font-semibold">공모전에서 들여오기</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/60">
              개최자가 클래스에서 쓰도록 허용한 무료 공모전입니다. 고른 공모전이 이 클래스에 초안으로
              들어옵니다.
            </p>
          </div>
          <button type="button" data-testid="contest-picker-close" onClick={onClose} className={buttonClass("secondary", "sm")}>
            닫기
          </button>
        </div>

        <div className="border-b border-rule px-4 py-3">
          <input
            type="search"
            data-testid="contest-picker-search"
            aria-label="공모전 제목으로 찾기"
            placeholder="공모전 제목으로 찾기"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className={`w-full ${INPUT_CLASS}`}
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {state.status === "loading" ? (
            <p className="p-5 text-[13px] text-ink/45">불러오는 중...</p>
          ) : state.status === "error" ? (
            <div className="p-5">
              <ErrorNote>
                <span>목록을 불러오지 못했습니다.</span>
              </ErrorNote>
            </div>
          ) : state.items.length === 0 ? (
            <div className="p-5">
              <EmptyState>
                <span data-testid="contest-picker-empty">
                  {query.trim()
                    ? `「${query.trim()}」이 든 공모전이 없습니다.`
                    : "지금 들여올 수 있는 공모전이 없습니다."}
                </span>
              </EmptyState>
            </div>
          ) : (
            <>
              <ul className="divide-y divide-rule">
                {state.items.map((contest) => (
                  <li key={contest.contest_id}>
                    <label
                      className={`flex w-full cursor-pointer items-start gap-3 px-4 py-3 ${
                        selected === contest.contest_id ? "bg-paper" : "hover:bg-paper/60"
                      }`}
                    >
                      <input
                        type="radio"
                        name="contest-picker-selection"
                        data-testid={`contest-picker-row-${contest.contest_id}`}
                        checked={selected === contest.contest_id}
                        onChange={() => setSelected(contest.contest_id)}
                        className="mt-1 shrink-0 accent-ink"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13.5px] font-medium">{contest.title}</span>
                        <span className="mt-0.5 block text-[11.5px] text-ink/45">
                          {formatPickerDate(contest.deadline_at)} 마감 · 요구사항 {contest.requirement_count}개
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              {state.next !== null ? (
                <div className="border-t border-rule p-3">
                  <button
                    type="button"
                    data-testid="contest-picker-more"
                    disabled={state.loadingMore}
                    onClick={() => void loadMore()}
                    className={`${buttonClass("secondary", "sm")} w-full`}
                  >
                    {state.loadingMore ? "불러오는 중..." : "더 보기"}
                  </button>
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className="flex flex-col gap-2.5 border-t border-rule bg-paper p-4">
          <p className="text-[12px] leading-relaxed text-ink/60">
            <b className="font-medium text-ink">제목·설명·체크리스트는 공모전을 따라갑니다</b> — 개최자가 고치면
            함께 바뀌고, 여기서는 고칠 수 없습니다. 수업용 안내·채점 지침·채점 모델·받는 형식은 정할 수
            있습니다. 참여자는 낼 때마다 이 공모전에도 낼지 고릅니다.
          </p>
          {importError ? (
            <ErrorNote>
              <span data-testid="contest-picker-import-error">{importError}</span>
            </ErrorNote>
          ) : null}
          <div className="flex justify-end">
            <button
              type="button"
              data-testid="contest-picker-import-submit"
              disabled={selected === null || importing}
              onClick={() => void handleImport()}
              className={buttonClass("primary")}
            >
              {importing ? "들여오는 중..." : "이 공모전 들여오기"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
