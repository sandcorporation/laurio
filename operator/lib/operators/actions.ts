// Operator 계정 관리 변경 행위(#69) — 생성·비활성화·재활성화.
//
// 백엔드(accounts/operator_api.py)는 실패마다 안정적인 `code`와 사람이 읽을
// `detail`을 함께 준다 — "화면이 detail 문구를 파싱해 분기하면 문구를 다듬는
// 순간 조용히 깨진다"는 그 파일 자신의 주석이 이유다. 그래서 여기서는 `code`를
// 분기에, `detail`을 화면 문구에 그대로 쓴다. 약한 비밀번호(422/invalid, Django
// 비밀번호 검증기 메시지)와 중복 아이디(422/invalid 또는 409/duplicate, "이미
// 존재하는 사용자입니다" 계열 메시지)는 같은 422/invalid로 묶일 때도 있지만
// `detail` 문구 자체가 서로 달라서 화면에서 구별된다 — 두 실패를 "생성
// 실패"로 뭉개지 않는다.
import type { OperatorAccount } from "./types";

export interface ApiFailure {
  ok: false;
  status: number;
  code: string;
  detail: string;
}

export interface ApiSuccess<T> {
  ok: true;
  data: T;
}

export type ApiResult<T> = ApiSuccess<T> | ApiFailure;

async function toFailure(res: Response): Promise<ApiFailure> {
  const body = (await res.json().catch(() => null)) as { detail?: string; code?: string } | null;
  return {
    ok: false,
    status: res.status,
    code: body?.code ?? "error",
    detail: body?.detail ?? `요청이 실패했습니다 (${res.status}).`,
  };
}

export interface CreateOperatorInput {
  username: string;
  password: string;
  is_superuser: boolean;
}

export async function createOperator(input: CreateOperatorInput): Promise<ApiResult<OperatorAccount>> {
  const res = await fetch("/api/backend/operator/operators", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as OperatorAccount };
}

export async function deactivateOperator(id: number): Promise<ApiResult<null>> {
  const res = await fetch(`/api/backend/operator/operators/${id}/deactivate`, { method: "POST" });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: null };
}

export async function reactivateOperator(id: number): Promise<ApiResult<null>> {
  const res = await fetch(`/api/backend/operator/operators/${id}/reactivate`, { method: "POST" });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: null };
}
