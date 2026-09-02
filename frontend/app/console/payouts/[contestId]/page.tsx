"use client";

// 지급 화면 (#74) — 상금이 얼마가 되어 내게 오는지, 지금 무엇이 남았는지.
//
// **세 가지를 반드시 구분해 그린다.**
//
// 1. 금액 내역. 상금 그대로가 통장에 들어오지 않는다 — 플랫폼 수수료와 원천징수
//    가 빠진다. 그 사실을 지급이 끝난 뒤에 알게 되면 그때부터는 해명이지 안내가
//    아니다. 네 금액은 `Payout` 이 만들어질 때 박힌 스냅샷이므로 화면은 율을
//    다시 곱하지 않는다.
// 2. 두 개의 기다림. 「주민등록번호 대기」와 「지급대행 등록 대기」는 서로 다른
//    것을 기다리고, 둘 다 실패가 아니다(ADR-0020). 앞은 내 차례이고 뒤는 아니다.
//    같은 회색 문장으로 그리면 사용자는 자기 차례인 걸 모른 채 기다린다.
// 3. 토스가 자기 인증 SMS 를 따로 보낸다. 본인확인은 이미 포트원으로 했는데
//    (ADR-0020 — 벤더가 갈려 두 번 일어난다) 예고 없이 두 번째 문자가 오면
//    피싱으로 읽힌다. **미리** 말한다.
import Link from "next/link";
import { use, useState } from "react";

import { useSession } from "@/lib/auth/use-session";
import {
  requestPayout,
  retrySellerRegistration,
  submitSellerPhone,
  submitTaxIdentity,
  usePayout,
  type Payout,
} from "@/lib/payouts/use-payout";

export default function PayoutPage({ params }: { params: Promise<{ contestId: string }> }) {
  const { contestId } = use(params);
  const session = useSession();
  const { state, reload } = usePayout(contestId);

  // 세션 만료를 로딩 게이트보다 먼저 본다(#69).
  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || state.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="payout-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl p-10">
      <Link className="text-sm text-muted" href="/console/participation" data-testid="payout-back">
        ← 내 참가 현황
      </Link>
      <h1 className="mt-2 text-2xl font-semibold" data-testid="payout-heading">
        상금 지급
      </h1>

      {state.status === "error" ? (
        <p className="mt-6 text-attention" data-testid="payout-error">
          지급 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : state.status === "none" ? (
        <RequestSection contestId={contestId} onRequested={reload} />
      ) : (
        <PayoutDetail payout={state.payout} onChanged={reload} />
      )}
    </main>
  );
}

