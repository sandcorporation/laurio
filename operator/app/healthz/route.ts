import { NextResponse } from "next/server";

// frontend/app/healthz/route.ts와 같은 계약 — Next가 요청을 처리하는가, 그리고
// 설정된 백엔드에 실제로 닿는가. 이 앱도 BFF라서(ADR-0019) 백엔드에 닿지 못하면
// 로그인부터 아무것도 되지 않는다.
export const dynamic = "force-dynamic";

const BACKEND_PROBE_TIMEOUT_MS = 3000;

function backendBaseUrl(): string {
  return process.env.LAURIO_API_BASE_URL ?? "http://127.0.0.1:58000";
}

async function probeBackend(): Promise<"ok" | "unreachable"> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BACKEND_PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(`${backendBaseUrl()}/api/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    return res.ok ? "ok" : "unreachable";
  } catch {
    return "unreachable";
  } finally {
    clearTimeout(timer);
  }
}

export async function GET() {
  const backend = await probeBackend();
  return NextResponse.json(
    { status: backend === "ok" ? "ok" : "degraded", operator: "ok", backend },
    { status: backend === "ok" ? 200 : 503 },
  );
}
