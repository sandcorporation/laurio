"use client";

// 「내 공모전」 (#81) — Sponsor 가 자기가 연 공모전들과 각각의 「다음 행동」을 본다.
//
// 개최자는 개최·결제·심사까지 할 수 있는데 그것들을 모아 보는 곳이 없었다.
// 그래서 "내 공모전이 끝났는가, 안 끝났으면 무엇을 기다리는가"에 답할 자리가
// 없었다.
//
// **행은 「지금 무엇을 해야 하는가」에 먼저 답한다.** 도메인 상태를 그대로
// 늘어놓지 않는다 — 그 판정은 서버가 하고(contests/sponsorship.py) 여기서는
// 문구로 옮기기만 한다. 참가자 화면과 같은 구조이고 같은 이유다.
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015).
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import {
  SPONSOR_ACTION_LABELS,
  useMyContests,
  type SponsoredContestRow,
} from "@/lib/sponsorship/use-my-contests";

export default function MyContestsPage() {
  const session = useSession();
  const state = useMyContests();

  // 세션이 죽었는지를 로딩 게이트보다 **먼저** 본다 — 반대로 두면 만료 시
  // 영원히 "불러오는 중"에 갇힌다(#69).
  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || state.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="my-contests-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl p-10">
      <h1 className="text-2xl font-semibold" data-testid="my-contests-heading">
        내 공모전
      </h1>

      {state.status === "error" ? (
        // 조회 실패와 0건은 반드시 다르게 보여야 한다 — 같아 보이면 조회가 죽은
        // 날 개최자는 자기 공모전이 사라졌다고 읽는다.
        <p className="mt-6 text-attention" data-testid="my-contests-error">
          공모전 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : state.count === 0 ? (
        <p className="mt-6" data-testid="my-contests-empty">
          아직 연 공모전이 없습니다.
        </p>
      ) : (
        <>
          <ul className="mt-6 flex flex-col gap-3" data-testid="my-contests-list">
            {state.rows.map((row) => (
              <SponsoredContestCard key={row.contest_id} row={row} />
            ))}
          </ul>

          {/* 목록은 페이지네이션된다. 컨트롤이 없으면 20개를 넘는 개최자는
              나머지에 도달할 길이 없고, 잘렸다는 사실조차 화면에 없다 —
              오래된 것들이 잘리는데 그중 하나가 「내 차례」면 이 화면이
              막으려던 결과가 그대로 일어난다. */}
          {state.hasMore ? (
            <button
              className="mt-4 rounded border border-subtle px-4 py-2 text-sm disabled:opacity-50"
              type="button"
              onClick={state.loadMore}
              disabled={state.loadingMore}
              data-testid="my-contests-load-more"
            >
              {state.loadingMore
                ? "불러오는 중..."
                : `더 보기 (${state.rows.length} / ${state.count})`}
            </button>
          ) : null}
        </>
      )}
    </main>
  );
}

