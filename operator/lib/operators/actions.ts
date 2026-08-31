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
//
// **`detail`이 항상 문자열은 아니다**(코드리뷰 지적). django-ninja의 **요청
// 검증** 실패(예: 스키마의 `min_length=1`을 어긴 빈 아이디·비밀번호)는 우리
// 라우터가 직접 만든 422가 아니라 ninja/pydantic이 만든 422이고, 그 `detail`은
// 오류 객체의 **배열**이다(`[{"type": ..., "loc": [...], "msg": "..."}, ...]`).
// 이걸 문자열로 가정하고 그대로 렌더하면(예: `{error}`) React가 "Objects are
// not valid as a React child"로 화면 전체를 죽인다. `normalizeDetail`이 이
// 두 형태(우리 라우터의 문자열 detail, ninja의 배열 detail)를 모두 사람이 읽을
// 수 있는 문자열 하나로 좁힌다 — 호출부는 항상 문자열만 받는다.
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

function normalizeDetail(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.length > 0) return detail;

  // ninja/pydantic 요청 검증 오류: [{"type": "...", "loc": [...], "msg": "..."}]
  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item && typeof (item as { msg: unknown }).msg === "string"
          ? (item as { msg: string }).msg
          : null,
      )
      .filter((msg): msg is string => msg !== null);
    if (messages.length > 0) return messages.join(" ");
  }

  return `요청이 실패했습니다 (${status}).`;
}

async function toFailure(res: Response): Promise<ApiFailure> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown; code?: string } | null;
  return {
    ok: false,
    status: res.status,
    code: body?.code ?? "error",
    detail: normalizeDetail(body?.detail, res.status),
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
