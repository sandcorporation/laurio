// 공개 `/api/health`(#949) — 외부 감시(Gatus)가 backend 의 db·redis·워커 상태를 공개 도메인에서 본다.
// backend 응답을 그대로 넘기지 않는다: 상태 코드는 200·503 만, 본문은 `status` 와 알려진 점검 이름만 남긴다
// (호스트·버전·내부 오류 문구가 backend 의 다른 응답 형태로 새는 것을 막는다).
import type { BackendHealthReply } from "@codemit/bff-shared";

const KNOWN_CHECKS = new Set(["db", "redis", "celery", "grader"]);

export type PublicHealth = { status: number; body: { status: "ok" } | { status: "error"; failed: string[] } };

export function publicHealth(reply: BackendHealthReply | null): PublicHealth {
  if (reply === null) return { status: 503, body: { status: "error", failed: ["backend"] } };
  if (reply.status === 200) return { status: 200, body: { status: "ok" } };
  let failed: string[] = [];
  try {
    const parsed: unknown = JSON.parse(reply.body);
    const list = (parsed as { failed?: unknown })?.failed;
    if (Array.isArray(list)) failed = list.filter((n): n is string => typeof n === "string" && KNOWN_CHECKS.has(n));
  } catch {
    // 본문이 JSON 이 아니면 점검 이름 없이 오류만 알린다.
  }
  if (failed.length === 0) failed = ["backend"];
  return { status: 503, body: { status: "error", failed } };
}
