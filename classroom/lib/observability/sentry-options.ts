// 오류 수집(GlitchTip) 설정을 한 곳에서 만든다(2026-09-16).
//
// 받는 쪽은 sentry.io 가 아니라 우리가 띄운 GlitchTip 이다 — 수업 제출물·이름·
// 이메일을 다루는 서비스라 오류 본문이 바깥 업체로 나가지 않는 편이 낫다. SDK 는
// 같으므로 DSN 만 그쪽을 가리킨다.
//
// **DSN 이 없으면 켜지 않는다** — dev 와 CI 는 값을 주지 않으므로 SDK 가 꺼진 채로
// 돈다(네트워크를 치지 않는다).
//
// **세션 리플레이와 성능 추적은 켜지 않는다.** GlitchTip 은 리플레이를 받지 못하고,
// 리플레이는 화면을 통째로 녹화해 개인정보가 함께 나간다 — 「오류만 보낸다」가 이
// 도입의 전제다. 사용자 식별은 백엔드가 내부 id 하나로만 한다.
//
// **`sendDefaultPii: false` 만으로는 쿠키가 막히지 않는다**(#460, 2026-09-18). 서버
// 쪽 `onRequestError` 경로로 올라온 이벤트에는 요청이 그대로 붙어 있었고, 그 안에
// `codemit_access`·`codemit_refresh` JWT 가 **평문으로** 들어갔다 — refresh 토큰의
// 수명이 14일이라 GlitchTip 에 읽기 권한이 있는 누구든 그 사용자로 로그인할 수 있는
// 값이다. 자동 진단이 prod 오류를 읽다가 찾았다(GlitchTip 오류 60). 그래서 옵션
// 하나를 믿지 않고 `beforeSend` 에서 직접 지운다 — 「보내지 않는다」는 약속을 지키는
// 것은 이 함수다.
//
// 이 파일은 세 앱(frontend·operator·classroom)에 같은 내용으로 복사돼 있다 —
// 토큰·로고와 같은 방식이다(공유 패키지로 빼지 않는 이유는 CLAUDE.md
// 「프론트엔드」의 손으로 관리되는 목록 셋 참고). 여섯 진입점(앱마다
// `instrumentation.ts`·`instrumentation-client.ts`)이 전부 이 함수를 지나므로,
// 여기서 지우면 서버·브라우저 양쪽이 함께 막힌다.

// 타입만 가져온다 — 컴파일 뒤 남지 않으므로 이 모듈은 여전히 SDK 없이 테스트된다
// (`test:unit` 이 vitest 로 이 파일만 돌린다).
import type { ErrorEvent } from "@sentry/nextjs";

/** `beforeSend` 가 이벤트에서 걷어내는 요청 필드. */
type SentryRequest = {
  cookies?: unknown;
  headers?: unknown;
  data?: unknown;
  [key: string]: unknown;
};

type ScrubbableEvent = {
  request?: SentryRequest;
  [key: string]: unknown;
};

/** 이 헤더는 그대로 자격증명이거나 사용자를 특정한다 — 이름으로 지운다. */
const CREDENTIAL_HEADERS = new Set([
  "cookie",
  "set-cookie",
  "authorization",
  "proxy-authorization",
  "x-internal-token",
  "x-operator-origin",
]);

/**
 * 오류 하나를 보내기 전에 자격증명과 요청 본문을 걷어낸다.
 *
 * **지우는 쪽으로 틀렸다(allow-list 가 아니라 deny-list 가 아니다).** `cookies` 와
 * 요청 본문(`data`)은 통째로 버리고, 헤더는 **이름을 아는 것만 남긴다** — 새 헤더가
 * 생겼을 때 기본값이 「보낸다」이면 다음 누출이 조용히 또 생긴다.
 */
export function scrubSensitiveRequestData<T extends ScrubbableEvent>(event: T): T {
  const request = event.request;
  if (!request) return event;

  delete request.cookies;
  // 요청 본문에는 제출물·이름·이메일이 들어온다. 진단에 필요한 적이 없다.
  delete request.data;

  const headers = request.headers;
  if (Array.isArray(headers)) {
    request.headers = headers.filter(
      (entry) => !(Array.isArray(entry) && CREDENTIAL_HEADERS.has(String(entry[0]).toLowerCase())),
    );
  } else if (headers && typeof headers === "object") {
    for (const name of Object.keys(headers as Record<string, unknown>)) {
      if (CREDENTIAL_HEADERS.has(name.toLowerCase())) {
        delete (headers as Record<string, unknown>)[name];
      }
    }
  }

  return event;
}

/** SDK 를 켤 때 쓸 설정. DSN 이 비어 있으면 null — 그러면 켜지 않는다. */
export function buildSentryOptions(env: Record<string, string | undefined>): {
  dsn: string;
  environment: string;
  release: string | undefined;
  tracesSampleRate: number;
  sendDefaultPii: false;
  // SDK 가 요구하는 모양 그대로 내보낸다 — 우리 쪽 시그니처를 제네릭으로 두면
  // `Sentry.init` 이 받지 않는다(타입 불일치로 세 앱 typecheck 가 전부 빨개졌다).
  beforeSend: (event: ErrorEvent) => ErrorEvent;
} | null {
  const dsn = (env.NEXT_PUBLIC_SENTRY_DSN ?? "").trim();
  if (dsn === "") return null;
  const release = (env.NEXT_PUBLIC_SENTRY_RELEASE ?? "").trim();
  return {
    dsn,
    environment: (env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "").trim() || "development",
    release: release === "" ? undefined : release,
    tracesSampleRate: 0,
    sendDefaultPii: false,
    // SDK 의 `ErrorEvent` 는 색인 시그니처가 없어 위 제네릭 제약을 만족하지 않는다 —
    // 경계에서 한 번만 맞춰 주고, 걷어내는 논리는 그대로 그 함수 하나다.
    beforeSend: (event: ErrorEvent) =>
      scrubSensitiveRequestData(event as unknown as ScrubbableEvent) as unknown as ErrorEvent,
  };
}
