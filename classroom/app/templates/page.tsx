"use client";

// 공개된 템플릿 목록 (#318/#319) — 제목 검색과 최신순뿐이다. 분류 체계는 만들지
// 않는다(#312 Implementation Decisions) — 아무도 안 고르는 목록이 쌓여
// 정작 필요한 것이 묻히는 것을 공모전 카테고리에서 이미 겪었다.
//
// 「문제」·「클래스」 탭이 문제 하나짜리 템플릿과 클래스 통째 템플릿을
// 구별한다(#319 AC "목록에서 구별된다") — 서로 다른 목록 엔드포인트·상세
// 주소를 갖는 별개의 자원이라 한 목록에 섞지 않는다.
import Link from "next/link";
import { useState } from "react";

import { Card, EmptyState, ErrorNote, FieldLabel, INPUT_CLASS, Num, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import { useClassTemplates } from "@/lib/class-templates/use-class-templates";
import { useProblemTemplates } from "@/lib/problem-templates/use-problem-templates";

type Kind = "problem" | "class";

export default function TemplatesPage() {
  const [kind, setKind] = useState<Kind>("problem");
  const [query, setQuery] = useState("");
  const [committedQuery, setCommittedQuery] = useState("");

  const problemTemplates = useProblemTemplates(kind === "problem" ? committedQuery : "");
  const classTemplates = useClassTemplates(kind === "class" ? committedQuery : "");

  return (
    <PageShell>
      <PageHeader
        eyebrow="강의실 · 템플릿"
        title="공개된 템플릿"
        titleTestId="templates-heading"
        description="다른 강사가 공개한 문제나 클래스를 찾아 내 것으로 가져올 수 있습니다."
        actions={
          <Link
            href="/templates/mine"
            data-testid="my-templates-link"
            className={buttonClass("secondary")}
          >
            내가 올린 템플릿
          </Link>
        }
      />

      <div
        role="tablist"
        aria-label="템플릿 종류"
        className="mb-5 flex items-end gap-0.5 border-b border-rule"
      >
        {(
          [
            ["problem", "문제", "templates-tab-problem"],
            ["class", "클래스", "templates-tab-class"],
          ] as const
        ).map(([key, label, testId]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={kind === key}
            data-testid={testId}
            onClick={() => {
              setKind(key);
              setQuery("");
              setCommittedQuery("");
            }}
            className={
              kind === key
                ? "-mb-px border border-rule border-b-surface bg-surface px-4 py-2 text-[13.5px] font-medium"
                : "px-4 py-2 text-[13.5px] text-ink/60 hover:text-ink"
            }
          >
            {label}
          </button>
        ))}
      </div>

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
            placeholder={kind === "problem" ? "문제 제목으로 찾기" : "클래스 이름으로 찾기"}
            className={INPUT_CLASS}
          />
        </div>
        <button type="submit" data-testid="template-search-submit" className={buttonClass("primary")}>
          검색
        </button>
      </form>

      {kind === "problem" ? (
        <ProblemTemplatesList
          state={problemTemplates.state}
          loadMore={problemTemplates.loadMore}
          committedQuery={committedQuery}
        />
      ) : (
        <ClassTemplatesList
          state={classTemplates.state}
          loadMore={classTemplates.loadMore}
          committedQuery={committedQuery}
        />
      )}
    </PageShell>
  );
}

function ProblemTemplatesList({
  state,
  loadMore,
  committedQuery,
}: {
  state: ReturnType<typeof useProblemTemplates>["state"];
  loadMore: () => void;
  committedQuery: string;
}) {
  if (state.status === "loading") {
    return (
      <p data-testid="problem-templates-loading" className="text-[13.5px] text-ink/45">
        불러오는 중...
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <ErrorNote>
        <span data-testid="problem-templates-error">템플릿 목록을 불러오지 못했습니다.</span>
      </ErrorNote>
    );
  }
  if (state.items.length === 0) {
    return (
      <Card>
        <EmptyState>
          <span data-testid="problem-templates-empty-state">
            {committedQuery
              ? "검색 결과가 없습니다. 다른 제목으로 찾아보세요."
              : "아직 공개된 템플릿이 없습니다. 문제 편집 화면에서 첫 템플릿을 공개해보세요."}
          </span>
        </EmptyState>
      </Card>
    );
  }
  return (
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
  );
}

function ClassTemplatesList({
  state,
  loadMore,
  committedQuery,
}: {
  state: ReturnType<typeof useClassTemplates>["state"];
  loadMore: () => void;
  committedQuery: string;
}) {
  if (state.status === "loading") {
    return (
      <p data-testid="class-templates-loading" className="text-[13.5px] text-ink/45">
        불러오는 중...
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <ErrorNote>
        <span data-testid="class-templates-error">템플릿 목록을 불러오지 못했습니다.</span>
      </ErrorNote>
    );
  }
  if (state.items.length === 0) {
    return (
      <Card>
        <EmptyState>
          <span data-testid="class-templates-empty-state">
            {committedQuery
              ? "검색 결과가 없습니다. 다른 이름으로 찾아보세요."
              : "아직 공개된 클래스 템플릿이 없습니다. 클래스 상세 화면에서 첫 템플릿을 공개해보세요."}
          </span>
        </EmptyState>
      </Card>
    );
  }
  return (
    <>
      <Card>
        <ul data-testid="class-templates-list" className="divide-y divide-rule">
          {state.items.map((item) => (
            <li
              key={item.share_code}
              data-testid={`class-template-row-${item.share_code}`}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-4"
            >
              <div className="min-w-0">
                <Link
                  href={`/class-templates/${item.share_code}`}
                  data-testid={`class-template-row-${item.share_code}-link`}
                  className="text-[15px] font-medium text-ink hover:underline"
                >
                  {item.name}
                </Link>
                <div className="mt-1 text-[12px] text-ink/45">
                  {item.publisher_display_name} ·{" "}
                  <Num>{new Date(item.created_at).toLocaleDateString("ko-KR")}</Num> 공개
                </div>
              </div>
              <Link href={`/class-templates/${item.share_code}`} className={buttonClass("secondary", "sm")}>
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
            data-testid="class-templates-load-more"
            onClick={loadMore}
            className={buttonClass("secondary")}
          >
            더 보기
          </button>
        </div>
      ) : null}
    </>
  );
}
