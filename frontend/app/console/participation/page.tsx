"use client";

// 「내 참가 현황」 (#74) — Developer 가 자기 제출들과 각각의 「다음 행동」을 본다.
//
// 이 화면이 이 스펙의 뿌리다. 이의도 지급도 여기 걸린다 — 그 전까지는 백엔드에
// 표면이 다 있는데도 참가자가 도달할 길이 없었다.
//
// **행은 「지금 무엇을 해야 하는가」에 먼저 답한다.** 도메인 상태를 그대로
// 늘어놓지 않는다 — 그 판정은 서버가 하고(submissions/participation.py) 여기서는
// 문구로 옮기기만 한다.
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015). 미들웨어가 쿠키 없는 요청을
// 렌더링 전에 /login 으로 돌린다.
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import {
  NEXT_ACTION_LABELS,
  useMyParticipation,
  type ParticipationRow,
} from "@/lib/participation/use-my-participation";

export default function MyParticipationPage() {
  const session = useSession();
  const state = useMyParticipation();

  // **순서가 중요하다**: 세션이 죽었는지를 로딩 게이트보다 **먼저** 본다.
  // 반대로 두면 세션이 만료됐을 때 조회가 시작되지 않아 영원히 "불러오는 중"
  // 에 갇힌다 — 운영자 앱의 계정 관리 화면이 실제로 겪은 결함이다(#69).
  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || state.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="participation-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl p-10">
      <h1 className="text-2xl font-semibold" data-testid="participation-heading">
        내 참가 현황
      </h1>

      {state.status === "error" ? (
        // 조회 실패와 0건은 반드시 다르게 보여야 한다 — 같아 보이면 조회가 죽은
        // 날 아무도 눈치채지 못한 채 참가자가 자기 상금을 놓친다.
        <p className="mt-6 text-attention" data-testid="participation-error">
          참가 현황을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : state.count === 0 ? (
        <p className="mt-6" data-testid="participation-empty">
          아직 참가한 공모전이 없습니다.
        </p>
      ) : (
        <ul className="mt-6 flex flex-col gap-3" data-testid="participation-list">
          {state.rows.map((row) => (
            <ParticipationCard key={row.submission_id} row={row} />
          ))}
        </ul>
      )}
    </main>
  );
}

function ParticipationCard({ row }: { row: ParticipationRow }) {
  const label = NEXT_ACTION_LABELS[row.next_action];

  return (
    <li
      className="rounded border border-subtle p-4"
      data-testid={`participation-row-${row.submission_id}`}
      data-next-action={row.next_action}
    >
      {/* 「다음 행동」이 제목보다 먼저 온다 — 이 화면에 온 이유가 그것이기 때문이다. */}
      <p
        className={label.mine ? "font-semibold text-attention" : "text-muted"}
        data-testid={`participation-row-${row.submission_id}-next-action`}
      >
        {label.mine ? `내 차례 · ${label.text}` : label.text}
      </p>

      <Link
        className="mt-2 block text-lg"
        href={`/contests/${row.contest_id}`}
        data-testid={`participation-row-${row.submission_id}-contest`}
      >
        {row.contest_title}
      </Link>

      <p className="mt-1 text-sm text-muted">
        상금 {row.prize.toLocaleString()}원 · 마감{" "}
        {new Date(row.deadline_at).toLocaleString("ko-KR")}
      </p>
    </li>
  );
}
