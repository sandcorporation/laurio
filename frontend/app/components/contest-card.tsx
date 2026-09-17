// 공모전 가로형 카드(#448, spec #444) — 랜딩 네 묶음과 `/contests`가 공유하는 서버
// 컴포넌트 조각이다. 시안은 2026-09-17 대화의 「C. 가로형 카드」이고, 조회수와
// 개최자 표시 이름을 더했다. 클라이언트 지시어를 붙이지 않는다 — 공개 표면의
// 서버 렌더링(ADR-0015)을 이 카드가 쓰이는 두 화면(랜딩·`/contests`)이 그대로
// 물려받는다.
//
// 색은 이 브랜드의 여섯 토큰(ink·paper·surface·rule·attention·verified)만
// 쓴다(brand-guard, `lib/ui/brand-guard.test.ts`) — 리터럴 hex·정의되지 않은
// 색은 한 글자도 없다.
//
// **넓은 화면 2열, 모바일 1열**은 호출부(`app/page.tsx`·`app/contests/page.tsx`)의
// 격자가 정한다 — 이 카드는 격자 한 칸일 때 자기 안을 어떻게 접을지만
// 안다(`sm:flex-row`, 640px 아래는 썸네일이 위로 올라온다).
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/app/components/ui";
import type { Contest } from "@/lib/api/contests";
import {
  finishedStatusLabel,
  formatPrize,
  formatSubmissionCount,
  remainingTimeIsImminent,
  remainingTimeLabel,
} from "@/lib/contest-format";

export function ContestCard({ contest }: { contest: Contest }) {
  const imminent = remainingTimeIsImminent(contest.deadline_at);
  const finished = finishedStatusLabel(contest.status);
  const underfundedBadge = !contest.is_free && contest.is_underfunded;
  const thumbnailUrl = contest.images[0]?.thumbnail_url;
  const hasBadges = contest.is_free || imminent || finished !== null || underfundedBadge;

  return (
    <Link
      href={`/contests/${contest.id}`}
      // 기존 e2e(`e2e/home.spec.ts`·`e2e/contests-pagination.spec.ts`·
      // `e2e/submit.spec.ts`)가 이 속성으로 행을 찾아 클릭한다 — 표 모양 줄을
      // 카드로 바꿔도 그 계약은 그대로 지킨다.
      data-contest-row={contest.id}
      className="flex flex-col border border-rule bg-surface transition-colors hover:border-ink sm:flex-row"
    >
      <div className="aspect-video shrink-0 overflow-hidden border-b border-rule bg-paper sm:aspect-auto sm:w-[180px] sm:border-b-0 sm:border-r">
        {thumbnailUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- 백엔드가 이미 만든 최적화 썸네일
          // 절대 주소를 그대로 쓴다(#233) — next/image 의 원격 최적화는 스토리지 도메인을
          // 배포마다 remotePatterns 에 등록해야 해 배포 설정을 하나 더 늘린다(상세 페이지의
          // ContestImageThumb 과 같은 선택).
          <img src={thumbnailUrl} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <ContestFallbackTile contest={contest} />
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-2 p-4">
        {hasBadges && (
          <div className="flex flex-wrap gap-1.5">
            {contest.is_free && <Badge tone="verified">무료 공모전</Badge>}
            {imminent && <Badge tone="attention">마감임박</Badge>}
            {finished && <Badge>{finished}</Badge>}
            {underfundedBadge && <Badge tone="attention">상금미달</Badge>}
          </div>
        )}

        <p className="truncate text-[15.5px] font-medium">{contest.title}</p>

        <div className="truncate text-xs text-ink/60">
          {contest.category.name}
          {/* 개최자 표시 이름은 비어 있으면(null) 이 줄에서 그 부분만 빠진다 —
              카드 자체가 사라지거나 빈 줄이 남지 않는다(#448 인수조건, spec #444
              "이미 이름 없이 공개된 공모전은 카드에서 개최자 줄만 빠진다"). */}
          {contest.sponsor_display_name && <> · {contest.sponsor_display_name}</>}
        </div>

        {contest.deliverable_types.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {contest.deliverable_types.map((dt) => (
              <Badge key={dt.id}>{dt.name}</Badge>
            ))}
          </div>
        )}

        <div className="mt-auto flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-t border-rule pt-2">
          <span
            className={`truncate font-mono text-base font-semibold ${underfundedBadge ? "text-attention" : ""}`}
          >
            {/* 랜딩의 옛 "0" 표기 버그(spec #444 Problem Statement)가 이 카드로 옮겨 오면 안
                된다 — 무료 공모전은 언제나 금액이 아니라 "무료"다. */}
            {contest.is_free ? "무료" : `${formatPrize(contest.prize)}원`}
          </span>
          <span
            data-testid="deadline"
            className={`shrink-0 font-mono text-sm ${imminent ? "font-semibold text-attention" : "text-ink/70"}`}
          >
            {remainingTimeLabel(contest.deadline_at)}
          </span>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-ink/45">
          <span data-testid="submission-count" data-submission-count={contest.submission_count}>
            {formatSubmissionCount(contest.submission_count)}
          </span>
          <span data-testid="view-count" data-view-count={contest.view_count}>
            조회 {contest.view_count.toLocaleString("ko-KR")}
          </span>
        </div>
      </div>
    </Link>
  );
}

// 공모전 이미지가 없을 때의 대체 타일(#448) — 카테고리 이름과 요구형태로
// 만든다(spec #444 Solution). 브랜드 색만 쓰므로(bg-paper) 이미지가 아직 없는
// 공모전도 빈칸 없이 구분된다.
function ContestFallbackTile({ contest }: { contest: Contest }) {
  return (
    <div className="flex h-full w-full flex-col justify-end gap-1 bg-paper p-3">
      <span className="line-clamp-2 text-lg leading-tight font-bold">{contest.category.name}</span>
      {contest.deliverable_types.length > 0 && (
        <span className="truncate text-[11px] text-ink/50">
          {contest.deliverable_types.map((dt) => dt.name).join(" · ")}
        </span>
      )}
    </div>
  );
}

// 랜딩·`/contests`가 공유하는 격자 — 넓은 화면 2열, 모바일 1열(#448 인수조건).
export function ContestCardGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{children}</div>;
}
