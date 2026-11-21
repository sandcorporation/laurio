// 상장 상태(`certificates/operator_api.py` 의 STATUS_*)의 한글 라벨.
const LABELS: Record<string, string> = {
  valid: "유효",
  cancelled: "취소됨",
  reissued: "재발급됨",
};

export function certificateStatusLabel(status: string): string {
  return LABELS[status] ?? status;
}
