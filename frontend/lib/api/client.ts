// 백엔드(django-ninja) 공개 표면을 부르는 타입 있는 클라이언트.
//
// `paths` 는 `@codemit/bff-client/schema` 가 백엔드의 OpenAPI 스키마에서 생성한다(FE-03, #28) —
// 손으로 쓰지 않는다. 백엔드 스키마가 바뀌면(필드 삭제·타입 변경·경로 변경) 이
// 클라이언트를 쓰는 모든 호출부에서 `tsc` 가 즉시 실패한다 — 런타임이 아니라
// 빌드타임에 드러난다.
//
// 이 클라이언트는 공개 표면(auth=None)에서만 쓴다. 서버 컴포넌트가 백엔드에
// 직접 붙는 것은 ADR-0015가 그은 경계 그대로다 — 공개 페이지는 인증이 필요
// 없으므로 BFF 프록시(ADR-0016, FE-08/#32)를 거칠 이유가 없다. **인증 구역의
// 호출은 `@codemit/bff-client`(#146) 다** — 브라우저에서 BFF 프록시를 거치고,
// 401·`detail`·목록 페이지네이션의 모양을 그 패키지가 소유한다. TanStack Query 는
// 들이지 않았다(e2e 가 「매 마운트마다 새로 읽는다」를 전제한다).
//
// 코디네이터 리뷰 지적: "서버 전용"이 주석으로만 남아 있으면 지켜지지
// 않는다. ADR-0015는 인증 구역(클라이언트 컴포넌트)이 이 파일 옆에 놓일
// 것이라고 예고하므로, 나중에 누군가 `"use client"` 컴포넌트에서 이 모듈을
// import 하는 건 시간 문제다 — 그러면 `process.env.CODEMIT_API_BASE_URL` 이
// 브라우저에서 `undefined` 가 되어 `backendBaseUrl()` 이 조용히
// `127.0.0.1:58000` 으로 떨어지고, 브라우저가 백엔드에 직접 요청을 쏘려다
// (CORS로) 막힌다 — 빌드는 통과한 채로.
//
// `server-only` 패키지의 `import "server-only"` 는 안 쓴다 — 이 패키지의
// 방어는 Next 번들러가 클라이언트 번들을 만들 때 특별 취급해주는 것에
// 기대는데, `e2e/api-types.spec.ts` 는 Next를 거치지 않고 Playwright가 Node
// 에서 이 파일을 직접 import 하므로(ADR-0017 — 시임이 실행 중인 Next 앱
// 하나라 해도, 그 앱이 부르는 라이브러리 코드 자체는 여전히 순수 TS 모듈이라
// 테스트 러너가 Node로 바로 실행한다) 그 번들러 특별 취급을 받지 못해 깨진다.
// 그 대신 `server-only` 패키지가 실제로 하는 일과 같은 검사를 직접 심는다 —
// `window` 가 있으면(=브라우저에서 평가되면) 이 모듈이 로드되는 즉시
// 크게 실패한다. Node(Next 서버 렌더링, Playwright 둘 다)에는 `window` 가
// 없으므로 이 검사는 그 쪽에서 아무 영향이 없다.
import createClient from "openapi-fetch";

import { retryWhileConnectionRefused } from "@codemit/bff-shared";
import type { paths } from "@codemit/bff-client/schema";

if (typeof window !== "undefined") {
  throw new Error(
    // SCREEN-LANGUAGE-EXCEPTION: 개발자용 불변식 크래시 메시지다 — 정상 동작에서는
    // 사용자가 볼 수 없고, 이 모듈이 실수로 브라우저에 번들되는 버그가 났을 때만
    // 개발자 콘솔에 뜬다.
    "lib/api/client.ts 는 서버 전용이다(ADR-0015) — 브라우저 번들에 들어가면 " +
      "CODEMIT_API_BASE_URL 이 undefined 가 되어 127.0.0.1:58000 으로 조용히 요청을 " +
      // SCREEN-LANGUAGE-EXCEPTION: 위와 같음 — 개발자용 크래시 메시지.
      "보내려 한다. 인증 구역(클라이언트 컴포넌트)은 BFF 프록시(FE-08, #32)를 거치는 " +
      "별도 클라이언트를 써야 한다 — 이 파일을 client component에서 import 하지 말 것.",
  );
}

// 컨테이너 안에서는 compose 네트워크 이름(backend:8000)으로 붙는다. 호스트에서
// 직접 돌릴 때는 이 값이 없어 로컬 기본값이 쓰인다 — `app/healthz/route.ts` 가
// 이미 같은 패턴을 쓴다.
function backendBaseUrl(): string {
  return process.env.CODEMIT_API_BASE_URL ?? "http://127.0.0.1:58000";
}

// 배포 중 backend 가 잠깐 없어 연결이 거부되면 몇 초 물러서서 다시 보낸다
// (`@codemit/bff-shared` 의 `connect-retry.ts`, GlitchTip 75). BFF 중계와 같은
// 함수·같은 예산이다 — 서버 컴포넌트가 백엔드에 직접 붙는 이 길에만 그 장치가
// 없어 `/contests`·sitemap 이 그 틈에 500 을 냈다. 매번 `clone()` 으로 보내야
// 본문이 있는 요청도 다시 보낼 수 있다. `fetch` 는 호출 때 읽는다 — Next 가
// 서버에서 전역 `fetch` 를 감싸 두므로 모듈을 읽는 순간의 값을 붙잡지 않는다.
export const backendClient = createClient<paths>({
  baseUrl: backendBaseUrl(),
  fetch: (request) =>
    retryWhileConnectionRefused(() => fetch(request.clone()), { signal: request.signal }),
});
