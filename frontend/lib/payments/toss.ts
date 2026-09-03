"use client";

// 토스페이먼츠 결제창 브라우저 SDK 연동 (#112, spec #110, ADR-0007).
//
// lib/verification/portone.ts와 같은 모양이다 — 스크립트를 한 번만 불러오고,
// 실패한 시도는 캐시하지 않는다(재시도가 막히지 않게). 다른 점은 위젯을
// "쓸지 말지"를 결정하는 기준이다: PortOne은 클라이언트 설정값의 유무로
// 실물 버튼 렌더링 여부를 가르지만, 토스는 **PG 어댑터 모드**가 가른다
// (payments.api가 PaymentOut에 실어 보내는 checkout_flow, #112 스펙 결정) —
// 클라이언트 키가 비었는데 checkout_flow가 "widget"이면 배포 설정 실수이지
// fake로 조용히 돌아갈 이유가 아니다. 이 모듈은 그 경우 명시적으로 에러를
// 던진다 — 부팅 시점에 그 값 자체를 요구하는 것은 별도 티켓(#115)의 범위다.
//
// 성공/실패 복귀 URL은 이 모듈을 호출하는 화면이 자기 자신의 주소
// (window.location.origin)에서 짓는다 — 컨테이너 안의 Next는 자기가 어떤
// 공개 주소로 불렸는지 모른다(카카오 로그인이 바인드 주소로 튕긴 적이 있다,
// lib/auth/redirect.ts). 위젯은 브라우저에서 도니 이 함정을 피한다.

const SDK_SRC = "https://js.tosspayments.com/v2/standard";

type TossRequestPaymentParams = {
  method: "CARD";
  amount: { currency: "KRW"; value: number };
  orderId: string;
  orderName: string;
  successUrl: string;
  failUrl: string;
};

type TossPaymentObject = {
  requestPayment: (params: TossRequestPaymentParams) => Promise<void>;
};

declare global {
  interface Window {
    TossPayments?: (clientKey: string) => {
      payment: (options: { customerKey: string }) => TossPaymentObject;
    };
  }
}

let sdkLoadPromise: Promise<void> | null = null;

/** 토스 결제 SDK 스크립트를 한 번만 불러온다 — lib/verification/portone.ts의
 * loadPortOneSdk와 같은 규율(실패를 캐시하지 않는다, 자신이 만든 script
 * 태그만 추적한다). */
function loadTossSdk(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("토스 결제 SDK는 브라우저에서만 불러올 수 있습니다."));
  }
  if (window.TossPayments) return Promise.resolve();
  if (sdkLoadPromise) return sdkLoadPromise;

  const promise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SDK_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      script.remove();
      reject(new Error("토스 결제 SDK를 불러오지 못했습니다."));
    };
    document.head.appendChild(script);
  });

  sdkLoadPromise = promise;
  promise.then(
    () => {
      if (sdkLoadPromise === promise) sdkLoadPromise = null;
    },
    () => {
      if (sdkLoadPromise === promise) sdkLoadPromise = null;
    },
  );
  return promise;
}

/** 결제창을 연다. 성공하면 이 함수가 resolve되기 전에 브라우저가 이미
 * successUrl/failUrl로 떠난다 — 이 Promise는 "결제창을 여는 요청 자체"가
 * 실패했을 때만(SDK 로드 실패 등) reject된다. */
export async function openTossCheckout(params: {
  clientKey: string;
  customerKey: string;
  amount: number;
  orderId: string;
  orderName: string;
  returnPath: string;
}): Promise<void> {
  await loadTossSdk();
  if (!window.TossPayments) {
    throw new Error("토스 결제 SDK가 초기화되지 않았습니다.");
  }

  const origin = window.location.origin;
  const tossPayments = window.TossPayments(params.clientKey);
  const payment = tossPayments.payment({ customerKey: params.customerKey });

  await payment.requestPayment({
    method: "CARD",
    amount: { currency: "KRW", value: params.amount },
    orderId: params.orderId,
    orderName: params.orderName,
    successUrl: `${origin}${params.returnPath}`,
    failUrl: `${origin}${params.returnPath}`,
  });
}

export type TossRedirectResult =
  | { status: "success"; paymentKey: string; orderId: string }
  | { status: "failure"; message: string };

/**
 * 결제창에서 돌아왔는지를 **읽기만** 한다 — URL은 건드리지 않는다
 * (lib/verification/portone.ts의 peekRedirectVerificationResult와 같은
 * 규율). 호출부가 확정(POST /payments/{order_id}/confirm)이 실제로 끝난
 * 뒤에만 clearRedirectPaymentParams를 따로 불러야 한다 — 확정 전에 지우면
 * 그 요청이 일시적으로 실패했을 때 재시도할 paymentKey 자체를 잃는다.
 *
 * 토스는 성공 시 successUrl에 amount/orderId/paymentKey를, 실패 시 failUrl에
 * code/message를 쿼리 파라미터로 붙인다 — amount는 여기서 읽지 않는다.
 * 확정에 쓰이는 금액은 언제나 서버의 Payment.total_amount다(#112 인수조건).
 */
export function peekRedirectPaymentResult(): TossRedirectResult | null {
  if (typeof window === "undefined") return null;

  const params = new URLSearchParams(window.location.search);
  const paymentKey = params.get("paymentKey");
  const orderId = params.get("orderId");
  const code = params.get("code");
  const message = params.get("message");

  if (!paymentKey && !code) return null;

  if (code) {
    return { status: "failure", message: message || "결제가 승인되지 않았습니다." };
  }
  // 위 가드(!paymentKey && !code)를 통과했고 code가 없으므로 paymentKey는 반드시 있다.
  return { status: "success", paymentKey: paymentKey as string, orderId: orderId ?? "" };
}

/** peekRedirectPaymentResult가 읽은 쿼리 파라미터를 URL에서 지운다(새로고침
 * 없이) — 결과를 확정 처리한 뒤에 호출한다. */
export function clearRedirectPaymentParams(): void {
  if (typeof window === "undefined") return;

  const params = new URLSearchParams(window.location.search);
  params.delete("paymentKey");
  params.delete("orderId");
  params.delete("amount");
  params.delete("code");
  params.delete("message");
  const rest = params.toString();
  const nextUrl = window.location.pathname + (rest ? "?" + rest : "") + window.location.hash;
  window.history.replaceState(null, "", nextUrl);
}

/** 빌드타임에 인라인되는 클라이언트 키(NEXT_PUBLIC_TOSS_CLIENT_KEY, #112) —
 * docker/compose.staging.yaml·docker/compose.prod.yaml의 frontend build.args가
 * 채운다. 비어 있으면 null — 부팅 시점에 그 자체를 요구하는 것은 #115의
 * 범위다. */
export function getTossClientKey(): string | null {
  const key = process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY;
  return key ? key : null;
}
