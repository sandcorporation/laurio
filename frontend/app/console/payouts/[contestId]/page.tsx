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
  submitSellerContact,
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
        <PayoutDetail
          payout={state.payout}
          onChanged={reload}
          accountEmail={session.user.email}
        />
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

function PayoutDetail({
  payout,
  onChanged,
  accountEmail,
}: {
  payout: Payout;
  onChanged: () => void;
  /** 로그인 계정의 이메일 — 연락처 폼이 이메일 입력의 기본값으로 보여줄 뿐,
   * 저장은 항상 Seller 쪽에 한다(#168 구현 결정). 비어 있을 수 있다(#49
   * 유저스토리 12 — 카카오가 이메일 동의를 안 주면). */
  accountEmail: string;
}) {
  // 「연락처를 내야 하는가」를 한 곳에서만 판정한다 — 아래에서 폼을 띄우는
  // 조건과 "하실 일은 없습니다"를 감추는 조건이 같은 값을 봐야 한다. 두 조건이
  // 따로 적혀 있으면 한쪽만 고쳤을 때 **아무것도 없는 빈 대기 상자**가 남는다
  // (#91 — `has_seller_phone` 만 보던 시절의 실제 결과).
  //
  // 백엔드의 Hold 표(`payouts/progress.py`)가 연락처를 요구하는 조합과 정확히
  // 같다: Seller 가 아직 없거나 PENDING 인데 전화번호나 이메일 중 하나라도
  // 없을 때(#168 이 전화번호 전용이던 조건을 넓혔다). 심사 중(under_review)·
  // 거절(rejected)·본인인증 대기(approval_required)에는 백엔드가 다른 것을
  // 안내하므로("심사가 끝나면 자동으로 넘어갑니다", "운영자에게 문의해주세요")
  // 여기서 연락처를 요구하면 화면이 시키는 대로 한 사람이 아무 변화도 못 본다.
  const missingSellerPhone = !payout.has_seller_phone;
  const missingSellerEmail = !payout.has_seller_email;
  const needsSellerContact =
    (missingSellerPhone || missingSellerEmail) &&
    (payout.seller_status === null || payout.seller_status === "pending");

  // 지급대행사가 보낸 본인인증 문자를 아직 처리하지 않았다 — 백엔드도 이것을
  // Developer 의 차례로 본다(`progress.py` 의 SELLER_AUTH → Turn.DEVELOPER).
  // 여기 화면이 줄 수 있는 것은 없지만(인증은 토스 쪽에서 끝난다)
  // "하실 일은 없습니다"라고 말해서는 안 된다 — 바로 위 안내가 정반대를
  // 말하고 있다.
  const awaitingSellerAuth = payout.seller_status === "approval_required";

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

      {/* 실이체는 이미 READY인 Seller에서도 실패할 수 있다(#57 코드리뷰
          지적 1) — 그러면 status는 confirmed_identity_pending에 머물지만
          할 일(재시도)이 있다. seller_pending 섹션과 같은 조건을 여기서도
          똑같이 쓴다(코드리뷰 지적 7/9, 3차 — 백엔드의 blocked_on/NextAction
          판정과 같은 신호를 본다). */}
      {payout.status === "confirmed_identity_pending" && payout.transfer_status === "failed" ? (
        <SellerRetry payout={payout} onRetried={onChanged} reason="transfer" />
      ) : null}

      {payout.status === "confirmed_seller_pending" ? (
        <section className="mt-6 rounded border border-subtle p-4" data-testid="payout-waiting">
          {/* PENDING이면서 아직 연락처(전화번호·이메일)를 안 냈으면 하실 일이
              있다(#57 코드리뷰 지적 10, #168) — next_action_message가 "아래에서
              제출해주세요"라고 말하는데 폼이 없으면 그 지시를 따를 수 없다.
              실물 어댑터는 연락처 없이 첫 등록을 시도조차 하지 않는다
              (TossSellerAdapter.register) — 그러니 이 폼 없이는 영구 정체다.
              `has_seller_phone`/`has_seller_email`(서버가 계산한 값)을 본다 —
              seller_status가 null/pending인지로만 추론하면, 이미 낸 값을 또
              내라는 폼이 된다(코드리뷰 지적 12, 3차). 그 값만으로 부족한
              이유와 Seller 상태를 함께 보는 이유는 위 `needsSellerContact`
              에 적혀 있다(#91). 폼 자신이 "무엇이 비었는지"를 두 사실로
              구성한다 — 그 문구는 백엔드 Hold 번역표가 아니라 화면이 소유한다
              (#168 구현 결정). */}
          {needsSellerContact ? (
            <SellerContactForm
              payout={payout}
              missingPhone={missingSellerPhone}
              missingEmail={missingSellerEmail}
              accountEmail={accountEmail}
              onSubmitted={onChanged}
            />
          ) : null}

          {/* **거절도, 실이체 실패도 실패가 아니다**(#74 스토리 30·31, #57
              코드리뷰 지적 1). 지급대행사가 수취인 등록을 거절하거나, 등록은
              끝났는데 실제 이체 자체가 거절돼도 상금은 원장에 그대로 남아
              있다 — 그 사실을 말하고, 다시 시도할 길을 준다. 사람이
              고객센터를 거쳐야 하면 "상금이 사라진 것 같은 시간"이 길어질
              뿐이다. */}
          {payout.seller_status === "rejected" ? (
            <SellerRetry payout={payout} onRetried={onChanged} reason="rejected" />
          ) : payout.transfer_status === "failed" ? (
            <SellerRetry payout={payout} onRetried={onChanged} reason="transfer" />
          ) : null}

          {/* Seller 등록 대기 중에도 주민등록번호는 낼 수 있다 — 두 대기는
              서로 독립적이다(ADR-0020). 먼저 끝낼 수 있는 쪽을 막지 않는다. */}
          {payout.has_identity ? null : <TaxIdentityForm payout={payout} onSubmitted={onChanged} />}

          {/* "하실 일은 없습니다"는 정말로 할 일이 없을 때만 보인다(코드리뷰
              지적 10, 3차) — 연락처 폼·재시도 버튼·신원 제출 폼 중 어느
              것도 뜨지 않을 때만이다. 폼·버튼 바로 위에 이 문장이 뜨면
              "할 일이 없다"와 "여기 낼 것이 있다"가 한 화면에서 서로
              모순된다. */}
          {!needsSellerContact &&
          !awaitingSellerAuth &&
          payout.seller_status !== "rejected" &&
          payout.transfer_status !== "failed" &&
          payout.has_identity ? (
            <p className="text-muted">
              지금은 기다리는 단계입니다 — 하실 일은 없습니다. 상금은 원장에 그대로 남아 있고,
              등록이 끝나면 자동으로 다음 단계로 넘어갑니다.
            </p>
          ) : null}
        </section>
      ) : null}

      {payout.status === "confirmed" && payout.transfer_status !== "failed" ? (
        <p className="mt-6 font-semibold" data-testid="payout-complete">
          지급이 완료되었습니다.
        </p>
      ) : null}

      {/* 확정 이후 뒤늦게 실이체 실패가 확인된 경우다(#57 코드리뷰 지적 4/8,
          2·3차) — next_action_message가 이미 그 사실을 말하므로(위), 그
          바로 아래에 모순되는 "지급이 완료되었습니다"를 또 찍지 않는다.
          Developer 쪽 자기 서비스 재시도 경로는 아직 없다(ADR-0008에 남긴
          한계) — 여기서 새 버튼을 만들지 않는다. */}
    </>
  );
}

