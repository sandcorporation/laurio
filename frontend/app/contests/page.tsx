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
function parseSort(value: string | string[] | undefined): ContestSort | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw === "prize" || raw === "deadline") return raw;
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
  // 화면 표시(정렬 링크의 aria-current)용 — 백엔드에 실제로 보내는 `current.sort`는
  // `undefined`로 그대로 둔다("명시하지 않음"을 백엔드가 판단하게 넘긴다, #449).
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
        <nav aria-label="정렬" className="flex items-center gap-4 text-sm">
          <Link
            href={buildHref(current, { sort: "deadline" })}
            aria-current={effectiveSort === "deadline" ? "true" : undefined}
            className={effectiveSort === "deadline" ? "font-medium text-ink" : "text-ink/60"}
          >
            {/* #227 — deadline 정렬의 방향이 closed 축에 따라 뒤집힌다(참가 가능은
                마감임박순 오름차순, 마감된 것은 최근 마감순 내림차순 — 백엔드
                list_contests 독스트링과 같은 근거). 방향이 바뀌는데 라벨이
                그대로면 "마감임박순"이라 써놓고 실제로는 정반대로 동작한다 —
                #227이 고치는 바로 그 버그를 라벨에서 재현하지 않는다. */}
            {current.closed ? "최근 마감순" : "마감 임박순"}
          </Link>
          <Link
            href={buildHref(current, { sort: "prize" })}
            aria-current={effectiveSort === "prize" ? "true" : undefined}
            className={effectiveSort === "prize" ? "font-medium text-ink" : "text-ink/60"}
          >
            상금순
          </Link>
        </nav>
      </div>

      {/* #227 — 기본은 "참가 가능"만 보여준다. 마감된 것을 보는 길은 필터
          형태로 명시적으로 켜야 하고, 그 상태가 URL(`?closed=1`)에 남아
          새로고침·공유·뒤로가기에도 유지된다(buildHref가 다른 필터처럼 이
          값을 계속 실어 나른다). */}
      <nav aria-label="참가 가능 여부로 좁히기" className="flex flex-wrap gap-2">
        <Link
          href={buildHref(current, { closed: false })}
          aria-current={!current.closed ? "true" : undefined}
          data-testid="contests-filter-open"
          className={buttonClass(!current.closed ? "primary" : "secondary", "sm")}
        >
          참가 가능한 것
        </Link>
        <Link
          href={buildHref(current, { closed: true })}
          aria-current={current.closed ? "true" : undefined}
          data-testid="contests-filter-closed"
          className={buttonClass(current.closed ? "primary" : "secondary", "sm")}
        >
          마감된 것
        </Link>
      </nav>

      <CategoryFilter categories={categories} current={current} />
      <DeliverableTypeFilter deliverableTypes={deliverableTypes} current={current} />

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

function CategoryFilter({
  categories,
  current,
}: {
  categories: Category[];
  current: Current;
}) {
  return (
    <nav aria-label="카테고리로 좁히기" className="flex flex-wrap gap-2">
      <Link
        href={buildHref(current, { category: undefined })}
        aria-current={current.category === undefined ? "true" : undefined}
        className={buttonClass(current.category === undefined ? "primary" : "secondary", "sm")}
      >
        전체
      </Link>
      {categories.map((category) => (
        <Link
          key={category.id}
          href={buildHref(current, { category: category.id })}
          aria-current={current.category === category.id ? "true" : undefined}
          className={buttonClass(current.category === category.id ? "primary" : "secondary", "sm")}
        >
          {category.name}
        </Link>
      ))}
    </nav>
  );
}

function DeliverableTypeFilter({
  deliverableTypes,
  current,
}: {
  deliverableTypes: DeliverableType[];
  current: Current;
}) {
  return (
    <nav aria-label="요구형태로 좁히기" className="flex flex-wrap gap-2">
      <Link
        href={buildHref(current, { deliverableType: undefined })}
        aria-current={current.deliverableType === undefined ? "true" : undefined}
        className={buttonClass(current.deliverableType === undefined ? "primary" : "secondary", "sm")}
      >
        모든 요구형태
      </Link>
      {deliverableTypes.map((deliverableType) => (
        <Link
          key={deliverableType.id}
          href={buildHref(current, { deliverableType: deliverableType.id })}
          aria-current={current.deliverableType === deliverableType.id ? "true" : undefined}
          className={buttonClass(
            current.deliverableType === deliverableType.id ? "primary" : "secondary",
            "sm",
          )}
        >
          {deliverableType.name}
        </Link>
      ))}
    </nav>
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
