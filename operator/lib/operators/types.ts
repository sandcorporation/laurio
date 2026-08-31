// Operator 계정 관리(#69)의 공유 타입. backend/accounts/operator_api.py의
// `OperatorOut`과 필드가 정확히 대응한다 — 자격증명과 관련된 것은 아무것도
// 없다(비밀번호 해시는 물론 애초에 응답에 없다).
export interface OperatorAccount {
  id: number;
  username: string;
  is_superuser: boolean;
  is_active: boolean;
}
