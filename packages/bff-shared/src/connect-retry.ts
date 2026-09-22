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
// **첫 예산 3.75초는 그 틈보다 짧았다**(2026-09-20, GlitchTip 64 — 같은 예외가
// 같은 모양으로 다시 올라왔다, 문제 목록 4건). 틈의 길이는 backend 컨테이너의
// 기동 명령이 정한다: 새 컨테이너는 `migrate` 와 `collectstatic` 을 마치고
// gunicorn 워커 넷이 뜬 **뒤에야** 8000 을 듣기 시작한다
// (`docker/compose.prod.yaml`). `deploy.sh` 자신도 그래서 backend 의 응답을
// 150초까지 기다린다 — 이 저장소가 그 틈을 「한순간」으로 본 적은 없다.
// GlitchTip 64 의 네 건에서 실제로 잰 하한은 **5.4초**다(첫 건이 16:09:06.0 에
// 시작해 09.8 에 포기, 마지막 건이 11.4 에 포기 — 그 사이 내내 거부됐다).
// 그래서 예산을 `run_scan` 이 쓰는 것과 같은 자릿수(2·4·8초, 합쳐 약 14초)까지
// 늘렸다. 여전히 상한은 아니다 — 이보다 긴 틈이면 예외를 그대로 낸다.
//
// **연결 거부(와 이름이 안 풀린 것)만 다시 보낸다.** 연결이 맺어지지 않았으니 요청은 어디에도 닿지
// 않았고, POST 도 두 번 처리될 일이 없다. 연결 뒤에 끊긴 것(ECONNRESET 등)은
// 요청이 이미 처리됐을 수 있어 다시 보내지 않는다.
//
// **이름이 풀리지 않는 것도 같은 틈이다**(2026-09-21, GlitchTip 64 가 예산을 늘린
// 뒤에 다시 올라왔다 — 알림 수, 원인 `getaddrinfo ENOTFOUND backend`). compose 가
// 옛 컨테이너를 지우고 새 것을 만드는 사이에는 포트가 닫힌 것이 아니라 `backend`
// 라는 이름 자체가 도커 DNS 에 없다. 이름이 안 풀렸으니 연결도 맺어지지 않았고,
// 그래서 연결 거부와 똑같이 다시 보내도 된다.
//
// **「지금은 답할 수 없다」도 같은 틈이다**(2026-09-22, GlitchTip 74 가 ENOTFOUND 를
// 더한 뒤에 다시 올라왔다 — 공개 앱 알림 수, 원인 `getaddrinfo EAI_AGAIN backend`).
// 그 순간 도커 내장 DNS 가 「없다」 대신 「일시적 실패」로 답했다. 이것도 이름이
// 안 풀려 연결이 맺어지기 전이라 다시 보내도 된다.
//
// **공개 앱 BFF 도 같은 틈에 같은 예외를 냈다**(2026-09-21, GlitchTip 74 — 알림 수
// 3건). 강의실에만 있던 이 함수를 공유 패키지로 옮겨 두 앱이 같은 예산을 쓴다.
//
// 브라우저가 이미 떠났으면(`signal`) 기다리지 않는다 — 예산이 길어진 만큼 이
// 확인이 **물러서기 전에도** 한 번 있어야 한다. 안 그러면 떠난 브라우저 때문에
// 8초를 마저 자고 나서야 그 사실을 안다.

export const DEFAULT_DELAYS_MS = [250, 500, 1000, 2000, 4000, 8000] as const;

// 연결이 맺어지기 전에 난 실패만 — 요청이 어디에도 닿지 않았다는 것이 확실한 것.
const NOT_CONNECTED_CODES: ReadonlySet<unknown> = new Set([
  "ECONNREFUSED",
  "ENOTFOUND",
  "EAI_AGAIN",
]);

function isConnectionRefused(error: unknown): boolean {
  if (!(error instanceof TypeError)) return false;
  const cause = (error as { cause?: unknown }).cause;
  return (
    typeof cause === "object" && cause !== null && NOT_CONNECTED_CODES.has((cause as { code?: unknown }).code)
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
      if (options.signal?.aborted) throw error;
      await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
      if (options.signal?.aborted) throw error;
    }
  }
}
