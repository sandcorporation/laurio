"use client";

// 포트원(PortOne) V2 브라우저 SDK로 실제 본인확인 인증창을 띄운다(#85, ADR-0007).
//
// 서버(verification.adapters.PortOneV2VerificationAdapter)는 이 함수가 돌려주는
// identityVerificationId로 서버-투-서버 조회를 한다 — 콜백 URL이 없는 모델이라
// redirectUrl은 인증창이 결과를 되돌려줄 브라우저 주소일 뿐, 서버가 그 경로로
// 뭔가를 받지는 않는다(MinIO가 dev에서 이미 실물인 것과 같은 모양 — 도메인·TLS
// 없이 dev에서 끝까지 걸을 수 있다).
//
// identityVerificationId는 클라이언트가 스스로 짓지 않는다 — `POST
// /verification/start`로 서버가 발급해 요청자에게 귀속시킨 값을 그대로 쓴다
// (#85 코드리뷰 지적 1). 클라이언트가 스스로 지으면 그 값이 리다이렉트 URL·
// 브라우저 히스토리로 노출됐을 때, 전혀 다른 계정이 그 값을 그대로 제출해
// 원래 발급받은 사람의 CI/DI로 VERIFIED가 될 수 있다 — 서버가 "요청자 본인이
// 발급받은 값인가"를 확인해야만 막을 수 있는 문제라, 발급도 서버가 해야 한다.
//
// 이 모듈은 NEXT_PUBLIC_PORTONE_STORE_ID/NEXT_PUBLIC_PORTONE_CHANNEL_KEY가 설정된
// 환경에서만 쓰인다 — 기본 dev/e2e는 이 값들이 비어 있으므로 호출부(각 화면의
// "실제 본인확인하기" 버튼)가 렌더링 자체를 건너뛴다. 기존 Fake 어댑터 기반
// dev 버튼("지금 본인확인하기(dev)")은 이 모듈과 무관하게 그대로 남는다.

import { sessionFetch } from "@/lib/auth/client-fetch";

const SDK_SRC = "https://cdn.portone.io/v2/browser-sdk.js";

type PortOneIdentityVerificationResponse = {
  code?: string;
  message?: string;
  identityVerificationId: string;
};

declare global {
  interface Window {
    PortOne?: {
      requestIdentityVerification: (params: {
        storeId: string;
        channelKey: string;
        identityVerificationId: string;
        redirectUrl?: string;
      }) => Promise<PortOneIdentityVerificationResponse>;
    };
  }
}

let sdkLoadPromise: Promise<void> | null = null;

/**
 * PortOne 브라우저 SDK 스크립트를 한 번만 불러온다.
 *
 * 실패한 시도를 캐시하지 않는다(#85 코드리뷰 지적 8) — 이전 구현은 실패한
 * `sdkLoadPromise`를 그대로 캐시에 남겨 재시도 자체를 영구히 막았다. 또한
 * "이미 있는 script 태그"에 뒤늦게 리스너를 다는 분기를 두지 않는다 — script
 * 태그는 load/error 이벤트를 한 번만 쏘므로, 그 이벤트가 이미 지나간 뒤에
 * 리스너를 달면 영원히 settle되지 않는 Promise가 만들어질 수 있었다. 이
 * 모듈이 스스로 만든 script 태그만 추적하므로 그 시나리오 자체가 없다.
 */
function loadPortOneSdk(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("PortOne SDK는 브라우저에서만 로드할 수 있습니다."));
  }
  if (window.PortOne) return Promise.resolve();
  if (sdkLoadPromise) return sdkLoadPromise;

  const promise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SDK_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // 실패한 태그를 지워야 다음 재시도가 새 script 태그로 처음부터
      // 다시 시도한다 — 브라우저는 실패한 src를 다시 요청하지 않을 수 있다.
      script.remove();
      reject(new Error("PortOne SDK를 불러오지 못했습니다."));
    };
    document.head.appendChild(script);
  });

  sdkLoadPromise = promise;
  // 성공하든 실패하든, 다음 호출이 이번 시도의 결과를 그대로 재사용하지
  // 않도록 캐시를 비운다 — 실패 후 재시도가 가능해야 하고, 성공 뒤에는 위의
  // `window.PortOne` 체크가 캐시보다 먼저 확인되므로 비워도 안전하다.
  promise.finally(() => {
    if (sdkLoadPromise === promise) sdkLoadPromise = null;
  });
  return promise;
}

