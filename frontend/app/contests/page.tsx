// FE-04(#29) — 공개 SSR 공모전 목록. `GET /api/contests` 는 auth=None 공개 표면이다
// (ADR-0015) — 서버 컴포넌트가 백엔드에 직접 붙어 렌더링하고, 브라우저는 다시
// 요청하지 않는다. 이 페이지는 클라이언트 컴포넌트 지시어를 붙이지 않는다 — 붙이는
// 순간 이 인수조건이 조용히 깨진다(frontend/e2e/seam.spec.ts 상단 주석, ADR-0015
// Consequences).
//
// 필터·정렬·페이지는 **백엔드가 처리한다**(#39). 이 서버 컴포넌트는 URL 의
// searchParams 를 그대로 쿼리로 넘기고, 돌아온 한 페이지를 그린다 — 예전처럼
// 전체를 받아와 여기서 거르지 않는다. 그 방식은 공개 Contest 가 한 번에 받아올
// 수 있는 수를 넘는 순간 뒤쪽이 목록에서 **조용히 사라졌다**(예외도 빈 화면도
// 아니다). 링크 클릭은 여전히 전부 진짜 내비게이션이라 "서버가 렌더링한다"는
// 인수조건은 그대로다.
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { ContestCard, ContestCardGrid } from "@/app/components/contest-card";
import { EmptyState, PageHeader } from "@/app/components/ui";
import { buttonClass } from "@/lib/ui/classnames";
import {
  CONTESTS_PAGE_SIZE,
  fetchContestCategories,
  fetchContests,
  fetchDeliverableTypes,
  type Category,
  type Contest,
  type ContestSort,
  type DeliverableType,
} from "@/lib/api/contests";

// canonical(#394) — 필터·정렬·페이지 쿼리가 무엇이든 이 경로 하나로
// 정식 주소를 고정한다. 쿼리별로 따로 색인되지 않게 하기 위해서다.
export const metadata: Metadata = { title: "공모전", alternates: { canonical: "/contests" } };

type SearchParams = { [key: string]: string | string[] | undefined };

type Current = {
  /** 헤더 검색창·손으로 친 `?q=`(#449). 빈 문자열은 "검색 없음"과 같다. */
  q?: string;
  category?: number;
  deliverableType?: number;
  // `undefined`는 "사용자가 정렬을 명시하지 않았다"다 — 백엔드가 `q` 유무로
  // 기본값(관련도순/마감임박순)을 고른다(#449). `buildHref`/`fetchContests`
  // 양쪽 다 이 구분을 그대로 살려 보낸다.
  sort?: ContestSort;
  // #227 — 기본은 지금 참가할 수 있는 것만(false), 켜면(true) 마감된 것만.
  closed: boolean;
  page: number;
};

function parseId(value: string | string[] | undefined): number | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw) return undefined;
  const parsed = Number(raw);
  // 손으로 친 URL 이 오류 화면이 되면 안 된다 — 숫자가 아니면 "필터 없음"으로
  // 떨어진다(#39: 알 수 없는 값은 500 이 아니라 안전한 기본값). 정수만 통과시켜야
  // `?category=1.5` 가 백엔드에서 422 가 되는 일도 막힌다.
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

// `undefined`를 돌려주는 값이 있다는 것이 핵심이다 — "명시하지 않았다"를 백엔드가
// `q` 유무로 기본값을 고르게 그대로 넘긴다(#449). 알 수 없는 값도 같은 "명시하지
// 않음"으로 떨어진다(#39 관용구 — 안전한 기본값).
//
// **`relevance`는 검색어가 있을 때만 뜻이 있다**(#452) — 검색어 없이 손으로
// `?sort=relevance`를 쳐도 이 함수는 그 값을 그대로 통과시킨다. 뒤에서
// `effectiveSort`가 "명시했지만 q가 없다"를 다시 "마감임박순"으로 접지는
// 않는다 — `fetchContests`가 그 값을 그대로 백엔드로 넘기면, 백엔드
// (`contests.api.list_contests`)가 "검색어 없이 관련도순을 요청하면 조용히
// 마감임박순으로 대신한다"는 같은 규칙을 이미 한 번 더 지킨다(중복이 아니라
// 방어선이 두 겹인 것 — #39 관용구, 단일 집행자를 벗어나지 않는다).
function parseSort(value: string | string[] | undefined): ContestSort | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw === "prize" || raw === "deadline" || raw === "relevance") return raw;
  return undefined;
}

