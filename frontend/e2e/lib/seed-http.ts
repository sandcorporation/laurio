// e2e 시드를 HTTP 로 부른다 (#156).
//
// 예전에는 시드 한 번이 `uv run python manage.py …` 서브프로세스였다 — 심는 데이터 양과
// 무관한 Django 부팅이 **약 0.9초**이고, 스위트 한 번에 백 번 넘게 치렀다. 이미 떠 있는
// 백엔드가 답하면 그 비용이 사라진다.
//
// **compose 프로젝트 이름과 무관하다는 성질은 그대로다.** 옛 주석이 `docker compose exec`
// 를 피한 이유가 그것이었는데(프로젝트 이름이 실행 환경마다 다르다), 호스트에 포트로
// 노출된 백엔드를 직접 치는 것도 같은 성질을 갖는다 — `LAURIO_API_BASE_URL` 하나만 본다.
//
// 내부 토큰은 dev 에서 `DEBUG` 기본값이 있다(backend/config/settings.py). 배포 환경에서는
// 이 표면 자체가 거부되므로(엔드포인트가 `IS_DEPLOYED_ENVIRONMENT` 를 먼저 본다) 토큰이
// 새어도 실제 데이터를 심을 수는 없다.

function backendBaseUrl(): string {
  return process.env.LAURIO_API_BASE_URL ?? "http://127.0.0.1:58000";
}

function internalToken(): string {
  return process.env.INTERNAL_API_TOKEN ?? "dev-only-internal-token";
}

/** 등록부의 시드 하나를 돌리고 결과 JSON 을 돌려준다.
 *
 * 조용히 실패하지 않게 막는다 — 시드가 깨지면 반환값이 이상해지고, 그 상태로 스펙이 계속
 * 돌면 진짜 이유(시드가 죽었다)가 아니라 증상(모르는 id 로 404)만 보여 진단이 멀어진다.
 */
export async function runSeed(name: string, options: Record<string, unknown> = {}): Promise<unknown> {
  const response = await fetch(`${backendBaseUrl()}/api/internal/e2e/seed/${name}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-internal-token": internalToken() },
    body: JSON.stringify(options),
  }).catch((cause) => {
    throw new Error(
      `e2e 시드(${name}) 요청이 백엔드에 닿지 못했다 — 스택이 떠 있는지 확인한다` +
        ` (${backendBaseUrl()}). 원인: ${String(cause)}`,
    );
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`e2e 시드(${name})가 ${response.status} 로 실패했다: ${text.slice(0, 400)}`);
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`e2e 시드(${name})가 JSON 을 내지 않았다: ${text.slice(0, 400)}`);
  }
}
