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
import { PARTICIPATION_EMPTY_MESSAGE } from "@/lib/participation/empty-state";
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
        // 공모전이 꺼진 환경(#271)에서는 이 화면을 여는 사람이 과제만 쓸 수
        // 있다 — 종류를 말하면 가질 수 없는 개념으로 말하게 된다(#353).
        <p className="mt-6" data-testid="participation-empty">
          {PARTICIPATION_EMPTY_MESSAGE}
        </p>
      ) : (
        <>
          <ul className="mt-6 flex flex-col gap-3" data-testid="participation-list">
            {state.rows.map((row) => (
              <ParticipationCard key={row.submission_id} row={row} />
            ))}
          </ul>

          {/* 목록은 페이지네이션된다 — 컨트롤이 없으면 20건을 넘는 참가자는
              오래된 행들에 도달할 길이 없다. 그중 하나가 「내 차례」면
              (이의 기한이 남은 채점, 지급 요청) 이 화면이 막으려던 결과가
              그대로 일어난다. */}
          {state.hasMore ? (
            <button
              className="mt-4 rounded border border-subtle px-4 py-2 text-sm disabled:opacity-50"
              type="button"
              onClick={state.loadMore}
              disabled={state.loadingMore}
              data-testid="participation-load-more"
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

      {/* 자기 제출로 돌아가는 길 (#245, #258) — 「내 참여」에 이 링크가 없어서
          제출 화면에 도달할 방법이 공개 상세의 CTA(공모전에만, 그리고
          `published` 상태에만 있다)뿐이었다. **모든 행에 건다** — 아래 「채점
          결과 보기」와 같은 이유다: 마감 뒤(채점 대기·이의 기간·미선정·배분·
          지급·지급 완료)에도 자기 제출물은 읽을 수 있고(백엔드가 이미
          `_serialize`에서 `past_deadline`으로 그 얼굴을 결정한다,
          `submissions/api.py`), 제출 화면 자체가 마감 뒤에는 읽기 전용으로
          서므로(`canEdit`) 저장 경로가 열릴 위험은 없다. #245 가 이 링크를
          `can_edit_submission`로 좁혔던 것은 「수정 어포던스」를 없애려던
          것이었는데, 링크가 하나뿐이어서 읽기까지 같이 사라진 누락이었다
          (#258).

          「지금 고칠 수 있는가」를 여기서 시각으로 다시 재지 않는다 — 서버가
          준 `next_action`만 본다(`can_edit_submission`은
          `_reject_if_past_deadline`과 같은 조건, `submissions/
          participation.py`). 문구만 그 값으로 갈린다: 실제로 고칠 수 있을
          때만 "수정하러"라고 말하고, `needs_reverification`(#250, 마감 전인데
          본인확인이 풀린 상태)은 본인확인이 먼저라고 말하고, 그 밖의 모든
          값(채점 대기부터 지급 완료까지)은 "내 제출물 보기"다.

          과제가 걷히면서(#359, spec #358) `invite_code`로 `/assignments/{code}`로
          보내던 분기도 되돌렸다 — 그 화면이 없으니 모든 행이 공모전 제출
          화면 하나로 간다. */}
      <Link
        className="mt-2 block text-sm underline"
        href={`/console/contests/${row.contest_id}/submit`}
        data-testid={`participation-row-${row.submission_id}-edit`}
      >
        {row.next_action === "can_edit_submission"
          ? "제출물 수정하러 가기"
          : row.next_action === "needs_reverification"
            ? "내 제출물 보기 (본인확인 필요)"
            : "내 제출물 보기"}
      </Link>

      {/* **모든 행에 건다.** 「채점됐을 때만」으로 좁히면 서버가 이미 내린 판정을
          화면이 다시 파생하는 것이고, 이의가 기각된 사람은 자기 점수를 다시 볼
          길이 없어진다. 채점 전이면 그 화면이 "아직 채점되지 않았다"고 말한다. */}
      <Link
        className="mt-2 inline-block text-sm underline"
        href={`/console/participation/${row.submission_id}/appeal`}
        data-testid={`participation-row-${row.submission_id}-appeal`}
      >
        채점 결과 보기
      </Link>

      {/* 지급 화면은 지급 단계에 닿은 행에만 건다. 「모든 행」으로 하면
          수상하지 않은 사람에게 「지급 요청」 버튼이 보이고, 눌러 봐야 서버가
          거절한다. 어느 상태가 지급 단계인지는 화면이 파생하지 않는다 —
          서버가 준 값에 대해 번역표가 답을 들고 있고, 새 값이 생기면
          `tsc --noEmit` 이 그 답을 요구한다. */}
      {label.payoutStage ? (
        <Link
          className="mt-2 ml-4 inline-block text-sm underline"
          href={`/console/payouts/${row.contest_id}`}
          data-testid={`participation-row-${row.submission_id}-payout`}
        >
          상금 지급
        </Link>
      ) : null}

      {/* 인수 자료 업로드(#180)도 지급 단계와 같은 조건에 건다 — 인수 확인
          대기부터가 Award된 뒤이므로, payoutStage가 참인 행은 이미 Award된
          Submission이다(위 NEXT_ACTION_LABELS 주석). 선택 사항이라 안 올려도
          되지만, 올릴 곳이 있다는 것 자체는 보여야 한다. */}
      {label.payoutStage ? (
        <Link
          className="mt-2 ml-4 inline-block text-sm underline"
          href={`/console/participation/${row.submission_id}/handover`}
          data-testid={`participation-row-${row.submission_id}-handover`}
        >
          인수 자료
        </Link>
      ) : null}
    </li>
  );
}
