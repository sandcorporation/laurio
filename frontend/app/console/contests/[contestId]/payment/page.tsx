"use client";

// 결제 화면 (#86, #112, spec #82, spec #110).
//
// 지금까지 결제 화면이 아예 없었다 — 개최 화면은 Contest를 draft로 만들고
// 끝났고, 결제는 e2e가 API를 직접 쳐야만 일어났다. #86이 그 공백을 벤더 없이
// 메웠다 — Fake PG 그대로 화면과 계약을 세워서, 이 화면(#112)이 벤더만
// 갈아끼우면 되게 했다.
//
// **위젯을 쓸지는 PG 어댑터 모드가 가른다**(payment.checkout_flow,
// payments.api._serialize) — 클라이언트 키의 유무가 아니다. Fake PG
// ("direct")는 지금처럼 결제 건 식별자를 지어내 곧바로 확정한다(dev에 벤더
// 자격증명이 없고 개최 e2e가 이 경로로 끝까지 걸어야 한다). 실물 어댑터
// ("widget")는 브라우저가 토스 결제창을 거친 뒤, 성공·실패 어느 쪽이든 같은
// 화면(이 페이지)으로 돌아와 쿼리 파라미터로 결과를 싣는다.
//
// **결제 건 식별자(payment key)**는 실물 PG(토스)가 결제 승인에 요구하는
// 값으로, 위젯이 성공했을 때만 생긴다. "direct" 경로는 여전히 그 값을
// 지어내 보낸다(Fake PG는 무시한다) — 브라우저 → BFF → 백엔드 → 어댑터까지
// 실제로 그 값이 실려 가는지는 이 화면이 보내는 요청 자체로 증명된다.
// "widget" 경로는 토스가 돌려준 진짜 값을 그대로 넘긴다.
//
// **성공·실패 복귀 URL은 브라우저가 자기 주소에서 짓는다**
// (lib/payments/toss.ts) — 컨테이너 안의 Next는 자기가 어떤 공개 주소로
// 불렸는지 모른다(카카오 로그인이 바인드 주소로 튕긴 적이 있다).
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015). 세션이 죽었는지를 로딩 게이트
// 보다 먼저 본다 — 반대로 두면 만료 시 영원히 "불러오는 중"에 갇힌다(#69,
// #81과 같은 관용구).
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { sessionFetch } from "@/lib/auth/client-fetch";
import { useSession } from "@/lib/auth/use-session";
import { formatPrize } from "@/lib/contest-format";
import {
  clearRedirectPaymentParams,
  getTossClientKey,
  openTossCheckout,
  peekRedirectPaymentResult,
} from "@/lib/payments/toss";
import type { components } from "@/lib/api/schema.gen";

type PaymentOut = components["schemas"]["PaymentOut"];

type ContestMeta = {
  id: number;
  title: string;
  status: string;
};

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  // Contest가 draft를 벗어났다 — 이미 결제되어 공개됐거나 그 뒤 상태다. 두
  // 번 청구하지 않는다는 것을 이 상태 자체가 보장한다 — 여기서는 애초에
  // 결제 요청을 다시 만들지 않는다.
  | { status: "already-paid"; title: string }
  | { status: "ready"; title: string; payment: PaymentOut };

type ConfirmState =
  | { status: "idle" }
  | { status: "confirming" }
  | { status: "paid" }
  // 실물 어댑터에서 도달 가능한 경로다(#86 코드리뷰) — confirm 응답이 아직
  // paid/failed로 확정되지 않았다(requested/pending). "idle"로 되돌리면
  // 사용자에게는 클릭이 아무 일도 안 한 것처럼 보여 반복 클릭을 유도한다 —
  // 그래서 구별되는 상태로 그린다.
  | { status: "pending" }
  // "widget" 경로 전용(#112) — 토스 SDK를 불러와 결제창을 여는 사이. 정상
  // 경로라면 이 상태가 오래 보이지 않는다(브라우저가 곧 토스로 떠난다) —
  // 그래도 "아무 일도 안 일어난 줄 알고 반복 클릭"을 막으려면 구별되는
  // 상태가 있어야 한다(인수조건).
  | { status: "opening_widget" }
  | { status: "failed"; message: string };

