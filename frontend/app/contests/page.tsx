// FE-04(#29) — 공개 SSR 공모전 목록. `GET /api/contests` 는 auth=None 공개 표면이다
// (ADR-0015) — 서버 컴포넌트가 백엔드에 직접 붙어 렌더링하고, 브라우저는 다시
// 요청하지 않는다. 이 페이지는 클라이언트 컴포넌트 지시어를 붙이지 않는다 — 붙이는
// 순간 이 인수조건이 조용히 깨진다(frontend/e2e/seam.spec.ts 상단 주석, ADR-0015
// Consequences).
//
// 필터·정렬은 백엔드에 쿼리 파라미터가 없어(contests.api.list_contests 는 page만
// 받는다) URL 의 searchParams 를 서버 컴포넌트가 직접 읽어 전체 목록에서 좁히고
// 정렬한다 — 링크 클릭마다 Next 가 새 서버 렌더링을 하므로 "서버가 렌더링한다"는
// 요구사항은 그대로 지켜진다.
import Link from "next/link";

import {
  fetchContestCategories,
  fetchContests,
  fetchDeliverableTypes,
  type Category,
  type Contest,
  type DeliverableType,
} from "@/lib/api/contests";
import { formatDday, formatPrize, isImminent } from "@/lib/contest-format";

type SearchParams = { [key: string]: string | string[] | undefined };

type Sort = "deadline" | "prize";

function parseId(value: string | string[] | undefined): number | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseSort(value: string | string[] | undefined): Sort {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "prize" ? "prize" : "deadline";
}

// 현재 필터·정렬을 유지한 채 한 파라미터만 바꾼 링크를 만든다. `undefined` 를 주면
// 그 파라미터를 지운다(토글) — "전체" 필터, 같은 정렬을 다시 누르는 경우.
function buildHref(
  current: { category?: number; deliverableType?: number; sort: Sort },
  overrides: Partial<{ category: number | undefined; deliverableType: number | undefined; sort: Sort }>,
): string {
  const next = { ...current, ...overrides };
  const params = new URLSearchParams();
  if (next.category !== undefined) params.set("category", String(next.category));
  if (next.deliverableType !== undefined) params.set("deliverableType", String(next.deliverableType));
  if (next.sort !== "deadline") params.set("sort", next.sort);
  const qs = params.toString();
  return qs ? `/contests?${qs}` : "/contests";
}