// 빈 문자열은 검색 없음과 같다 — `?q=` 로 손으로 지운 링크가 "검색어 빈칸"으로
// 남지 않게 한다.
function parseQ(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed ? trimmed : undefined;
}

// 손으로 친 값이 뭐든 "꺼짐"이 안전한 기본값이다(#39 관용구를 그대로 따른다) —
// `?closed=` 든 `?closed=nonsense` 든 "참가 가능한 것만"으로 떨어진다.
//
// **켜는 값은 `"1"` 과 `"true"` 둘 다다.** 링크(아래 buildHref)는 항상 `"1"` 로
// 켜지만, 백엔드의 같은 파라미터는 `closed=true` 를 받는다(django-ninja 의 bool
// 파싱) — 화면만 그것을 모르면 사람이 API 를 보고 손으로 친 URL 이나 공유된 링크가
// **오류도 없이 엉뚱한 목록**을 보여준다. 실제로 #227 의 e2e 가 `?closed=true` 로
// 걸어 CI 에서 그렇게 걸렸다. 「알 수 없는 값은 안전한 기본값으로」는 그대로다 —
// 아는 값의 목록만 백엔드와 맞춘다.
function parseClosed(value: string | string[] | undefined): boolean {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "1" || raw === "true";
}

function parsePage(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

// 현재 상태를 유지한 채 일부만 바꾼 링크를 만든다. `undefined` 를 주면 그
// 파라미터를 지운다(토글) — "전체" 필터, 같은 정렬을 다시 누르는 경우.
//
// **필터나 정렬을 바꾸면 페이지는 1 로 되돌린다.** 3페이지에서 카테고리를 좁히면
// 결과가 1페이지밖에 없을 수 있고, 그때 3페이지에 그대로 남으면 "조건에 맞는
// 공모전이 없습니다" 가 뜬다 — 실제로는 있는데 없다고 말하는 화면이다.
function buildHref(current: Current, overrides: Partial<Current>): string {
  const resetsPage =
    "q" in overrides ||
    "category" in overrides ||
    "deliverableType" in overrides ||
    "sort" in overrides ||
    "closed" in overrides;
  const next = { ...current, ...(resetsPage ? { page: 1 } : {}), ...overrides };

  const params = new URLSearchParams();
  if (next.q !== undefined) params.set("q", next.q);
  if (next.category !== undefined) params.set("category", String(next.category));
  if (next.deliverableType !== undefined)
    params.set("deliverableType", String(next.deliverableType));
  if (next.sort !== undefined) params.set("sort", next.sort);
  if (next.closed) params.set("closed", "1");
  if (next.page > 1) params.set("page", String(next.page));

  const qs = params.toString();
  return qs ? `/contests?${qs}` : "/contests";
}

export default async function ContestsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const current: Current = {
    q: parseQ(sp.q),
    category: parseId(sp.category),
    deliverableType: parseId(sp.deliverableType),
    sort: parseSort(sp.sort),
    closed: parseClosed(sp.closed),
    page: parsePage(sp.page),
  };
  // 화면 표시(도구 막대의 정렬 `<select>`가 실제로 적용된 값을 선택된 채로
  // 보여주는 데)용 — 백엔드에 실제로 보내는 `current.sort`는 `undefined`로
  // 그대로 둔다("명시하지 않음"을 백엔드가 판단하게 넘긴다, #449).
  const effectiveSort: ContestSort = current.sort ?? (current.q ? "relevance" : "deadline");

  const [page, categories, deliverableTypes] = await Promise.all([
    fetchContests(current),
    fetchContestCategories(),
    fetchDeliverableTypes(),
  ]);

  // 범위를 벗어난 page 는 마지막 페이지로 정정한다. 그냥 두면 「전체 30」이라고
  // 써놓고 바로 아래에 "조건에 맞는 공모전이 없습니다" 가 뜬다 — 있는데 없다고
  // 말하는 화면이고, 범위 표시도 `19999961 – 30 / 30` 처럼 깨진다(직접 확인했다).
  // URL 까지 정정하려고 redirect 를 쓴다 — 그래야 공유된 링크가 다음에도 같은
  // 화면을 연다. 정정된 page 는 항상 totalPages 이하라 이 분기가 다시 걸리지
  // 않는다(재귀 없음).
  if (current.page > page.totalPages) {
    redirect(buildHref(current, { page: page.totalPages }));
  }

  return (
    // PageShell(공용 조각, app/components/ui.tsx)은 폭을 max-w-3xl(768px)로
    // 고정한다 — 이 화면의 표는 열이 넷(공모전·요구형태·상금·마감)이라 그
    // 폭에서는 공모전 열이 200px 아래로 눌려 제목이 대부분 잘린다. 대신 헤더
    // (site-header.tsx)와 같은 폭(1200px)을 직접 준다 — PageHeader 는 그대로
    // 공용 조각을 쓴다.
    <main className="mx-auto flex w-full max-w-[1200px] flex-col gap-8 px-6 py-10">
      <PageHeader
        title="공모전"
        description={
          current.q
            ? `"${current.q}" 검색 결과입니다.`
            : current.closed
              ? "마감된 공모전 목록입니다. 데모·영상은 공개돼 있지만 더 이상 참가할 수 없습니다."
              : "발주자가 상금을 걸고 요구사항을 공개한, 지금 참가할 수 있는 공모전 목록입니다. 로그인 없이 볼 수 있습니다."
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule pb-4">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-semibold">전체</span>
          {/* 이 페이지에 실린 개수가 아니라 **필터가 걸린 전체 건수**다. 페이지를
              넘겨도 이 숫자는 그대로여야 한다. */}
          <span data-testid="contest-count" className="font-mono text-sm text-ink/60">
            {page.count}
          </span>
        </div>

        <ContestsToolbar
          current={current}
          effectiveSort={effectiveSort}
          categories={categories}
          deliverableTypes={deliverableTypes}
        />
      </div>

      {current.q && (
        // 걸린 검색어 칩(#452 인수조건) — 지우면 나머지 필터(카테고리·요구형태·
        // 상태·정렬)는 그대로 URL 에 남는다. `buildHref`가 `q`만 빼고 다시 조립한다.
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink/60">
          <span>검색어</span>
          <Link
            href={buildHref(current, { q: undefined })}
            data-testid="contests-search-chip"
            className="inline-flex items-center gap-1.5 border border-rule bg-surface px-2 py-1 text-ink hover:border-ink"
          >
            {current.q}
            <span aria-hidden="true">✕</span>
            <span className="sr-only">검색어 지우기</span>
          </Link>
        </div>
      )}

      <ContestGrid contests={page.items} />

      <Pagination current={current} page={page} />

      <p className="flex items-start gap-2 border-t border-rule pt-4 text-xs leading-relaxed text-ink/60">
        <span aria-hidden="true">ⓘ</span>
        <span>
          「상금미달」은 참가를 막지 않습니다. 선택한 요구형태의 최소 제안 상금 합계에 못
          미친다는 표시일 뿐이며, 판단은 개발자의 몫입니다.
        </span>
      </p>
    </main>
  );
}

function Pagination({
  current,
  page,
}: {
  current: Current;
  page: { count: number; page: number; totalPages: number };
}) {
  // 한 페이지에 다 들어가면 아무것도 그리지 않는다 — 지금까지의 화면 그대로다.
  if (page.totalPages <= 1) return null;

  const first = (page.page - 1) * CONTESTS_PAGE_SIZE + 1;
  const last = Math.min(page.page * CONTESTS_PAGE_SIZE, page.count);

  return (
    <nav
      aria-label="페이지"
      data-testid="contest-pagination"
      className="flex items-center justify-between border-t border-rule pt-4 text-sm"
    >
      <span className="font-mono text-xs text-ink/60">
        {first}–{last} / {page.count}
      </span>
      <span className="flex items-center gap-4">
        {page.page > 1 ? (
          <Link data-testid="page-prev" href={buildHref(current, { page: page.page - 1 })}>
            이전
          </Link>
        ) : (
          <span className="text-ink/30">이전</span>
        )}
        <span className="font-mono text-xs text-ink/60">
          {page.page} / {page.totalPages}
        </span>
        {page.page < page.totalPages ? (
          <Link data-testid="page-next" href={buildHref(current, { page: page.page + 1 })}>
            다음
          </Link>
        ) : (
          <span className="text-ink/30">다음</span>
        )}
      </span>
    </nav>
  );
}

// 한 줄 도구 막대(#452, spec #444) — 예전의 세 줄(참가 가능 여부 토글·카테고리
// 칩 줄·요구형태 칩 줄)을 걷어내고, 상태 토글·카테고리·요구형태·정렬을 한
// 자리로 모았다. 카테고리·요구형태가 칩 목록이 아니라 `<select>`인 이유는
// spec #444 Problem Statement 그대로다 — "카테고리·요구형태가 늘면 더
// 길어진다"는 칩 방식의 실패를 되풀이하지 않는다(개수가 늘어도 한 줄 폭은
// 그대로다).
//
// **자바스크립트 없이도 동작한다**(#452 인수조건) — `<select>`는 `onChange`
// 자동 제출 대신 평범한 `<form method="get">`과 제출 버튼을 쓴다. 상태
// 토글만은 값이 둘뿐이라 여전히 두 `<Link>`다(누르면 그 자리에서 바로
// 이동한다 — 폼도 제출 버튼도 필요 없다).
//
// **넓은 화면은 항상 펼쳐져 있고, 좁은 화면은 「필터」 버튼 뒤에 접힌다** —
// `header-search.tsx`의 헤더 검색창과 같은 `<details>`/`<summary>` 관용구다
// (`useState`로 만든 접이식은 자바스크립트 없이는 항상 닫힌 채로 보인다).
function ContestsToolbar({
  current,
  effectiveSort,
  categories,
  deliverableTypes,
}: {
  current: Current;
  effectiveSort: ContestSort;
  categories: Category[];
  deliverableTypes: DeliverableType[];
}) {
  const activeCount =
    (current.category !== undefined ? 1 : 0) +
    (current.deliverableType !== undefined ? 1 : 0) +
    (current.closed ? 1 : 0) +
    (current.sort !== undefined ? 1 : 0);

  return (
    <>
      <div className="hidden flex-wrap items-center gap-2 sm:flex">
        <FilterFields
          current={current}
          effectiveSort={effectiveSort}
          categories={categories}
          deliverableTypes={deliverableTypes}
        />
      </div>

      <details className="sm:hidden">
        <summary
          data-testid="contests-filter-toggle"
          className={`${buttonClass("secondary", "sm")} cursor-pointer list-none [&::-webkit-details-marker]:hidden`}
        >
          필터{activeCount > 0 ? ` · ${activeCount}` : ""}
        </summary>
        <div className="mt-3 flex flex-col items-start gap-2">
          <FilterFields
            current={current}
            effectiveSort={effectiveSort}
            categories={categories}
            deliverableTypes={deliverableTypes}
          />
        </div>
      </details>
    </>
  );
}

const SELECT_CLASS =
  "border border-rule bg-surface px-2 py-1.5 text-xs text-ink focus:border-ink focus:outline-none";

// 상태 토글·카테고리·요구형태·정렬 — 넓은 화면 줄과 접힌 모바일 패널이 같은
// 필드를 그대로 두 벌 렌더링한다(header-search.tsx와 같은 방식) — 한쪽은
// `hidden`으로 화면에서만 빠지고 둘 다 DOM 에 남지만, 서로 **다른 `<form>`
// 이라 이름이 겹쳐도 제출은 클릭한 쪽 하나만 일어난다**.
function FilterFields({
  current,
  effectiveSort,
  categories,
  deliverableTypes,
}: {
  current: Current;
  effectiveSort: ContestSort;
  categories: Category[];
  deliverableTypes: DeliverableType[];
}) {
  return (
    <>
      <div className="inline-flex border border-rule" role="group" aria-label="참가 가능 여부로 좁히기">
        <Link
          href={buildHref(current, { closed: false })}
          aria-current={!current.closed ? "true" : undefined}
          data-testid="contests-filter-open"
          className={`px-3 py-1.5 text-xs ${!current.closed ? "bg-ink text-paper" : "text-ink/60 hover:bg-paper"}`}
        >
          참가 가능한 것
        </Link>
        <Link
          href={buildHref(current, { closed: true })}
          aria-current={current.closed ? "true" : undefined}
          data-testid="contests-filter-closed"
          className={`border-l border-rule px-3 py-1.5 text-xs ${current.closed ? "bg-ink text-paper" : "text-ink/60 hover:bg-paper"}`}
        >
          마감된 것
        </Link>
      </div>

      {/* `q`·`closed`는 이 폼이 편집하는 필드가 아니다 — 숨은 입력으로 그대로
          실어 날라야, 카테고리만 바꿔도 걸려 있던 검색어·상태가 사라지지
          않는다. 페이지는 일부러 안 싣는다 — 필터를 바꾸면 1페이지로
          되돌아가야 한다(#39 관용구, 기존 buildHref와 같은 규칙). */}
      <form method="get" action="/contests" className="flex flex-wrap items-center gap-2">
        {current.q && <input type="hidden" name="q" value={current.q} />}
        {current.closed && <input type="hidden" name="closed" value="1" />}
        <select
          name="category"
          defaultValue={current.category ?? ""}
          aria-label="카테고리로 좁히기"
          className={SELECT_CLASS}
        >
          <option value="">카테고리 전체</option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
        <select
          name="deliverableType"
          defaultValue={current.deliverableType ?? ""}
          aria-label="요구형태로 좁히기"
          className={SELECT_CLASS}
        >
          <option value="">모든 요구형태</option>
          {deliverableTypes.map((deliverableType) => (
            <option key={deliverableType.id} value={deliverableType.id}>
              {deliverableType.name}
            </option>
          ))}
        </select>
        {/* `defaultValue`는 **명시한** `current.sort`가 아니라 `effectiveSort`다
            — 검색어가 있고 정렬을 명시하지 않았을 때 실제로 적용되는 정렬은
            관련도순인데(#449), 셀렉트가 그 사실을 숨기고 "마감 임박순"이
            선택된 것처럼 보이면 사용자가 다시 고르기 전까지 화면과 실제
            정렬이 어긋난다. 제출할 값도 언제나 이 셋 중 하나로 명시적이라
            "명시하지 않음"이 URL에 다시 숨어들지 않는다(#452 인수조건 —
            모든 조합이 URL로 재현된다). */}
        <select name="sort" defaultValue={effectiveSort} aria-label="정렬" className={SELECT_CLASS}>
          {/* #227 — deadline 정렬의 방향이 closed 축에 따라 뒤집힌다(참가 가능은
              마감임박순 오름차순, 마감된 것은 최근 마감순 내림차순). 라벨이
              그 방향을 그대로 옮긴다 — #227이 고치는 버그를 여기서 재현하지
              않는다. */}
          <option value="deadline">{current.closed ? "최근 마감순" : "마감 임박순"}</option>
          <option value="prize">상금순</option>
          {/* 검색어가 없으면 관련도순 선택지 자체가 없다(#452 인수조건) —
              개념이 성립하지 않는 정렬을 목록에 두지 않는다. */}
          {current.q && <option value="relevance">관련도순</option>}
        </select>
        <button type="submit" data-testid="contests-filter-apply" className={buttonClass("secondary", "sm")}>
          적용
        </button>
      </form>
    </>
  );
}

// 랜딩(app/page.tsx)과 같은 카드 조각을 쓴다(#448 인수조건) — 예전의 표 모양
// 줄·헤더 행(공모전/요구형태/상금/마감 네 칸)은 여기서 걷어냈다.
function ContestGrid({ contests }: { contests: Contest[] }) {
  if (contests.length === 0) {
    return <EmptyState>조건에 맞는 공모전이 없습니다.</EmptyState>;
  }

  return (
    <ContestCardGrid>
      {contests.map((contest) => (
        <ContestCard key={contest.id} contest={contest} />
      ))}
    </ContestCardGrid>
  );
}