function RequestSection({
  contestId,
  onRequested,
}: {
  contestId: string;
  onRequested: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleClick() {
    setPending(true);
    setMessage(null);
    const result = await requestPayout(contestId);
    if (result.ok) return onRequested();
    // 인수 확인이 아직이라거나 이미 요청했다거나 — 서버만 아는 사실이다.
    setMessage(result.message);
    setPending(false);
  }

  return (
    <section className="mt-6" data-testid="payout-request">
      {/* 「요청할 수 있습니다」라고 말하지 않는다 — 서버는 아직 Award 되지
          않은 Contest 에도 같은 404 를 내므로, 여기서 자격을 단정하면 자격 없는
          사람에게 "요청하세요"라고 말하게 된다. 자격은 눌렀을 때 서버가 답한다.
          「내 참가 현황」이 이 화면을 링크하는 조건도 서버가 준 값이다. */}
      <p data-testid="payout-none">이 공모전에는 아직 지급 내역이 없습니다.</p>
      <SmsNotice />
      <button
        className="mt-4 rounded bg-accent px-4 py-2 text-white disabled:opacity-50"
        type="button"
        onClick={handleClick}
        disabled={pending}
        data-testid="payout-request-submit"
      >
        {pending ? "요청하는 중..." : "상금 지급 요청"}
      </button>
      {message ? (
        <p className="mt-3 text-attention" data-testid="payout-request-error">
          {message}
        </p>
      ) : null}
    </section>
  );
}

function PayoutDetail({ payout, onChanged }: { payout: Payout; onChanged: () => void }) {
  return (
    <>
      <AmountBreakdown payout={payout} />

      <p className="mt-6" data-testid="payout-next-action-message">
        {payout.next_action_message}
      </p>

      {/* **두 대기를 다르게 그린다.** 앞은 내 차례, 뒤는 기다림이다. */}
      {payout.status === "confirmed_identity_pending" && !payout.has_identity ? (
        <TaxIdentityForm payout={payout} onSubmitted={onChanged} />
      ) : null}

      {payout.status === "confirmed_seller_pending" ? (
        <section className="mt-6 rounded border border-subtle p-4" data-testid="payout-waiting">
          <p className="text-muted">
            지금은 기다리는 단계입니다 — 하실 일은 없습니다. 상금은 원장에 그대로 남아 있고,
            등록이 끝나면 자동으로 다음 단계로 넘어갑니다.
          </p>
          {/* PENDING이면서 아직 전화번호를 안 냈으면 하실 일이 있다(#57
              코드리뷰 지적 10) — next_action_message가 "아래에서 제출해주세요"
              라고 말하는데 폼이 없으면 그 지시를 따를 수 없다. 실물 어댑터는
              전화번호 없이 첫 등록을 시도조차 하지 않는다
              (TossSellerAdapter.register) — 그러니 이 폼 없이는 영구 정체다. */}
          {payout.seller_status === null || payout.seller_status === "pending" ? (
            <SellerPhoneForm payout={payout} onSubmitted={onChanged} />
          ) : null}

          {/* **거절도, 실이체 실패도 실패가 아니다**(#74 스토리 30·31, #57
              코드리뷰 지적 1). 지급대행사가 수취인 등록을 거절하거나, 등록은
              끝났는데 실제 이체 자체가 거절돼도 상금은 원장에 그대로 남아
              있다 — 그 사실을 말하고, 다시 시도할 길을 준다. 사람이
              고객센터를 거쳐야 하면 "상금이 사라진 것 같은 시간"이 길어질
              뿐이다. */}
          {payout.seller_status === "rejected" || payout.transfer_status === "failed" ? (
            <SellerRetry payout={payout} onRetried={onChanged} />
          ) : null}

          {/* Seller 등록 대기 중에도 주민등록번호는 낼 수 있다 — 두 대기는
              서로 독립적이다(ADR-0020). 먼저 끝낼 수 있는 쪽을 막지 않는다. */}
          {payout.has_identity ? null : <TaxIdentityForm payout={payout} onSubmitted={onChanged} />}
        </section>
      ) : null}

      {payout.status === "confirmed" ? (
        <p className="mt-6 font-semibold" data-testid="payout-complete">
          지급이 완료되었습니다.
        </p>
      ) : null}
    </>
  );
}

function SellerRetry({ payout, onRetried }: { payout: Payout; onRetried: () => void }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleClick() {
    setPending(true);
    setMessage(null);
    const result = await retrySellerRegistration(payout.idempotency_key);
    if (result.ok) return onRetried();
    setMessage(result.message);
    setPending(false);
  }

  return (
    <div className="mt-3" data-testid="payout-seller-rejected">
      <p className="text-sm">
        지급대행사의 수취인 등록이 거절되었습니다. <strong>상금은 그대로 남아 있습니다</strong> —
        다시 시도해보시고, 계속 거절되면 운영자에게 문의해주세요.
      </p>
      <button
        className="mt-2 rounded border border-subtle px-3 py-2 text-sm disabled:opacity-50"
        type="button"
        onClick={handleClick}
        disabled={pending}
        data-testid="payout-seller-retry"
      >
        {pending ? "다시 시도하는 중..." : "등록 다시 시도"}
      </button>
      {message ? (
        <p className="mt-2 text-attention" data-testid="payout-seller-retry-error">
          {message}
        </p>
      ) : null}
    </div>
  );
}

function SellerPhoneForm({ payout, onSubmitted }: { payout: Payout; onSubmitted: () => void }) {
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setMessage(null);

    const result = await submitSellerPhone(payout.idempotency_key, value);

    if (result.ok) return onSubmitted();
    setMessage(result.message);
    setPending(false);
  }

  return (
    <form
      className="mt-4 flex flex-col gap-3 rounded border border-subtle p-3"
      onSubmit={handleSubmit}
      data-testid="payout-seller-phone-form"
    >
      <label className="text-sm" htmlFor="payout-seller-phone">
        지급대행사 수취인 등록에 전화번호가 필요합니다 — 본인인증 문자를 받을 번호입니다.
      </label>
      <input
        id="payout-seller-phone"
        className="rounded border border-subtle p-3"
        type="tel"
        inputMode="numeric"
        autoComplete="tel"
        maxLength={11}
        value={value}
        onChange={(event) => setValue(event.target.value.replace(/\D/g, ""))}
        placeholder="숫자만 (하이픈 없이)"
        data-testid="payout-seller-phone-input"
        required
      />
      <button
        className="self-start rounded bg-accent px-4 py-2 text-white disabled:opacity-50"
        type="submit"
        disabled={pending || value.length < 10}
        data-testid="payout-seller-phone-submit"
      >
        {pending ? "제출하는 중..." : "제출"}
      </button>
      {message ? (
        <p className="text-attention" data-testid="payout-seller-phone-error">
          {message}
        </p>
      ) : null}
    </form>
  );
}