async function fetchServerIssuedIdentityVerificationId(): Promise<string> {
  const res = await sessionFetch("/api/backend/verification/start", { method: "POST" });
  if (!res.ok) {
    throw new Error("본인확인 요청 발급에 실패했습니다.");
  }
  const body = (await res.json()) as { identity_verification_id: string };
  return body.identity_verification_id;
}

/**
 * 실제 인증창을 띄우고, 인증이 끝나면 identityVerificationId를 돌려준다.
 * 이 값을 그대로 `POST /api/verification/verify`의 `verification_token`으로
 * 보내면 서버가 포트원에 서버-투-서버로 조회해 완료 처리한다.
 *
 * 데스크톱은 팝업 창이 끝나면 이 함수가 돌려주는 Promise가 그대로 resolve된다.
 * 모바일은 PortOne SDK가 팝업 대신 전체 페이지 리다이렉트로 인증창을 여는데,
 * 그러면 이 JS 실행 컨텍스트 자체가 사라져 이 Promise는 영원히 resolve되지
 * 않는다(#85 코드리뷰 지적 3) — 대신 리다이렉트로 돌아온 새 페이지 로드에서
 * `consumeRedirectVerificationResult`를 불러야 한다.
 */
export async function requestPortOneIdentityVerification(params: {
  storeId: string;
  channelKey: string;
}): Promise<string> {
  const identityVerificationId = await fetchServerIssuedIdentityVerificationId();

  await loadPortOneSdk();
  if (!window.PortOne) {
    throw new Error("PortOne SDK가 초기화되지 않았습니다.");
  }

  const response = await window.PortOne.requestIdentityVerification({
    storeId: params.storeId,
    channelKey: params.channelKey,
    identityVerificationId,
    redirectUrl: window.location.href,
  });

  if (response.code) {
    throw new Error(response.message || "본인확인 창에서 오류가 발생했습니다.");
  }

  return response.identityVerificationId;
}

export type PortOneRedirectResult =
  | { status: "success"; identityVerificationId: string }
  | { status: "failure"; message: string };

/**
 * 모바일에서 PortOne 인증창이 전체 페이지 리다이렉트로 돌아왔는지 확인한다
 * (#85 코드리뷰 지적 3). `redirectUrl`로 돌아온 요청은 쿼리스트링에
 * identityVerificationId(성공)나 code/message(실패)를 싣고 있다 — 있으면 그
 * 결과를 소비하고 쿼리스트링을 지운 뒤(새로고침 없이, 다시 마운트돼도 같은
 * 결과를 중복 처리하지 않도록) 돌려준다. 리다이렉트 복귀가 아니면(쿼리
 * 파라미터가 없으면) null이다 — 데스크톱 팝업 흐름에서는 절대 호출될 일이
 * 없지만, 모바일에서는 화면이 마운트될 때마다 이걸로 복귀 여부를 확인해야
 * `requestPortOneIdentityVerification`이 돌려주는 Promise가 오지 않는 경로를
 * 보완할 수 있다.
 */
export function consumeRedirectVerificationResult(): PortOneRedirectResult | null {
  if (typeof window === "undefined") return null;

  const params = new URLSearchParams(window.location.search);
  const identityVerificationId = params.get("identityVerificationId");
  if (!identityVerificationId) return null;

  const code = params.get("code");
  const message = params.get("message");

  params.delete("identityVerificationId");
  params.delete("code");
  params.delete("message");
  const rest = params.toString();
  const nextUrl = window.location.pathname + (rest ? "?" + rest : "") + window.location.hash;
  window.history.replaceState(null, "", nextUrl);

  if (code) {
    return { status: "failure", message: message || "본인확인 창에서 오류가 발생했습니다." };
  }
  return { status: "success", identityVerificationId };
}

/** 실물 본인확인 버튼을 렌더링할지 결정한다 — 둘 다 있어야 인증창을 열 수 있다. */
export function getPortOneBrowserConfig(): { storeId: string; channelKey: string } | null {
  const storeId = process.env.NEXT_PUBLIC_PORTONE_STORE_ID;
  const channelKey = process.env.NEXT_PUBLIC_PORTONE_CHANNEL_KEY;
  if (!storeId || !channelKey) return null;
  return { storeId, channelKey };
}
