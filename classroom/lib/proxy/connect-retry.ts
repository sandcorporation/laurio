// 배포 중 backend·이벤트 서비스가 잠깐 없는 몇 초를 BFF 가 물러서서 기다린다
// (2026-09-18, GlitchTip 60).
//
// `deploy.sh` 가 컨테이너를 바꿔 끼우는 사이 그 포트에는 아무도 듣지 않아, 그
// 순간 들어온 요청의 `fetch` 가 `TypeError: fetch failed`(원인 `connect
// ECONNREFUSED`)로 던지고 화면은 500 을 받았다 — prod 에서 배포 한 번에 5건
// (알림 수·문제 목록). beat 의 스캔 태스크가 같은 순간을 같은 방식으로 넘긴다
// (`backend/core/tasks.py` 의 `run_scan`): 연결 실패만 몇 번 물러서서 다시 보내고,
// 그래도 안 되면 예외를 그대로 낸다 — 실패를 삼키지 않는다.
//
// **연결 거부만 다시 보낸다.** 연결이 맺어지지 않았으니 요청은 어디에도 닿지
// 않았고, POST 도 두 번 처리될 일이 없다. 연결 뒤에 끊긴 것(ECONNRESET 등)은
// 요청이 이미 처리됐을 수 있어 다시 보내지 않는다.
//
// 브라우저가 이미 떠났으면(`signal`) 기다리지 않는다.

const DEFAULT_DELAYS_MS = [250, 500, 1000, 2000] as const;

function isConnectionRefused(error: unknown): boolean {
  if (!(error instanceof TypeError)) return false;
  const cause = (error as { cause?: unknown }).cause;
  return (
    typeof cause === "object" && cause !== null && (cause as { code?: unknown }).code === "ECONNREFUSED"
  );
}

export async function retryWhileConnectionRefused(
  send: () => Promise<Response>,
  options: { delaysMs?: readonly number[]; signal?: AbortSignal } = {},
): Promise<Response> {
  const delays = options.delaysMs ?? DEFAULT_DELAYS_MS;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await send();
    } catch (error) {
      if (!isConnectionRefused(error) || attempt >= delays.length) throw error;
      await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
      if (options.signal?.aborted) throw error;
    }
  }
}
