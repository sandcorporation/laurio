// 정책 변경 API 호출(#77). `operator/lib/operators/actions.ts`와 같은 계약이다
// — 백엔드가 안정적인 `code`와 사람이 읽을 `detail`을 같이 준다는 것, 그리고
// **`detail`이 항상 문자열은 아니라는 것**(django-ninja의 요청 검증 422는
// `detail`이 오류 객체의 배열이다 — 그대로 렌더하면 React가 "Objects are not
// valid as a React child"로 화면 전체를 죽인다, #69에서 실제로 겪었다).
// `normalizeDetail`이 두 형태(우리 라우터의 문자열 detail, ninja의 배열
// detail)를 모두 사람이 읽을 수 있는 문자열 하나로 좁힌다.
import type { PlatformPolicy, PolicyChangeEntry, PolicyField } from "./types";

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

export async function fetchPolicy(): Promise<ApiResult<PlatformPolicy>> {
  const res = await fetch("/api/backend/operator/policy", { cache: "no-store" });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as PlatformPolicy };
}

export async function fetchPolicyChanges(): Promise<ApiResult<PolicyChangeEntry[]>> {
  const res = await fetch("/api/backend/operator/policy/changes", { cache: "no-store" });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as PolicyChangeEntry[] };
}

export interface UpdatePolicyInput {
  changes: Partial<Record<PolicyField, number>>;
  reason: string;
  expectedVersion: number;
}

export async function updatePolicy(input: UpdatePolicyInput): Promise<ApiResult<PlatformPolicy>> {
  const res = await fetch("/api/backend/operator/policy", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      ...input.changes,
      reason: input.reason,
      expected_version: input.expectedVersion,
    }),
  });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as PlatformPolicy };
}
