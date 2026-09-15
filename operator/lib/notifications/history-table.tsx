"use client";

// 운영팀 알림 발송 이력 표(#418/#419) — 받는 사람·보낸 운영자·시각·읽음 여부.
// 수정·삭제 버튼이 없다(append-only, CONTEXT.md 「운영자 알림」). 이미지가
// 첨부된 줄은 다시 열어 볼 수 있다(User Story 8) — 목록 응답에는 유무만
// 있으므로 누를 때마다 짧게 유효한 주소를 새로 받는다.
import { useState } from "react";

import { fetchOperatorNoticeImageUrl } from "./actions";
import type { OperatorNotice } from "./types";

export function OperatorNoticeHistoryTable({ notices }: { notices: OperatorNotice[] }) {
  const [openImageUrl, setOpenImageUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);

  async function openImage(notificationId: number) {
    setImageError(null);
    const result = await fetchOperatorNoticeImageUrl(notificationId);
    if (!result.ok) {
      setImageError(result.detail);
      return;
    }
    setOpenImageUrl(result.data.download_url);
  }

  if (notices.length === 0) {
    return <p data-testid="operator-notices-empty">아직 보낸 알림이 없습니다.</p>;
  }

  return (
    <>
      <table data-testid="operator-notices-table">
        <thead>
          <tr>
            <th>받는 사람</th>
            <th>제목</th>
            <th>보낸 운영자</th>
            <th>보낸 시각</th>
            <th>읽음 여부</th>
            <th>이미지</th>
          </tr>
        </thead>
        <tbody>
          {notices.map((notice) => (
            <tr key={notice.notification_id} data-testid={`operator-notice-row-${notice.notification_id}`}>
              <td>{notice.recipient_email}</td>
              <td>{notice.title}</td>
              <td>{notice.sent_by}</td>
              <td>{new Date(notice.created_at).toLocaleString("ko-KR")}</td>
              <td data-testid={`operator-notice-read-${notice.notification_id}`}>
                {notice.read_at ? "읽음" : "안 읽음"}
              </td>
              <td>
                {notice.has_image && (
                  <button
                    type="button"
                    data-testid={`operator-notice-view-image-${notice.notification_id}`}
                    onClick={() => openImage(notice.notification_id)}
                  >
                    이미지 보기
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {imageError && (
        <p role="alert" data-testid="operator-notice-image-view-error">
          {imageError}
        </p>
      )}
      {openImageUrl && (
        <div data-testid="operator-notice-image-preview">
          <img src={openImageUrl} alt="첨부된 이미지" />
          <button type="button" data-testid="operator-notice-image-preview-close" onClick={() => setOpenImageUrl(null)}>
            닫기
          </button>
        </div>
      )}
    </>
  );
}
