// 세션이 죽었을 때 로그인으로 보내는 이동 — 세 앱(공개·운영자·강의실)이 똑같이 쓰던 `goToLogin` 을
// 한 곳에 둔다(#501).
//
// **짧은 창 안의 두 번째 이동은 건너뛴다.** 한 화면의 백엔드 요청 둘(예: 강의실의 「내 클래스」와
// 헤더 알림 벨)이 함께 401 을 받으면 둘 다 `onUnauthorized` 를 불러 `location.replace` 를 두 번 했고,
// 두 번째가 첫 번째를 취소했다. 사용자는 같은 로그인 화면에 닿지만 취소된 이동이 하나 남아, 이동을
// 기다리는 쪽(e2e 의 `waitForURL`)이 `ERR_ABORTED` 를 받았다.
//
// 「한 번만」이 아니라 「창 안에서 한 번」인 이유: 페이지 이동 없이 다시 로그인하는 경로가 있거나
// 이동이 중간에 취소돼 페이지가 그대로 남으면, 영원히 막힌 플래그는 다음 세션 만료 때 이동을 아예
// 막는다. 보통은 `replace` 가 페이지를 내려 이 모듈 상태도 함께 사라지므로 창은 그 드문 경우만을
// 위한 것이다.

export interface LoginNavigator {
  /** 로그인 뒤 돌아올 자리 — `?next=` 로 실어 보낸다. */
  currentPath(): string;
  replace(url: string): void;
}

export interface LoginRedirectOptions {
  navigator?: LoginNavigator;
  now?: () => number;
  /** 이 시간(ms) 안의 두 번째 이동은 건너뛴다. */
  windowMs?: number;
}

const DEFAULT_WINDOW_MS = 3000;

const windowNavigator: LoginNavigator = {
  currentPath: () => window.location.pathname + window.location.search,
  replace: (url) => window.location.replace(url),
};

export function createLoginRedirect(options: LoginRedirectOptions = {}): () => void {
  const navigator = options.navigator ?? windowNavigator;
  const now = options.now ?? Date.now;
  const windowMs = options.windowMs ?? DEFAULT_WINDOW_MS;
  let lastRedirectAt: number | null = null;

  return function goToLogin(): void {
    if (navigator === windowNavigator && typeof window === "undefined") return;
    const at = now();
    if (lastRedirectAt !== null && at - lastRedirectAt < windowMs) return;
    lastRedirectAt = at;
    navigator.replace(`/login?next=${encodeURIComponent(navigator.currentPath())}`);
  };
}
