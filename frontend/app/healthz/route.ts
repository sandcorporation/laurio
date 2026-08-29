import { NextResponse } from "next/server";

// 헬스 엔드포인트. 두 가지를 답한다.
//
//   1. Next 가 요청을 처리하고 있는가
//   2. 설정된 백엔드에 실제로 닿는가
//
// 둘째를 포함하는 이유: 이 앱은 BFF 라서(ADR-0016) 백엔드에 닿지 못하면 로그인부터
// 아무것도 되지 않는다. "Next 는 떴는데 백엔드를 못 찾는" 상태가 정상으로 보이면
// compose 도 CI 도 그걸 못 잡는다. 백엔드가 죽어 있으면 503 으로 정직하게 알린다.
//
// 라우트 핸들러이므로 브라우저 없이 raw HTTP 로 칠 수 있다 — e2e 가 `page` 와
// `request` 두 방식으로 같은 앱을 치는 시임 증명에 이 엔드포인트를 쓴다(ADR-0017).

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
    { status: backend === "ok" ? "ok" : "degraded", frontend: "ok", backend },
    { status: backend === "ok" ? 200 : 503 },
  );
}
