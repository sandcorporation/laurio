// 공개 표면의 현관(#93, spec #92). FE-02(#27)가 토큰 배선을 증명하려고 세운
// 자리표시 페이지였고, 그 주석은 "실제 공개 표면은 FE-04(#29)가 이 자리를
// 대신한다"고 적어 뒀었다 — 하지만 #29 는 `/contests` 를 새로 만들었을 뿐 이
// 자리는 그대로 남겨졌다. 이 페이지가 그 약속을 늦게라도 지킨다.
//
// **큐레이션(진행중·마감임박·심사중·완료 네 묶음)은 다음 티켓의 몫이다**(#94,
// spec #92). 여기서는 `/contests` 가 이미 쓰는 것과 같은 공개 목록 데이터를
// 그대로 보여준다 — 중요한 것은 "보인다"가 아니라 "걸어서 닿는다"다. 헤더의
// 「공모전」 링크가 필터·정렬·페이지가 있는 전체 목록으로 안내한다.
//
// 서버 컴포넌트다. 클라이언트 지시어가 붙으면 안 된다(ADR-0015) — 이 페이지는
// 색인 대상 공개 표면이다.
// **이 페이지는 요청 시점에 렌더된다.** Next 는 기본적으로 이 라우트를 정적
// 프리렌더하려 하고, 그러면 `pnpm build` 중에 백엔드를 치다가 ECONNREFUSED 로
// **빌드가 통째로 실패한다**(`Export encountered an error on /page: /`). 빌드
// 시점에는 백엔드가 없다 — 프로덕션 이미지는 컨테이너 밖에서 혼자 구워진다.
//
// `cache: "no-store"` 만으로는 부족했다. 명시적으로 표시한다.
export const dynamic = "force-dynamic";

import Link from "next/link";

import { fetchContests, type Contest } from "@/lib/api/contests";
import { formatDday, formatPrize, isImminent } from "@/lib/contest-format";

// 큐레이션이 없는 이 티켓 범위에서는 첫 화면에 너무 많은 행을 쏟아붓지 않는다
// — 전체는 「공모전」 링크가 있는 `/contests` 의 몫이다.
const HOME_CONTEST_LIMIT = 12;

export default async function Home() {
  const page = await fetchContests({ page: 1 });
  const contests = page.items.slice(0, HOME_CONTEST_LIMIT);

  return (
    <main className="flex min-h-screen flex-col gap-8 bg-paper p-10 text-ink">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">Laurio</h1>
        <p className="text-sm text-ink/70">
          발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 만들어 제출하는 공개 공모전
          플랫폼입니다.
        </p>
      </header>

      <section className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-2">
          <h2 className="text-lg font-semibold">공모전</h2>
          <Link href="/contests" data-testid="home-view-all-contests" className="text-sm text-ink/60 hover:text-ink">
            전체 보기
          </Link>
        </div>

        {contests.length === 0 ? (
          <p data-testid="home-contests-empty" className="py-10 text-center text-sm text-ink/60">
            아직 공개된 공모전이 없습니다.
          </p>
        ) : (
          <ul data-testid="home-contest-list" className="flex flex-col">
            {contests.map((contest) => (
              <HomeContestRow key={contest.id} contest={contest} />
            ))}
          </ul>
        )}

        {/* 「상금미달」이 참가를 막지 않는다는 도메인 규칙은 /contests(app/contests/page.tsx)와
            같은 문구로 반복한다 — 액센트 색만으로는 이 규칙이 안 읽힌다. 홈은 하필 그
            규칙을 가장 모를 첫 방문자가 보는 화면이라, 여기서 빠지면 안 된다. */}
        <p className="flex items-start gap-2 border-t border-rule pt-4 text-xs leading-relaxed text-ink/60">
          <span aria-hidden="true">ⓘ</span>
          <span>
            「상금미달」은 참가를 막지 않습니다. 선택한 요구형태의 최소 제안 상금 합계에 못
            미친다는 표시일 뿐이며, 판단은 개발자의 몫입니다.
          </span>
        </p>
      </section>
    </main>
  );
}

function HomeContestRow({ contest }: { contest: Contest }) {
  const imminent = isImminent(contest.deadline_at);

  return (
    <li>
      <Link
        href={`/contests/${contest.id}`}
        data-contest-row={contest.id}
        className="grid grid-cols-[minmax(0,1fr)_150px_88px] items-center gap-6 border-b border-rule px-1 py-4 hover:bg-surface"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[15px] font-medium">{contest.title}</span>
            {contest.is_underfunded && <UnderfundedBadge />}
          </div>
          <span className="text-xs text-ink/60">{contest.category.name}</span>
        </div>
        <div
          className={`text-right font-mono text-sm font-medium ${contest.is_underfunded ? "text-attention" : ""}`}
        >
          {formatPrize(contest.prize)}
        </div>
        <div
          className={`text-right font-mono text-sm ${imminent ? "font-semibold text-attention" : "text-ink/70"}`}
        >
          {formatDday(contest.deadline_at)}
        </div>
      </Link>
    </li>
  );
}

function UnderfundedBadge() {
  return (
    <span className="inline-flex items-center gap-1 border border-attention px-1.5 py-0.5 text-[10.5px] font-medium text-attention">
      상금미달
    </span>
  );
}