function SellerRetry({
  payout,
  onRetried,
  reason,
}: {
  payout: Payout;
  onRetried: () => void;
  /** 재시도 버튼이 뜬 이유 — 문구가 실제 원인과 어긋나면 안 된다(코드리뷰
   * 지적 11, 3차): "rejected"인데 "실이체가 실패했다"고 말하거나 그 반대면
   * Developer가 무엇을 다시 시도하는 건지 오해한다. */
  reason: "rejected" | "transfer";
}) {
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

  const explanation =
    reason === "rejected"
      ? "지급대행사의 수취인 등록이 거절되었습니다."
      : "지급대행사 수취인 등록은 끝났지만 실제 이체가 거절되었습니다.";

  return (
    <div className="mt-3" data-testid={`payout-seller-retry-${reason}`}>
      <p className="text-sm">
        {explanation} <strong>상금은 그대로 남아 있습니다</strong> — 다시 시도해보시고, 계속
        거절되면 운영자에게 문의해주세요.
      </p>
      <button
        className="mt-2 rounded border border-subtle px-3 py-2 text-sm disabled:opacity-50"
        type="button"
        onClick={handleClick}
        disabled={pending}
        data-testid="payout-seller-retry"
      >
        {pending ? "다시 시도하는 중..." : "다시 시도"}
      </button>
      {message ? (
        <p className="mt-2 text-attention" data-testid="payout-seller-retry-error">
          {message}
        </p>
      ) : null}
    </div>
  );
}

