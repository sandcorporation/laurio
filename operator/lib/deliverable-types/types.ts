// DeliverableType 운영자 화면 타입(#80). 백엔드(contests/schemas.py)의
// OperatorDeliverableTypeOut·DeliverableTypeChangeOut과 1:1로 대응한다.

export interface DeliverableType {
  id: number;
  name: string;
  minimum_prize: number;
  is_active: boolean;
}

export interface DeliverableTypeChangeEntry {
  id: number;
  deliverable_type_id: number;
  operator_username: string;
  action: "created" | "updated" | "deactivated";
  reason: string;
  before: Record<string, number | boolean | string>;
  after: Record<string, number | boolean | string>;
  changed_at: string;
}

export const ACTION_LABELS: Record<DeliverableTypeChangeEntry["action"], string> = {
  created: "생성",
  updated: "수정",
  deactivated: "비활성화",
};
