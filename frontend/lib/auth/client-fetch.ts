"use client";

// 세션이 필요한 BFF 호출의 클라이언트 쪽 래퍼 (FE-07 #32).
//
// lib/auth/session.ts가 서버(Next 라우트 핸들러) 안에서 액세스 만료를 조용히
// 리프레시하지만, 그 서버 쪽 단일 비행(lib/auth/refresh.ts의 inflightRefresh
// Map)은 "같은 프로세스가 우연히 처리한 요청들" 사이에서만 유효하다 — 실제
// 배포에서 요청이 서로 다른 인스턴스로 갈 수 있고, Next dev 서버조차 컴파일
// 경계에서 라우트 모듈을 새로 평가해 그 캐시가 비워지는 것을 직접 재현해
// 확인했다. 그래서 여러 화면 요소가 동시에 만료를 발견하면 리프레시 토큰이
// 1회용이라(accounts/tokens.py) 뒤늦게 도착한 요청이 이미 소모된 토큰으로
// 401을 받을 수 있다.
//
// 진짜 방어선은 여기다: 브라우저는 항상 하나의 JS 실행 컨텍스트라는 사실을
// 이용해, 같은 페이지에서 동시에 401을 만난 호출들이 "세션을 다시 확인하는"
// 시도 하나를 공유하게 만든다. 그 시도(reviveSession)가 끝나길 다 같이 기다린
// 뒤에야 각자 원래 요청을 한 번 더 시도한다 — 실제로 어느 호출이 리프레시를
// 성사시켰는지는 상관없다. 쿠키는 하나의 브라우저 쿠키 저장소에 쌓이므로,
// 누가 먼저 갱신했든 그 다음 요청은 전부 최신 쿠키를 그대로 실어 보낸다.
let inflightRevive: Promise<void> | null = null;

function reviveSession(): Promise<void> {
  if (inflightRevive) return inflightRevive;

  inflightRevive = fetch("/api/auth/session", { cache: "no-store" })
    .then(() => undefined)
    .catch(() => undefined)
    .finally(() => {
      inflightRevive = null;
    });

  return inflightRevive;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const MAX_ATTEMPTS = 3;

/**
 * fetch를 그대로 감싸되, 401을 받으면 세션을 되살려보고 다시 시도한다. 동시에
 * 여러 곳에서 401을 만나도 그 순간의 세션 되살리기 시도는 하나만 나간다
 * (reviveSession의 단일 비행) — 나머지는 그 결과를 기다렸다가 재시도한다.
 *
 * 한 번의 되살리기·재시도로 부족할 수 있다 — 동시에 경합하던 다른 호출이
 * "먼저 리프레시를 성사시킨" 응답의 Set-Cookie가 브라우저 쿠키 저장소에 실제로
 * 반영되는 시점과, 그 직후 새로 시작되는 되살리기 요청이 그 쿠키를 실어 보내는
 * 시점 사이에는 보장된 순서가 없다(둘 다 "지금 막" 일어난 별개의 비동기
 * 이벤트다). 그래서 실패하면 짧게 쉬었다가 다시 되살리기를 시도한다 — 몇 차례
 * 안에 가장 먼저 성사된 리프레시의 쿠키가 안정적으로 자리잡는다.
 */
export async function sessionFetch(path: string, init?: RequestInit): Promise<Response> {
  let response = await fetch(path, init);

  for (let attempt = 1; response.status === 401 && attempt < MAX_ATTEMPTS; attempt += 1) {
    await reviveSession();
    response = await fetch(path, init);
    if (response.status === 401) await sleep(75 * attempt);
  }

  return response;
}
