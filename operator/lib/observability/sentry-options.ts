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
// **남의 코드가 던진 것도 보내지 않는다**(#471, 2026-09-20). 브라우저 확장의 콘텐츠
// 스크립트가 던진 처리되지 않은 promise 거절을 우리 전역 핸들러가 잡아 강의실
// 프로젝트로 보냈고, 하루 만에 prod 미해결 목록이 그 예외 하나로 통째로 찼다
// (GlitchTip 오류 62·63, 합쳐 14건). 우리 화면은 멀쩡했다 — 그대로 두면 진짜 5xx 가
// 소음에 묻힌다(백엔드가 의도한 4xx 를 버리는 것과 같은 이유다).
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

/**
 * 이 SDK 가 어느 쪽에서 도는가. 진입점이 직접 말한다 — 이벤트를 보고 추측하지
 * 않는다(`platform` 은 SDK 버전에 따라 `beforeSend` 시점에 아직 비어 있을 수
 * 있고, 서버 이벤트를 브라우저로 잘못 보면 아래 제3자 판정이 **우리 서버 오류를**
 * 버린다). 새 진입점이 생기면 이 인자를 적기 전까지 타입이 빨갛다.
 */
export type SentryRuntime = "browser" | "server";

/**
 * 이 헤더는 그대로 자격증명이거나 사용자를 특정한다 — 이름으로 지운다(소문자).
 * 백엔드 `core.observability._CREDENTIAL_HEADERS` 와 같은 목록이다.
 *
 * **차단 목록이라 목록에 없는 헤더는 보내진다.** 자격증명을 싣는 헤더를 새로
 * 만들면 이 목록(세 앱의 사본 셋)과 백엔드 목록에 함께 더한다 — 더하지 않으면
 * 그 값이 GlitchTip 에 평문으로 실린다.
 */
const CREDENTIAL_HEADERS = new Set([
  "cookie",
  "set-cookie",
  "authorization",
  "proxy-authorization",
  "x-internal-token",
  "x-operator-origin",
]);

/**
 * 우리 브라우저 번들의 프레임. 정규화된 `app:///_next/…` 와 정규화 전의
 * `https://…/_next/…` 를 함께 본다.
 *
 * **`app:///` 로 시작하는 것만으로는 우리 코드가 아니다** — 그 접두어는 SDK 가
 * 오리진을 떼어낸 흔적이다(`clientNormalizationIntegration` 이
 * `filename.replace(new URL(filename).origin, "app://")` 를 한다). 확장의
 * `chrome-extension://<id>/executors/200.js` 도 같은 방식으로
 * `app:///executors/200.js` 가 된다 — #471 이 그 값이었다. 우리 빌드가 내보내는
 * 파일은 전부 `/_next/` 아래다.
 */
const OUR_BROWSER_FRAME = /\/_next\//;

/**
 * 스택이 **전부** 우리 번들 밖인 브라우저 오류인가.
 *
 * **좁게 막는다.** 「우리 프레임이 하나도 없으면 버린다」로 넓히면 스택이 아예
 * 없는 우리 오류(교차 오리진의 `Script error.`, 잘린 스택)까지 함께 사라진다 —
 * 오류 수집의 기본 실패 모양이 「조용히 아무 일도 안 일어난다」라 그 대가가 가장
 * 위험하다. 그래서 프레임이 하나도 없으면 **보낸다**, 이름 없는 프레임(익명 함수
 * 등)이 섞여 있어도 **보낸다**. 판정이 확실한 자리만 버린다.
 */
export function isThirdPartyBrowserError(event: ScrubbableEvent): boolean {
  const values = (event as { exception?: { values?: unknown } }).exception?.values;
  if (!Array.isArray(values)) return false;

  const frames = values.flatMap((value) => {
    const candidate = (value as { stacktrace?: { frames?: unknown } } | null)?.stacktrace?.frames;
    return Array.isArray(candidate) ? candidate : [];
  });
  if (frames.length === 0) return false;

  return frames.every((frame) => {
    const filename = (frame as { filename?: unknown } | null)?.filename;
    return typeof filename === "string" && !OUR_BROWSER_FRAME.test(filename);
  });
}

/**
 * 오류 하나를 보내기 전에 자격증명과 요청 본문을 걷어낸다.
 *
 * `cookies` 와 요청 본문(`data`)은 통째로 버리고, 헤더는 **차단 목록**이다 —
 * `CREDENTIAL_HEADERS` 에 든 이름만(대소문자 무시) 지우고 나머지 헤더는 그대로
 * 보낸다. 백엔드 `core.observability.scrub_secrets`(#590)와 같은 방식·같은 목록이다.
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
export function buildSentryOptions(
  env: Record<string, string | undefined>,
  runtime: SentryRuntime,
): {
  dsn: string;
  environment: string;
  release: string | undefined;
  tracesSampleRate: number;
  sendDefaultPii: false;
  // SDK 가 요구하는 모양 그대로 내보낸다 — 우리 쪽 시그니처를 제네릭으로 두면
  // `Sentry.init` 이 받지 않는다(타입 불일치로 세 앱 typecheck 가 전부 빨개졌다).
  // null 을 돌려주면 그 이벤트는 보내지 않는다.
  beforeSend: (event: ErrorEvent) => ErrorEvent | null;
} | null {
  const dsn = (env.CODEMIT_PUBLIC_SENTRY_DSN ?? "").trim();
  if (dsn === "") return null;
  const release = (env.CODEMIT_PUBLIC_SENTRY_RELEASE ?? "").trim();
  return {
    dsn,
    environment: (env.CODEMIT_PUBLIC_SENTRY_ENVIRONMENT ?? "").trim() || "development",
    release: release === "" ? undefined : release,
    tracesSampleRate: 0,
    sendDefaultPii: false,
    // SDK 의 `ErrorEvent` 는 색인 시그니처가 없어 위 제네릭 제약을 만족하지 않는다 —
    // 경계에서 한 번만 맞춰 주고, 걷어내는 논리는 그대로 그 함수 하나다.
    beforeSend: (event: ErrorEvent) => {
      const scrubbed = scrubSensitiveRequestData(event as unknown as ScrubbableEvent);
      // 제3자 판정은 브라우저에서만 한다 — 서버 이벤트의 프레임은 `/_next/` 가 아닌
      // 곳(`.next/server`·`node_modules`)에 있어서, 여기서 함께 보면 우리 서버 오류가
      // 통째로 버려진다.
      if (runtime === "browser" && isThirdPartyBrowserError(scrubbed)) return null;
      return scrubbed as unknown as ErrorEvent;
    },
  };
}
