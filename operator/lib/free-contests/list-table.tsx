import Link from "next/link";

import { freeContestStatusLabel } from "./status-label";
import { operatorNoticeComposeHref } from "./notify-link";
import type { FreeContest } from "./types";

// 무료 공모전 목록 표(#420) — 수상자 옆에 「운영팀 알림 보내기」를 둔다. 수상하지
// 않은(아직 심사 중이거나 심사 기간 안에 못 고르고 끝난) 행은 `winner`가 없어
// 그 자리가 비어 있다.
export function FreeContestListTable({ contests }: { contests: FreeContest[] }) {
  return (
    <table data-testid="free-contest-list-table">
      <thead>
        <tr>
          <th>제목</th>
          <th>상태</th>
          <th>마감</th>
          <th>수상자</th>
          <th>작업</th>
        </tr>
      </thead>
      <tbody>
        {contests.map((contest) => (
          <tr key={contest.id} data-testid={`free-contest-row-${contest.id}`}>
            <td>{contest.title}</td>
            <td data-testid={`free-contest-status-${contest.id}`}>
              {freeContestStatusLabel(contest.status)}
            </td>
            <td>{new Date(contest.deadline_at).toLocaleString("ko-KR")}</td>
            <td data-testid={`free-contest-winner-${contest.id}`}>
              {contest.winner
                ? contest.winner.nickname || contest.winner.email
                : "-"}
            </td>
            <td>
              {contest.winner && (
                <Link
                  href={operatorNoticeComposeHref(contest.winner)}
                  data-testid={`free-contest-notify-${contest.id}`}
                >
                  운영팀 알림 보내기
                </Link>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
