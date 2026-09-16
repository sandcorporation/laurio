// 백엔드의 세션 확인 응답을 화면이 쓸 상태로 옮긴다(2026-09-16).
//
// **403 을 401 로 옮기는 자리다.** 운영자였던 계정이 참가자로 내려가면(또는 애초에
// 운영자가 아닌 계정의 세션이 남아 있으면) 백엔드는 `/api/operator/me` 에
// 403「Operator 권한이 필요합니다」를 낸다 — 「너인 건 알겠는데 권한이 없다」와
// 「너를 모르겠다」를 가르는 것은 ADR-0018 의 의도이므로 백엔드는 그대로 둔다.
//
// 그러나 **세션 확인에서만은** 그 둘이 같은 뜻이다: 이 세션으로는 운영자 구역에
// 아무것도 할 수 없다. 그래서 여기서 401 로 옮겨, 401 에서만 도는 로그인 유도
// (`lib/bff/client.ts`)와 쿠키 정리가 함께 돌게 한다. 예전에는 403 이 그 둘 어디에도
// 걸리지 않아 화면이 아무것도 그리지 않고 멈췄다 — 흰 화면이었다.
//
// **다른 요청의 403 은 옮기지 않는다.** 일반 등급 운영자가 상위 등급 전용 기능을
// 부를 때도 403 이고(#45), 그것까지 401 로 옮기면 그 사람이 로그아웃된다.

export interface SessionOutcome {
  /** 화면에 돌려줄 상태 코드. */
  status: number;
  /** 세션 쿠키를 지울 것인가 — 그 세션으로는 더 할 수 있는 일이 없을 때만. */
  clearCookie: boolean;
  /** 옮긴 이유를 화면에 전할 문구(있을 때만). */
  detail?: string;
}

export function sessionOutcomeFor(backendStatus: number): SessionOutcome {
  if (backendStatus === 401) return { status: 401, clearCookie: true };
  if (backendStatus === 403) {
    return {
      status: 401,
      clearCookie: true,
      detail: "운영자 권한이 없는 계정입니다. 다시 로그인해주세요.",
    };
  }
  return { status: backendStatus, clearCookie: false };
}
