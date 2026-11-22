// 반려된 시도의 사유 한 줄(#1311) — 「소스 약 41만 자 — 한도 약 30만 자」. 학생 문제 화면과 강사 제출 현황이 같은 글을 쓴다.
import { charsLabel } from "@/lib/scoring/calculator";

import type { SubmissionRejection } from "./api";

export function rejectionText(rejection: SubmissionRejection | null | undefined): string {
  if (!rejection) return "";
  return `소스 약 ${charsLabel(rejection.source_chars)} — 한도 약 ${charsLabel(rejection.limit_chars)}`;
}

/** 「들어가는 파일만으로 채점」(#1311)이 보지 못한 파일 수 — 0 이면 빈 글. */
export function unseenFilesText(unseen: number | undefined): string {
  return unseen ? `파일 ${unseen.toLocaleString("ko-KR")}개는 보지 못했습니다` : "";
}
