"use client";

// 운영팀 알림 발송 이력 표(#418/#419, #424 — 골간으로 옮긴다) — 받는 사람·이메일·
// 제목·보낸 운영자·시각·읽음 여부. 수정·삭제 버튼이 없다(append-only, CONTEXT.md
// 「운영자 알림」). 이미지가 첨부된 줄은 다시 열어 볼 수 있다(User Story 8) —
// 목록 응답에는 유무만 있으므로 누를 때마다 짧게 유효한 주소를 새로 받는다.
//
// **「읽음」은 판정이 아니라 정보다** — 그래서 초록 배지가 아니라 중립 배지에
// 글자로만 가른다(spec #421 user story 17, 지급 큐의 대기 배지와 같은 원칙).
import { useState } from "react";

import { Badge } from "@/app/components/badge";

import { fetchOperatorNoticeImageUrl } from "./actions";
import type { OperatorNotice } from "./types";

const COL = {
  recipient: "w-[70px]",
  email: "w-[170px]",
  sentBy: "w-[100px]",
  sentAt: "w-[130px]",
  read: "w-[70px]",
  image: "w-[80px]",
};

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className={COL.recipient}>받는 사람</div>
      <div className={COL.email}>이메일</div>
      <div className="min-w-0 flex-1">제목</div>
      <div className={`${COL.sentBy} shrink-0`}>보낸 운영자</div>
      <div className={`${COL.sentAt} shrink-0`}>보낸 시각</div>
      <div className={`${COL.read} shrink-0`}>읽음</div>
      <div className={`${COL.image} shrink-0`}></div>
    </div>
  );
}

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
    return (
      <p data-testid="operator-notices-empty" className="px-[15px] py-[14px] text-[13px] text-ink/62">
        아직 보낸 알림이 없습니다.
      </p>
    );
  }

  return (
    <>
      <div data-testid="operator-notices-table">
        <TableHead />
        {notices.map((notice, i) => (
          <div
            key={notice.notification_id}
            data-testid={`operator-notice-row-${notice.notification_id}`}
            className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] ${
              i % 2 === 1 ? "bg-ink/[2%]" : ""
            }`}
          >
            <div className={`${COL.recipient} shrink-0 truncate font-mono`}>#{notice.recipient_id}</div>
            <div className={`${COL.email} shrink-0 truncate`}>{notice.recipient_email}</div>
            <div className="min-w-0 flex-1 truncate">{notice.title}</div>
            <div className={`${COL.sentBy} shrink-0 truncate font-mono`}>{notice.sent_by}</div>
            <div className={`${COL.sentAt} shrink-0 truncate font-mono text-[12.5px]`}>
              {new Date(notice.created_at).toLocaleString("ko-KR")}
            </div>
            <div className={`${COL.read} shrink-0`} data-testid={`operator-notice-read-${notice.notification_id}`}>
              <Badge tone="neutral">{notice.read_at ? "읽음" : "안 읽음"}</Badge>
            </div>
            <div className={`${COL.image} shrink-0`}>
              {notice.has_image && (
                <button
                  type="button"
                  data-testid={`operator-notice-view-image-${notice.notification_id}`}
                  onClick={() => openImage(notice.notification_id)}
                  className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
                >
                  이미지
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {imageError && (
        <p role="alert" data-testid="operator-notice-image-view-error" className="px-[15px] py-[10px] text-[12.5px] text-attention">
          {imageError}
        </p>
      )}
      {openImageUrl && (
        <div data-testid="operator-notice-image-preview" className="flex flex-col items-start gap-2 border-t border-rule p-[15px]">
          <img src={openImageUrl} alt="첨부된 이미지" className="max-h-[280px] border border-rule" />
          <button
            type="button"
            data-testid="operator-notice-image-preview-close"
            onClick={() => setOpenImageUrl(null)}
            className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
          >
            닫기
          </button>
        </div>
      )}
    </>
  );
}