function AmountBreakdown({ payout }: { payout: Payout }) {
  const won = (amount: number) => `${amount.toLocaleString()}원`;

  return (
    <section className="mt-6 rounded border border-subtle p-4" data-testid="payout-amounts">
      {/* 상금 그대로가 들어오지 않는다는 사실을 **지급 전에** 본다. */}
      <dl className="flex flex-col gap-1 text-sm">
        <Row label="상금" value={won(payout.prize_amount)} testId="payout-amount-prize" />
        <Row
          label="플랫폼 수수료"
          value={`− ${won(payout.platform_fee_amount)}`}
          testId="payout-amount-fee"
        />
        <Row
          label="원천징수"
          value={`− ${won(payout.withholding_tax_amount)}`}
          testId="payout-amount-withholding"
        />
      </dl>
      <p className="mt-3 border-t border-subtle pt-3 text-lg font-semibold">
        실수령액 <span data-testid="payout-amount-net">{won(payout.net_amount)}</span>
      </p>
      <p className="mt-2 text-xs text-muted">
        수수료율과 원천징수율은 지급을 요청한 시점의 값으로 고정됩니다 — 이후 정책이 바뀌어도 이
        금액은 달라지지 않습니다.
      </p>
    </section>
  );
}

function Row({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="flex justify-between">
      <dt>{label}</dt>
      <dd data-testid={testId}>{value}</dd>
    </div>
  );
}

function SmsNotice() {
  return (
    // 본인확인은 이미 끝났는데 지급대행사가 자기 인증 문자를 또 보낸다
    // (ADR-0020 — 결제·지급대행과 본인확인의 벤더가 갈려 있다). 예고 없이
    // 두 번째 문자가 오면 피싱으로 읽히고, 그러면 사람들은 무시한다.
    <p className="mt-3 rounded border border-subtle p-3 text-sm" data-testid="payout-sms-notice">
      지급 절차 중에 지급대행사(토스페이먼츠)가 <strong>별도의 본인확인 문자</strong>를 보냅니다.
      가입할 때 하신 본인확인과는 다른 절차이며, 정상입니다.
    </p>
  );
}

function TaxIdentityForm({ payout, onSubmitted }: { payout: Payout; onSubmitted: () => void }) {
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setMessage(null);

    const result = await submitTaxIdentity(payout.idempotency_key, value);
    // **성공이든 실패든 즉시 버린다.** 실패했다고 남겨 두면 다시 시도하기 편한
    // 대신, 주민등록번호가 화면 상태에 계속 살아 있게 된다.
    setValue("");

    if (result.ok) return onSubmitted();
    setMessage(result.message);
    setPending(false);
  }

  return (
    <form
      className="mt-6 flex flex-col gap-3"
      onSubmit={handleSubmit}
      data-testid="payout-identity-form"
    >
      <label className="text-sm" htmlFor="payout-rrn">
        세무 신고를 위해 주민등록번호가 필요합니다. 암호화해 보관하며, 화면에 다시 표시하지
        않습니다.
      </label>
      <input
        id="payout-rrn"
        className="rounded border border-subtle p-3"
        // `password` 다 — 어깨너머로 읽히지 않고, 브라우저·확장이 자동완성
        // 목록에 남기지 않는다.
        type="password"
        inputMode="numeric"
        autoComplete="off"
        maxLength={13}
        value={value}
        onChange={(event) => setValue(event.target.value.replace(/\D/g, ""))}
        placeholder="숫자 13자리"
        data-testid="payout-rrn-input"
        required
      />
      <SmsNotice />
      <button
        className="self-start rounded bg-accent px-4 py-2 text-white disabled:opacity-50"
        type="submit"
        disabled={pending || value.length !== 13}
        data-testid="payout-identity-submit"
      >
        {pending ? "제출하는 중..." : "제출"}
      </button>
      {message ? (
        <p className="text-attention" data-testid="payout-identity-error">
          {message}
        </p>
      ) : null}
    </form>
  );
}