function SponsoredContestCard({ row }: { row: SponsoredContestRow }) {
  const label = SPONSOR_ACTION_LABELS[row.next_action];

  return (
    <li
      className="rounded border border-subtle p-4"
      data-testid={`my-contest-row-${row.contest_id}`}
      data-next-action={row.next_action}
    >
      {/* 「다음 행동」이 제목보다 먼저 온다 — 이 화면에 온 이유가 그것이다. */}
      <p
        className={label.mine ? "font-semibold text-attention" : "text-muted"}
        data-testid={`my-contest-row-${row.contest_id}-next-action`}
      >
        {label.mine ? `내 차례 · ${label.text}` : label.text}
      </p>

      {/* draft(next_action === "pay_to_publish")는 공개 서버 컴포넌트
          (`/contests/{id}`)로 가면 인증 없는 조회로는 404다 — 소유자라도
          공개 표면에서는 draft가 보이지 않는다(#111, ADR-0015). 이어서
          작성하는 자리(`/console/contests/{id}/draft`)로 보낸다 — 결제
          화면이 아니라 그 화면이 "초안 행을 눌렀을 때" 가야 할 곳이다. */}
      <Link
        className="mt-2 block text-lg"
        href={
          row.next_action === "pay_to_publish"
            ? `/console/contests/${row.contest_id}/draft`
            : `/contests/${row.contest_id}`
        }
        data-testid={`my-contest-row-${row.contest_id}-detail`}
      >
        {row.title}
      </Link>

      <p className="mt-1 text-sm text-muted">
        상금 {row.prize.toLocaleString()}원 · 마감{" "}
        {new Date(row.deadline_at).toLocaleString("ko-KR")} · 제출{" "}
        <span data-testid={`my-contest-row-${row.contest_id}-submission-count`}>
          {row.submission_count}
        </span>
        건
      </p>

      {/* **행동 링크는 한 줄에 나란히 선다.** 넷 다 `inline-block` 이라 가로 간격이
          없어 「심사하러 가기지표 보기결제하러 가기」로 붙어 보였다 — JSX 는 줄바꿈
          공백을 지우므로 마진 없이는 구분되지 않는다. 몇 개가 뜨는지가 상태마다
          달라(지표만 항상, 나머지는 조건부) 링크마다 마진을 주면 첫 링크 앞이나
          마지막 뒤에 빈칸이 생긴다 — 컨테이너의 gap 이 그 문제를 갖지 않는다. */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        {/* 심사 화면은 **심사할 수 있는 단계에만** 건다. 어느 상태가 그런지는
            화면이 파생하지 않고 번역표가 들고 있다 — 별도 Set 으로 빼면 새 상태가
            생겼을 때 아무도 결정하지 않은 채 조용히 빠진다(#74 에서 세운 관용구). */}
        {label.canJudge ? (
          <Link
            className="text-sm underline"
            href={`/console/contests/${row.contest_id}/judge`}
            data-testid={`my-contest-row-${row.contest_id}-judge`}
          >
            심사하러 가기
          </Link>
        ) : null}

        {/* 인수 확인 화면은 그 확인이 의미 있는 단계에만 건다(#179) — 「내 차례 ·
            인수를 확인하세요」가 뜨는 그 자리에서 그 행동으로 갈 수 있어야 한다.
            canJudge·canPay와 같은 이유로 번역표를 거친다: 새 상태가 생기면
            `tsc --noEmit`이 결정을 요구한다. */}
        {label.canAcceptHandover ? (
          <Link
            className="text-sm underline"
            href={`/console/contests/${row.contest_id}/handover`}
            data-testid={`my-contest-row-${row.contest_id}-handover`}
          >
            인수 확인하러 가기
          </Link>
        ) : null}

        {/* 지표 화면(#107)은 「다음 행동」과 무관하게 항상 열려 있다 — 마감 전에도
            Sponsor 는 자기 Contest 의 참가 추이를 볼 수 있어야 하고(마감 전에도
            개별 Submission 을 볼 수 있으므로 집계도 새로 알려주는 것이 없다),
            canJudge·canPay 처럼 상태를 타는 링크가 아니다. */}
        <Link
          className="text-sm underline"
          href={`/console/contests/${row.contest_id}/metrics`}
          data-testid={`my-contest-row-${row.contest_id}-metrics`}
        >
          지표 보기
        </Link>

        {/* 「결제해야 공개됩니다」가 갈 곳이 없었다(#86) — draft 인 채로 두면
            아무 일도 일어나지 않는데, 이 화면이 유일하게 그 사실을 말하는 자리다.
            canJudge와 같은 이유로 `next_action`을 직접 비교하지 않고 번역표를
            거친다(#86 코드리뷰) — 새 상태가 생기면 빌드가 깨진다. */}
        {label.canPay ? (
          <Link
            className="text-sm underline"
            href={`/console/contests/${row.contest_id}/payment`}
            data-testid={`my-contest-row-${row.contest_id}-pay`}
          >
            결제하러 가기
          </Link>
        ) : null}
      </div>

    </li>
  );
}
