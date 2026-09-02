"use client";

// 포트원(PortOne) V2 브라우저 SDK로 실제 본인확인 인증창을 띄운다(#85, ADR-0007).
//
// 서버(verification.adapters.PortOneV2VerificationAdapter)는 이 함수가 돌려주는
// identityVerificationId로 서버-투-서버 조회를 한다 — 콜백 URL이 없는 모델이라
// redirectUrl은 인증창이 결과를 되돌려줄 브라우저 주소일 뿐, 서버가 그 경로로
// 뭔가를 받지는 않는다(MinIO가 dev에서 이미 실물인 것과 같은 모양 — 도메인·TLS
// 없이 dev에서 끝까지 걸을 수 있다).
//
// 이 모듈은 NEXT_PUBLIC_PORTONE_STORE_ID/NEXT_PUBLIC_PORTONE_CHANNEL_KEY가 설정된
// 환경에서만 쓰인다 — 기본 dev/e2e는 이 값들이 비어 있으므로 호출부(각 화면의
// "실제 본인확인하기" 버튼)가 렌더링 자체를 건너뛴다. 기존 Fake 어댑터 기반
// dev 버튼("지금 본인확인하기(dev)")은 이 모듈과 무관하게 그대로 남는다.

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

function loadPortOneSdk(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("PortOne SDK는 브라우저에서만 로드할 수 있습니다."));
  }
  if (window.PortOne) return Promise.resolve();
  if (sdkLoadPromise) return sdkLoadPromise;

  sdkLoadPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${SDK_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("PortOne SDK를 불러오지 못했습니다.")));
      return;
    }
    const script = document.createElement("script");
    script.src = SDK_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("PortOne SDK를 불러오지 못했습니다."));
    document.head.appendChild(script);
  });
  return sdkLoadPromise;
}

function generateIdentityVerificationId(): string {
  return `laurio-iv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * 실제 인증창을 띄우고, 인증이 끝나면 identityVerificationId를 돌려준다.
 * 이 값을 그대로 `POST /api/verification/verify`의 `verification_token`으로
 * 보내면 서버가 포트원에 서버-투-서버로 조회해 완료 처리한다.
 *
 * 사용자가 창을 닫거나 인증이 실패하면 reject한다 — 호출부가 알림으로
 * 보여주는 것 이상은 하지 않는다(dev에서 사람이 한 번 걸어 확인하는 용도).
 */
export async function requestPortOneIdentityVerification(params: {
  storeId: string;
  channelKey: string;
}): Promise<string> {
  await loadPortOneSdk();
  if (!window.PortOne) {
    throw new Error("PortOne SDK가 초기화되지 않았습니다.");
  }

  const response = await window.PortOne.requestIdentityVerification({
    storeId: params.storeId,
    channelKey: params.channelKey,
    identityVerificationId: generateIdentityVerificationId(),
    redirectUrl: window.location.href,
  });

  if (response.code) {
    throw new Error(response.message || "본인확인 창에서 오류가 발생했습니다.");
  }

  return response.identityVerificationId;
}

/** 실물 본인확인 버튼을 렌더링할지 결정한다 — 둘 다 있어야 인증창을 열 수 있다. */
export function getPortOneBrowserConfig(): { storeId: string; channelKey: string } | null {
  const storeId = process.env.NEXT_PUBLIC_PORTONE_STORE_ID;
  const channelKey = process.env.NEXT_PUBLIC_PORTONE_CHANNEL_KEY;
  if (!storeId || !channelKey) return null;
  return { storeId, channelKey };
}