function SellerContactForm({
  payout,
  missingPhone,
  missingEmail,
  accountEmail,
  onSubmitted,
}: {
  payout: Payout;
  missingPhone: boolean;
  missingEmail: boolean;
  /** 계정 이메일 — 이메일 입력의 기본값으로만 쓴다. 저장은 항상 제출 시점의
   * 입력값을 Seller 쪽에 한다(#168). */
  accountEmail: string;
  onSubmitted: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState(accountEmail);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setMessage(null);

    // **부분 제출을 보낸다** — 이미 낸 쪽(missing 이 아닌 쪽)은 아예 요청에
    // 담지 않는다. 서버가 "안 보냄"과 "빈 값"을 구분하므로(#168), 이미 낸
    // 값을 다시 덮어쓰는 요청을 만들지 않는다.
    const result = await submitSellerContact(payout.idempotency_key, {
      ...(missingPhone ? { phoneNumber: phone } : {}),
      ...(missingEmail ? { email } : {}),
    });

    if (result.ok) return onSubmitted();
    setMessage(result.message);
    setPending(false);
  }

  const canSubmit = (!missingPhone || phone.length >= 10) && (!missingEmail || email.length > 0);

  return (
    <form
      className="mt-4 flex flex-col gap-3 rounded border border-subtle p-3"
      onSubmit={handleSubmit}
      data-testid="payout-seller-contact-form"
    >
      {/* **무엇이 비었는지는 이 화면이 두 사실로 직접 구성한다** — Hold
          번역표(백엔드)가 아니라 여기가 그 문구를 소유한다(#168 구현 결정).
          이미 낸 값은 다시 내라고 하지 않는다. */}
      <p className="text-sm" data-testid="payout-seller-contact-missing">
        {missingPhone && missingEmail
          ? "지급대행사 수취인 등록에 전화번호와 이메일이 모두 필요합니다."
          : missingPhone
            ? "지급대행사 수취인 등록에 전화번호가 필요합니다 — 이미 제출한 이메일은 그대로 유지됩니다."
            : "지급대행사 수취인 등록에 이메일이 필요합니다 — 이미 제출한 전화번호는 그대로 유지됩니다."}
      </p>
      {missingPhone ? (
        <div className="flex flex-col gap-1">
          <label className="text-sm" htmlFor="payout-seller-phone">
            전화번호 — 본인인증 문자를 받을 번호입니다.
          </label>
          <input
            id="payout-seller-phone"
            className="rounded border border-subtle p-3"
            type="tel"
            inputMode="numeric"
            autoComplete="tel"
            maxLength={11}
            value={phone}
            onChange={(event) => setPhone(event.target.value.replace(/\D/g, ""))}
            placeholder="숫자만 (하이픈 없이)"
            data-testid="payout-seller-phone-input"
            required
          />
        </div>
      ) : null}
      {missingEmail ? (
        <div className="flex flex-col gap-1">
          <label className="text-sm" htmlFor="payout-seller-email">
            이메일 — 로그인 계정의 이메일과 달라도 됩니다.
          </label>
          <input
            id="payout-seller-email"
            className="rounded border border-subtle p-3"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            data-testid="payout-seller-email-input"
            required
          />
        </div>
      ) : null}
      <button
        className="self-start rounded bg-accent px-4 py-2 text-white disabled:opacity-50"
        type="submit"
        disabled={pending || !canSubmit}
        data-testid="payout-seller-contact-submit"
      >
        {pending ? "제출하는 중..." : "제출"}
      </button>
      {message ? (
        <p className="text-attention" data-testid="payout-seller-contact-error">
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