/** 실물 위젯이 없는 이 티켓의 범위 안에서 "위젯이 성공했을 때만 생기는 값"을
 * 흉내낸다. Fake PG는 이 값을 검증도 저장도 하지 않는다 — 이 함수가 있는
 * 이유는 계약 자리가 실제로 브라우저에서부터 채워진다는 것을 보여주기
 * 위해서다(#87이 실물 위젯 값으로 갈아끼운다). */
function fakeWidgetPaymentKey(orderId: string): string {
  return `fake-widget-payment-key-${orderId}`;
}

export default function ContestPaymentPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [confirm, setConfirm] = useState<ConfirmState>({ status: "idle" });
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    async function loadAll() {
      const contestRes = await sessionFetch(`/api/backend/contests/${contestId}`);
      if (cancelled) return;

      if (contestRes.status === 404) {
        setLoad({ status: "not-found" });
        return;
      }
      if (!contestRes.ok) {
        setLoad({ status: "error", message: "공모전 정보를 불러오지 못했습니다." });
        return;
      }
      const contest = (await contestRes.json()) as ContestMeta;
      if (cancelled) return;

      if (contest.status !== "draft") {
        // 이미 결제되어 공개된(또는 그 뒤로 넘어간) Contest다 — 새 결제 요청을
        // 만들 이유가 없다. 여기서 걸러야 initiate_payment의 409를 화면이
        // 매번 대신 겪지 않는다.
        setLoad({ status: "already-paid", title: contest.title });
        return;
      }

      // draft다 — 결제를 시작(또는 이미 진행 중인 활성 결제를 그대로 이어받아)
      // 금액을 받아온다. 이 호출 자체가 소유자 확인이다: 남의 Contest면 403,
      // 없으면 404 — 어느 쪽도 금액을 돌려주지 않는다.
      const paymentRes = await sessionFetch("/api/backend/payments", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ contest_id: Number(contestId) }),
      });
      if (cancelled) return;

      if (paymentRes.status === 409) {
        // GET과 POST 사이에 다른 경로로 이미 결제·공개됐다 — 드문 경합이지만
        // "두 번 청구되지 않는다"는 여기서도 성립해야 한다.
        setLoad({ status: "already-paid", title: contest.title });
        return;
      }
      if (paymentRes.status === 403 || paymentRes.status === 404) {
        // 남의 Contest다. 제목도 이미 응답에 있었지만, 여기서부터는 아무 금액도
        // 보여주지 않는다 — not-found로 합류시켜 남의 결제 화면이 다른 문구로
        // "여기 뭔가 있다"는 것조차 알려주지 않게 한다.
        setLoad({ status: "not-found" });
        return;
      }
      if (!paymentRes.ok) {
        setLoad({ status: "error", message: "결제 정보를 불러오지 못했습니다." });
        return;
      }
      const payment = (await paymentRes.json()) as PaymentOut;
      if (cancelled) return;
      setLoad({ status: "ready", title: contest.title, payment });
    }

    loadAll().catch(() => {
      if (!cancelled) setLoad({ status: "error", message: "불러오는 중 오류가 발생했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, contestId, reloadTick]);

  // 토스 결제창에서 돌아왔는지 마운트 시점에(그리고 로드가 끝난 뒤) 확인한다
  // (#112, #114) — "widget" 경로에서만 실제로 쿼리 파라미터가 실려 오지만,
  // 이 확인 자체는 경로와 무관하게 항상 돈다("direct" 경로에는 애초에 이
  // 파라미터가 붙을 일이 없으므로 조용히 아무 것도 하지 않는다).
  //
  // URL은 peekRedirectPaymentResult가 **읽기만** 하고, 확정을 시도한 뒤(성공
  // 이든 실패든) clearRedirectPaymentParams로 지운다 — lib/verification/
  // portone.ts와 같은 규율: 확정 전에 지우면 그 요청이 일시적으로 실패했을 때
  // 재시도할 paymentKey 자체를 잃는다. 실패 복귀는 재시도할 여지가 없으므로
  // 곧바로 지운다.
  useEffect(() => {
    if (load.status !== "ready") return;
    const redirectResult = peekRedirectPaymentResult();
    if (redirectResult === null) return;

    if (redirectResult.status === "failure") {
      clearRedirectPaymentParams();
      setConfirm({ status: "failed", message: redirectResult.message });
      return;
    }

    clearRedirectPaymentParams();
    void confirmWithPaymentKey(redirectResult.paymentKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 마운트(로드 완료) 시점 1회만 확인한다.
  }, [load.status]);

  // 로드 경로(loadAll)와 같은 모양으로 맞춘다 — fetch 자체가 reject되면(네트워크
  // 끊김 등) catch 없이는 "confirming"에 영구히 갇혀 버튼이 disabled인 채
  // 남고, 사용자는 청구가 됐는지조차 알 수 없다(#86 코드리뷰). "direct"
  // 경로(가짜 결제 건 식별자)와 "widget" 복귀 경로(토스가 돌려준 진짜 값)
  // 둘 다 이 함수로 수렴한다.
  async function confirmWithPaymentKey(paymentKey: string) {
    if (load.status !== "ready") return;
    setConfirm({ status: "confirming" });

    try {
      const res = await sessionFetch(`/api/backend/payments/${load.payment.order_id}/confirm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ payment_key: paymentKey }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setConfirm({
          status: "failed",
          message: body?.detail ?? `결제 확인에 실패했습니다 (${res.status})`,
        });
        return;
      }

      const result = (await res.json()) as PaymentOut;
      if (result.status === "paid") {
        setConfirm({ status: "paid" });
        return;
      }
      if (result.status === "failed") {
        setConfirm({ status: "failed", message: "결제가 승인되지 않았습니다." });
        return;
      }
      // 아직 확정되지 않았다(requested/pending) — 타임아웃 후 조회로 확정하는
      // 규율은 백엔드가 이미 지킨다(ADR-0008). 여기서는 그 사실을 구별되는
      // 상태로 보여주기만 한다 — "다시 확인하기"는 retry()와 같은 경로를 타
      // 최신 상태를 다시 불러온다(이미 확정됐으면 already-paid로, 아직이면
      // 같은 결제를 그대로 이어받는다).
      setConfirm({ status: "pending" });
    } catch {
      setConfirm({
        status: "failed",
        message: "네트워크 오류로 결제 확인 결과를 알 수 없습니다. 다시 확인해주세요.",
      });
    }
  }

  /** "widget" 경로 전용(#112) — 토스 결제창을 연다. 성공하면 브라우저가 이
   * 화면(returnPath)으로 돌아오고, 위 리다이렉트 확인 useEffect가 이어받는다.
   * SDK 로드 자체가 실패하거나(네트워크) 클라이언트 키가 비어 있으면(배포
   * 설정 실수 — #115가 부팅 시점 가드를 더한다) 결제창을 아예 열지 못했다는
   * 것을 곧바로 보여준다. */
  async function payViaWidget() {
    if (load.status !== "ready") return;
    const clientKey = getTossClientKey();
    if (!clientKey) {
      setConfirm({
        status: "failed",
        message: "결제 설정이 올바르지 않습니다. 관리자에게 문의해주세요.",
      });
      return;
    }

    setConfirm({ status: "opening_widget" });
    try {
      await openTossCheckout({
        clientKey,
        customerKey: load.payment.order_id,
        amount: load.payment.total_amount,
        orderId: load.payment.order_id,
        orderName: load.title.slice(0, 100),
        returnPath: `/console/contests/${contestId}/payment`,
      });
      // 정상 경로라면 여기 도달하기 전에 브라우저가 이미 토스로 떠났다.
    } catch (err) {
      setConfirm({
        status: "failed",
        message: err instanceof Error ? err.message : "결제창을 여는 중 오류가 발생했습니다.",
      });
    }
  }

  async function pay() {
    if (load.status !== "ready") return;
    if (load.payment.checkout_flow === "widget") {
      await payViaWidget();
      return;
    }
    await confirmWithPaymentKey(fakeWidgetPaymentKey(load.payment.order_id));
  }

  function retry() {
    // 실패한 결제는 되살아나지 않는다(services.mark_failed는 종결 상태다) —
    // 다시 시도한다는 것은 **새 결제**를 시작한다는 뜻이다. 그래서 이 화면은
    // confirm을 다시 부르지 않고 처음부터 다시 불러온다.
    setConfirm({ status: "idle" });
    setLoad({ status: "loading" });
    setReloadTick((tick) => tick + 1);
  }

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="payment-loading">불러오는 중...</p>
      </main>
    );
  }

  if (load.status === "not-found") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="payment-not-found">Contest를 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (load.status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="payment-load-error">
          {load.message}
        </p>
      </main>
    );
  }

  if (load.status === "already-paid") {
    return (
      <main className="mx-auto max-w-xl p-10">
        <h1 className="text-2xl font-semibold" data-testid="payment-heading">
          {load.title}
        </h1>
        <p className="mt-6" data-testid="payment-already-paid">
          이미 결제가 완료되어 공개된 공모전입니다. 다시 청구되지 않습니다.
        </p>
        <Link href="/console/contests" className="mt-4 inline-block text-sm underline">
          내 공모전으로 돌아가기
        </Link>
      </main>
    );
  }

  const { title, payment } = load;

  if (confirm.status === "paid") {
    return (
      <main className="mx-auto max-w-xl p-10">
        <h1 className="text-2xl font-semibold" data-testid="payment-heading">
          {title}
        </h1>
        <p className="mt-6 text-attention" data-testid="payment-success">
          결제가 완료되어 공모전이 공개되었습니다.
        </p>
        <Link
          href={`/contests/${contestId}`}
          data-testid="payment-view-contest"
          className="mt-4 inline-block text-sm underline"
        >
          공모전 보기
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-xl p-10">
      <h1 className="text-2xl font-semibold" data-testid="payment-heading">
        {title}
      </h1>
      <p className="mt-1 text-sm text-ink/60">결제가 끝나야 공모전이 공개됩니다.</p>

      <dl
        className="mt-6 flex flex-col gap-2 border border-rule p-4 text-sm"
        data-testid="payment-summary"
      >
        <div className="flex items-center justify-between">
          <dt className="text-ink/60">상금</dt>
          <dd className="font-mono" data-testid="payment-prize-amount">
            {formatPrize(payment.prize_amount)}원
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink/60">개최 등록비</dt>
          <dd className="font-mono" data-testid="payment-listing-fee-amount">
            {formatPrize(payment.listing_fee_amount)}원
          </dd>
        </div>
        <div className="flex items-center justify-between border-t border-rule pt-2 font-semibold">
          <dt>합계</dt>
          <dd className="font-mono" data-testid="payment-total-amount">
            {formatPrize(payment.total_amount)}원
          </dd>
        </div>
      </dl>

      {confirm.status === "failed" ? (
        <div className="mt-4 flex flex-col items-start gap-2" data-testid="payment-failed">
          <p role="alert" className="text-attention">
            {confirm.message}
          </p>
          <button
            type="button"
            onClick={retry}
            data-testid="payment-retry"
            className="rounded border border-ink px-4 py-2 text-sm hover:bg-ink hover:text-paper"
          >
            다시 시도
          </button>
        </div>
      ) : confirm.status === "pending" ? (
        <div className="mt-4 flex flex-col items-start gap-2" data-testid="payment-pending">
          <p role="status">확인 중입니다. 잠시 후 다시 확인해주세요.</p>
          <button
            type="button"
            onClick={retry}
            data-testid="payment-recheck"
            className="rounded border border-ink px-4 py-2 text-sm hover:bg-ink hover:text-paper"
          >
            다시 확인하기
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => void pay()}
          disabled={confirm.status === "confirming" || confirm.status === "opening_widget"}
          data-testid="payment-pay-button"
          className="mt-6 w-full rounded border border-ink bg-ink px-4 py-2.5 text-sm text-paper disabled:opacity-50"
        >
          {confirm.status === "confirming"
            ? "결제 확인 중..."
            : confirm.status === "opening_widget"
              ? "결제창 여는 중..."
              : "결제하기"}
        </button>
      )}
    </main>
  );
}
