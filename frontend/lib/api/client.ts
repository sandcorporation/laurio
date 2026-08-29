// 백엔드(django-ninja) 공개 표면을 부르는 타입 있는 클라이언트.
//
// `paths` 는 `schema.gen.ts` 가 백엔드의 OpenAPI 스키마에서 생성한다(FE-03, #28) —
// 손으로 쓰지 않는다. 백엔드 스키마가 바뀌면(필드 삭제·타입 변경·경로 변경) 이
// 클라이언트를 쓰는 모든 호출부에서 `tsc` 가 즉시 실패한다 — 런타임이 아니라
// 빌드타임에 드러난다.
//
// 이 클라이언트는 공개 표면(auth=None)에서만 쓴다. 서버 컴포넌트가 백엔드에
// 직접 붙는 것은 ADR-0015가 그은 경계 그대로다 — 공개 페이지는 인증이 필요
// 없으므로 BFF 프록시(ADR-0016, FE-08/#32)를 거칠 이유가 없다. 인증 구역의
// 호출은 이후 티켓이 이 자리에 별도 클라이언트로 추가한다(BFF 프록시를 거치고,
// TanStack Query 를 쓴다) — 여기서 앞서 만들지 않는다.
import createClient from "openapi-fetch";

import type { paths } from "./schema.gen";

// 컨테이너 안에서는 compose 네트워크 이름(backend:8000)으로 붙는다. 호스트에서
// 직접 돌릴 때는 이 값이 없어 로컬 기본값이 쓰인다 — `app/healthz/route.ts` 가
// 이미 같은 패턴을 쓴다.
function backendBaseUrl(): string {
  return process.env.LAURIO_API_BASE_URL ?? "http://127.0.0.1:58000";
}

export const backendClient = createClient<paths>({ baseUrl: backendBaseUrl() });
