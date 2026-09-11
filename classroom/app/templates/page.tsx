"use client";

// 공개된 템플릿 목록 (#318) — 제목 검색과 최신순뿐이다. 분류 체계는 만들지
// 않는다(#312 Implementation Decisions) — 아무도 안 고르는 목록이 쌓여
// 정작 필요한 것이 묻히는 것을 공모전 카테고리에서 이미 겪었다.
import Link from "next/link";
import { useState } from "react";

import { Card, EmptyState, ErrorNote, FieldLabel, INPUT_CLASS, Num, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import { useProblemTemplates } from "@/lib/problem-templates/use-problem-templates";

export default function ProblemTemplatesPage() {
  const [query, setQuery] = useState("");
  const [committedQuery, setCommittedQuery] = useState("");
  const { state, loadMore } = useProblemTemplates(committedQuery);

  return (
    <PageShell>
      <PageHeader
        eyebrow="강의실 · 템플릿"
        title="공개된 템플릿"
        titleTestId="problem-templates-heading"
        description="다른 강사가 공개한 문제를 찾아 내 클래스로 가져올 수 있습니다."
        actions={
          <Link
            href="/templates/mine"
            data-testid="my-problem-templates-link"
            className={buttonClass("secondary")}
          >
            내가 올린 템플릿
          </Link>
        }
      />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setCommittedQuery(query.trim());
        }}
        className="mb-5 flex flex-wrap items-end gap-2.5"
      >
        <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
          <label htmlFor="template-search-input">
            <FieldLabel>제목 검색</FieldLabel>
          </label>
          <input
            id="template-search-input"
            data-testid="template-search-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="문제 제목으로 찾기"
            className={INPUT_CLASS}
          />
        </div>
        <button type="submit" data-testid="template-search-submit" className={buttonClass("primary")}>
          검색
        </button>
      </form>

      {state.status === "loading" ? (
        <p data-testid="problem-templates-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      ) : state.status === "error" ? (
        <ErrorNote>
          <span data-testid="problem-templates-error">템플릿 목록을 불러오지 못했습니다.</span>
        </ErrorNote>
      ) : state.items.length === 0 ? (
        <Card>
          <EmptyState>
            <span data-testid="problem-templates-empty-state">
              {committedQuery
                ? "검색 결과가 없습니다. 다른 제목으로 찾아보세요."
                : "아직 공개된 템플릿이 없습니다. 문제 편집 화면에서 첫 템플릿을 공개해보세요."}
            </span>
          </EmptyState>
        </Card>
      ) : (
        <>
          <Card>
            <ul data-testid="problem-templates-list" className="divide-y divide-rule">
              {state.items.map((item) => (
                <li
                  key={item.share_code}
                  data-testid={`problem-template-row-${item.share_code}`}
                  className="flex flex-wrap items-center justify-between gap-3 px-4 py-4"
                >
                  <div className="min-w-0">
                    <Link
                      href={`/templates/${item.share_code}`}
                      data-testid={`problem-template-row-${item.share_code}-link`}
                      className="text-[15px] font-medium text-ink hover:underline"
                    >
                      {item.title}
                    </Link>
                    <div className="mt-1 text-[12px] text-ink/45">
                      {item.publisher_display_name} ·{" "}
                      <Num>{new Date(item.created_at).toLocaleDateString("ko-KR")}</Num> 공개
                    </div>
                  </div>
                  <Link href={`/templates/${item.share_code}`} className={buttonClass("secondary", "sm")}>
                    미리보기
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          {state.hasMore ? (
            <div className="mt-4">
              <button
                type="button"
                data-testid="problem-templates-load-more"
                onClick={loadMore}
                className={buttonClass("secondary")}
              >
                더 보기
              </button>
            </div>
          ) : null}
        </>
      )}
    </PageShell>
  );
}
