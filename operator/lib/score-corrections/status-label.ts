const LABELS: Record<string, string> = {
  in_progress: "진행 중",
  done: "끝",
  failed: "실패",
};

export function correctionStatusLabel(status: string): string {
  return LABELS[status] ?? status;
}

export function isCorrectionRunning(status: string): boolean {
  return status === "in_progress";
}