export default async function ContestsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const categoryId = parseId(sp.category);
  const deliverableTypeId = parseId(sp.deliverableType);
  const sort = parseSort(sp.sort);

  const [contests, categories, deliverableTypes] = await Promise.all([
    fetchContests(),
    fetchContestCategories(),
    fetchDeliverableTypes(),
  ]);

  const filtered = contests.filter((contest) => {
    const matchesCategory = categoryId === undefined || contest.category.id === categoryId;
    const matchesDeliverable =
      deliverableTypeId === undefined ||
      contest.deliverable_types.some((dt) => dt.id === deliverableTypeId);
    return matchesCategory && matchesDeliverable;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sort === "prize") return b.prize - a.prize;
    return new Date(a.deadline_at).getTime() - new Date(b.deadline_at).getTime();
  });

  const current = { category: categoryId, deliverableType: deliverableTypeId, sort };

  return (
    <main className="flex min-h-screen flex-col gap-8 bg-paper p-10 text-ink">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">공모전</h1>
        <p className="text-sm text-ink/70">
          발주자가 상금을 걸고 요구사항을 공개한 공모전 목록입니다. 로그인 없이 볼 수 있습니다.
        </p>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule pb-4">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-semibold">전체</span>
          <span className="font-mono text-sm text-ink/60">{sorted.length}</span>
        </div>
        <nav aria-label="정렬" className="flex items-center gap-4 text-sm">
          <Link
            href={buildHref(current, { sort: "deadline" })}
            aria-current={sort === "deadline" ? "true" : undefined}
            className={sort === "deadline" ? "font-medium text-ink" : "text-ink/60"}
          >
            마감 임박순
          </Link>
          <Link
            href={buildHref(current, { sort: "prize" })}
            aria-current={sort === "prize" ? "true" : undefined}
            className={sort === "prize" ? "font-medium text-ink" : "text-ink/60"}
          >
            상금순
          </Link>
        </nav>
      </div>

      <CategoryFilter categories={categories} current={current} />
      <DeliverableTypeFilter deliverableTypes={deliverableTypes} current={current} />

      <ContestTable contests={sorted} />

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

function CategoryFilter({
  categories,
  current,
}: {
  categories: Category[];
  current: { category?: number; deliverableType?: number; sort: Sort };
}) {
  return (
    <nav aria-label="카테고리로 좁히기" className="flex flex-wrap gap-2">
      <Link
        href={buildHref(current, { category: undefined })}
        aria-current={current.category === undefined ? "true" : undefined}
        className={
          current.category === undefined
            ? "border border-ink bg-ink px-3 py-1.5 text-sm text-paper"
            : "border border-rule px-3 py-1.5 text-sm text-ink/70"
        }
      >
        전체
      </Link>
      {categories.map((category) => (
        <Link
          key={category.id}
          href={buildHref(current, { category: category.id })}
          aria-current={current.category === category.id ? "true" : undefined}
          className={
            current.category === category.id
              ? "border border-ink bg-ink px-3 py-1.5 text-sm text-paper"
              : "border border-rule px-3 py-1.5 text-sm text-ink/70"
          }
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
  current: { category?: number; deliverableType?: number; sort: Sort };
}) {
  return (
    <nav aria-label="요구형태로 좁히기" className="flex flex-wrap gap-2">
      <Link
        href={buildHref(current, { deliverableType: undefined })}
        aria-current={current.deliverableType === undefined ? "true" : undefined}
        className={
          current.deliverableType === undefined
            ? "border border-ink px-3 py-1.5 text-sm font-medium text-ink"
            : "border border-rule px-3 py-1.5 text-sm text-ink/70"
        }
      >
        모든 요구형태
      </Link>
      {deliverableTypes.map((deliverableType) => (
        <Link
          key={deliverableType.id}
          href={buildHref(current, { deliverableType: deliverableType.id })}
          aria-current={current.deliverableType === deliverableType.id ? "true" : undefined}
          className={
            current.deliverableType === deliverableType.id
              ? "border border-ink px-3 py-1.5 text-sm font-medium text-ink"
              : "border border-rule px-3 py-1.5 text-sm text-ink/70"
          }
        >
          {deliverableType.name}
        </Link>
      ))}
    </nav>
  );
}

function ContestTable({ contests }: { contests: Contest[] }) {
  if (contests.length === 0) {
    return <p className="py-10 text-center text-sm text-ink/60">조건에 맞는 공모전이 없습니다.</p>;
  }

  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-[minmax(0,1fr)_210px_150px_88px] gap-6 border-b border-ink px-1 pb-2.5 text-[11px] font-medium tracking-wide text-ink/60">
        <div>공모전</div>
        <div>요구형태</div>
        <div className="text-right">상금</div>
        <div className="text-right">마감</div>
      </div>
      {contests.map((contest) => (
        <ContestRow key={contest.id} contest={contest} />
      ))}
    </div>
  );
}

function ContestRow({ contest }: { contest: Contest }) {
  const imminent = isImminent(contest.deadline_at);

  return (
    <Link
      href={`/contests/${contest.id}`}
      data-contest-row={contest.id}
      className="grid grid-cols-[minmax(0,1fr)_210px_150px_88px] items-center gap-6 border-b border-rule px-1 py-5 hover:bg-surface"
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <span className="truncate text-[15.5px] font-medium">{contest.title}</span>
          {contest.is_underfunded && <UnderfundedBadge />}
          {contest.status === "closed" && (
            <span className="border border-rule px-1.5 py-0.5 text-[11px] text-ink/60">마감</span>
          )}
        </div>
        <div className="text-xs text-ink/60">
          {contest.category.name}
          {contest.is_underfunded && (
            <> · 최소 제안 {formatPrize(contest.required_minimum_prize)}원</>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 text-[11.5px] text-ink/70">
        {contest.deliverable_types.map((dt) => (
          <span key={dt.id} className="border border-rule px-1.5 py-0.5">
            {dt.name}
          </span>
        ))}
      </div>
      <div
        className={`text-right font-mono text-base font-medium ${contest.is_underfunded ? "text-attention" : ""}`}
      >
        {formatPrize(contest.prize)}
      </div>
      <div
        data-testid="deadline"
        className={`text-right font-mono text-sm ${imminent ? "font-semibold text-attention" : "text-ink/70"}`}
      >
        {formatDday(contest.deadline_at)}
      </div>
    </Link>
  );
}

function UnderfundedBadge() {
  return (
    <span className="inline-flex items-center gap-1 border border-attention px-1.5 py-0.5 text-[10.5px] font-medium text-attention">
      상금미달
    </span>
  );
}
