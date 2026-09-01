// DeliverableType 관리 API 호출(#80). `operator/lib/operators/actions.ts`·
// `operator/lib/policies/actions.ts`와 같은 계약 — 안정적인 `code` + 사람이 읽을
// `detail`, 그리고 detail이 배열일 수 있다는 것(django-ninja 요청 검증 422)을
// 같은 normalizeDetail로 좁힌다.
import type { DeliverableType, DeliverableTypeChangeEntry } from "./types";

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

export async function fetchDeliverableTypes(): Promise<ApiResult<DeliverableType[]>> {
  const res = await fetch("/api/backend/operator/deliverable-types", { cache: "no-store" });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as DeliverableType[] };
}

export async function fetchDeliverableTypeChanges(): Promise<ApiResult<DeliverableTypeChangeEntry[]>> {
  const res = await fetch("/api/backend/operator/deliverable-types/changes", { cache: "no-store" });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as DeliverableTypeChangeEntry[] };
}

export interface CreateDeliverableTypeInput {
  name: string;
  minimum_prize: number;
  reason: string;
}

export async function createDeliverableType(
  input: CreateDeliverableTypeInput,
): Promise<ApiResult<DeliverableType>> {
  const res = await fetch("/api/backend/operator/deliverable-types", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as DeliverableType };
}

export async function updateMinimumPrize(
  id: number,
  minimumPrize: number,
  reason: string,
): Promise<ApiResult<DeliverableType>> {
  const res = await fetch(`/api/backend/operator/deliverable-types/${id}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ minimum_prize: minimumPrize, reason }),
  });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as DeliverableType };
}

export async function deactivateDeliverableType(
  id: number,
  reason: string,
): Promise<ApiResult<DeliverableType>> {
  const res = await fetch(`/api/backend/operator/deliverable-types/${id}/deactivate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) return toFailure(res);
  return { ok: true, data: (await res.json()) as DeliverableType };
}
