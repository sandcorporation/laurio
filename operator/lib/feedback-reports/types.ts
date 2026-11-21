// 제보 목록·상세가 쓰는 타입과 글자 (#1243, 스펙 #1237). 응답 모양은 운영자 API 의 것이다.

export type FeedbackStatus = "received" | "in_progress" | "deployed" | "declined";

export const STATUS_OPTIONS: ReadonlyArray<{ value: FeedbackStatus; label: string }> = [
  { value: "received", label: "접수" },
  { value: "in_progress", label: "작업 중" },
  { value: "deployed", label: "반영" },
  { value: "declined", label: "반려" },
];
export const APP_OPTIONS = [
  { value: "contest", label: "공모전" },
  { value: "classroom", label: "강의실" },
] as const;
export const KIND_OPTIONS = [
  { value: "suggestion", label: "제안" },
  { value: "bug", label: "문제" },
] as const;

export type ReportRow = {
  id: number;
  kind: string;
  app: string;
  status: string;
  body: string;
  reporter_id: number;
  reporter_email: string;
  has_screenshot: boolean;
  received_at: string;
  closed_at: string | null;
};

export type ReportHistory = {
  from_status: string;
  to_status: string;
  note: string;
  actor: string;
  changed_at: string;
};

export type ReportDetail = ReportRow & {
  page_url: string;
  user_agent: string;
  screen_width: number | null;
  screen_height: number | null;
  resolution_note: string;
  screenshot_url: string | null;
  history: ReportHistory[];
};

export function labelOf(options: ReadonlyArray<{ value: string; label: string }>, value: string): string {
  return options.find((option) => option.value === value)?.label ?? value;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
