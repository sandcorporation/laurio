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
// **연결 거부만 다시 보낸다.** 연결이 맺어지지 않았으니 요청은 어디에도 닿지
// 않았고, POST 도 두 번 처리될 일이 없다. 연결 뒤에 끊긴 것(ECONNRESET 등)은
// 요청이 이미 처리됐을 수 있어 다시 보내지 않는다.
//
// **공개 앱 BFF 도 같은 틈에 같은 예외를 냈다**(2026-09-21, GlitchTip 74 — 알림 수
// 3건). 강의실에만 있던 이 함수를 공유 패키지로 옮겨 두 앱이 같은 예산을 쓴다.
//
// 브라우저가 이미 떠났으면(`signal`) 기다리지 않는다 — 예산이 길어진 만큼 이
// 확인이 **물러서기 전에도** 한 번 있어야 한다. 안 그러면 떠난 브라우저 때문에
// 8초를 마저 자고 나서야 그 사실을 안다.

export const DEFAULT_DELAYS_MS = [250, 500, 1000, 2000, 4000, 8000] as const;

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
      if (options.signal?.aborted) throw error;
      await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
      if (options.signal?.aborted) throw error;
    }
  }
}
