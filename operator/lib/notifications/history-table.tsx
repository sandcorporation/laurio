// 운영팀 알림 발송 이력 표(#418) — 받는 사람·보낸 운영자·시각·읽음 여부. 수정·삭제
// 버튼이 없다(append-only, CONTEXT.md 「운영자 알림」).
import type { OperatorNotice } from "./types";

export function OperatorNoticeHistoryTable({ notices }: { notices: OperatorNotice[] }) {
  if (notices.length === 0) {
    return <p data-testid="operator-notices-empty">아직 보낸 알림이 없습니다.</p>;
  }

  return (
    <table data-testid="operator-notices-table">
      <thead>
        <tr>
          <th>받는 사람</th>
          <th>제목</th>
          <th>보낸 운영자</th>
          <th>보낸 시각</th>
          <th>읽음 여부</th>
        </tr>
      </thead>
      <tbody>
        {notices.map((notice) => (
          <tr key={notice.notification_id} data-testid={`operator-notice-row-${notice.notification_id}`}>
            <td>#{notice.recipient_id}</td>
            <td>{notice.title}</td>
            <td>{notice.sent_by}</td>
            <td>{new Date(notice.created_at).toLocaleString("ko-KR")}</td>
            <td data-testid={`operator-notice-read-${notice.notification_id}`}>
              {notice.read_at ? "읽음" : "안 읽음"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
