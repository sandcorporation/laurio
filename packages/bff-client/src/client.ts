// 인증 구역(BFF 프록시 `/api/backend/*`)을 부르는 브라우저 쪽 클라이언트 (#146, #122).
//
// 앱이 주입하는 것은 인증 방식뿐이다:
//
// - `revive` — 401 을 만났을 때 세션을 되살리는 시도(공개 앱: `/api/auth/session` 이 조용히
//   리프레시한다). 없으면(운영자 앱 — Django 세션은 조용한 갱신이 없다) 되살리지 않는다.
// - `onUnauthorized` — 되살려도 401 이면 부른다. 조회든 변경이든 「세션이 죽었다」 한 가지 뜻이라
//   항상 같은 곳으로 간다(`/login?next=현재 경로`).
//
// 되살리기는 **단일 비행**이다. 브라우저는 하나의 JS 실행 컨텍스트라, 같은 페이지에서 동시에 401 을
// 만난 호출들이 되살리기 시도 하나를 공유하고 그 결과를 기다렸다가 각자 한 번 더 시도한다 —
// 리프레시 토큰이 1회용이라(backend accounts/tokens.py) 여러 시도가 경합하면 늦게 도착한 것이 이미
// 소모된 토큰으로 401 을 받는다. 한 번으로 부족할 수 있어(Set-Cookie 가 쿠키 저장소에 반영되는
// 시점과 다음 요청 사이에 보장된 순서가 없다) 짧게 쉬었다 몇 차례 더 시도한다. 예전
// `frontend/lib/auth/client-fetch.ts` 의 로직이 그대로 여기로 왔다.

import createClient from "openapi-fetch";

import {
  type ApiFailure,
  type ApiResult,
  FALLBACK_DETAIL,
  codeForStatus,
  normalizeDetail,
} from "./result";
import type { paths } from "./schema.gen";

export interface BffClientOptions {
  /** 되살려도 401 일 때 — 로그인으로 보내는 자리. */
  onUnauthorized: () => void;
  /** 세션 되살리기 시도. 없으면 401 은 곧바로 onUnauthorized 다. */
  revive?: () => Promise<unknown>;
  /** 되살리기·재시도를 포함한 최대 시도 횟수. */
  maxAttempts?: number;
}

/** `RequestInit` 에 이 클라이언트만 아는 스위치 하나를 더한 것. */
export interface BffRequestInit extends RequestInit {
  /** 401 을 「세션이 죽었다」가 아니라 **정상적인 답**으로 받는다 — 로그인하지 않은 방문자가
   * 정답인 자리(공개 페이지 헤더의 세션 확인)에서 쓴다. 되살리기·재시도는 그대로 하되(로그인한
   * 사용자가 만료된 액세스로 온 경우를 흡수해야 한다) `onUnauthorized` 는 부르지 않는다 —
   * 부르면 로그인 페이지가 자기 자신으로 리다이렉트하며 로그인 흐름을 끊는다(실제로 재현됐다). */
  unauthorizedIsAnswer?: boolean;
}

export interface BffClient {
  /** fetch 그대로 — 401 이면 되살리기·재시도를 거치고, 그래도 401 이면 onUnauthorized 를 부른다. */
  fetch(input: string | Request, init?: BffRequestInit): Promise<Response>;
  /** JSON 을 기대하는 호출 — 결과는 항상 `ApiResult`. 본문 없는 2xx(204 등)는 `data` 가 undefined. */
  request<T>(path: string, init?: BffRequestInit): Promise<ApiResult<T>>;
  /** `request` 의 GET 형 — `cache: "no-store"` 가 기본이다(매 마운트마다 새로 읽는다). */
  get<T>(path: string, init?: BffRequestInit): Promise<ApiResult<T>>;
  /** `request` 의 JSON POST 형. */
  post<T>(path: string, body?: unknown, init?: BffRequestInit): Promise<ApiResult<T>>;
  /** 경로·파라미터·응답까지 타입이 붙은 openapi-fetch 클라이언트. 스키마의 `/api/...` 경로를 BFF
   * 프록시 경로로 옮겨 같은 fetch(되살리기·401 처리)로 보낸다 — 경로 오타와 사라진 필드가 `tsc` 에
   * 잡힌다. */
  api: ReturnType<typeof createClient<paths>>;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 스키마 경로(`/api/contests/mine`)를 BFF 프록시 경로(`/api/backend/contests/mine`)로 옮긴다. */
export function toBffPath(schemaPath: string): string {
  if (schemaPath.startsWith("/api/backend/")) return schemaPath;
  if (schemaPath.startsWith("/api/")) return `/api/backend/${schemaPath.slice("/api/".length)}`;
  return schemaPath;
}

export function createBffClient(options: BffClientOptions): BffClient {
  const maxAttempts = options.maxAttempts ?? 3;
  let inflightRevive: Promise<void> | null = null;

  function reviveOnce(): Promise<void> {
    const revive = options.revive;
    if (!revive) return Promise.resolve();
    if (inflightRevive) return inflightRevive;
    inflightRevive = Promise.resolve()
      .then(() => revive())
      .then(
        () => undefined,
        () => undefined,
      )
      .finally(() => {
        inflightRevive = null;
      });
    return inflightRevive;
  }

  async function bffFetch(input: string | Request, init?: BffRequestInit): Promise<Response> {
    // Request 로 들어온 경우 매 시도마다 복제본을 쓴다 — 원본의 본문 스트림이 소비되면 재시도가
    // 빈 본문을 보내게 된다.
    const attempt = () => (typeof input === "string" ? fetch(input, init) : fetch(input.clone()));

    let response = await attempt();
    if (options.revive) {
      for (let tries = 1; response.status === 401 && tries < maxAttempts; tries += 1) {
        await reviveOnce();
        response = await attempt();
        if (response.status === 401) await sleep(75 * tries);
      }
    }
    if (response.status === 401 && !init?.unauthorizedIsAnswer) options.onUnauthorized();
    return response;
  }

  async function request<T>(path: string, init?: BffRequestInit): Promise<ApiResult<T>> {
    let response: Response;
    try {
      response = await bffFetch(path, init);
    } catch {
      return { ok: false, status: 0, code: "network", detail: FALLBACK_DETAIL };
    }

    if (response.ok) {
      const text = await response.text().catch(() => "");
      if (text === "") return { ok: true, status: response.status, data: undefined as T };
      try {
        return { ok: true, status: response.status, data: JSON.parse(text) as T };
      } catch {
        return { ok: false, status: response.status, code: "malformed", detail: FALLBACK_DETAIL };
      }
    }

    const body: unknown = await response.json().catch(() => undefined);
    const raw =
      body !== null && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
    const failure: ApiFailure = {
      ok: false,
      status: response.status,
      code: codeForStatus(response.status),
      detail: normalizeDetail(raw),
    };
    return failure;
  }

  const api = createClient<paths>({
    baseUrl: "",
    fetch: (request_: Request) => {
      const url = new URL(request_.url);
      return bffFetch(new Request(toBffPath(url.pathname) + url.search, request_));
    },
  });

  return {
    fetch: bffFetch,
    request,
    get: (path, init) => request(path, { cache: "no-store", ...init }),
    post: (path, body, init) =>
      request(path, {
        method: "POST",
        ...init,
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
        body: JSON.stringify(body ?? {}),
      }),
    api,
  };
}
