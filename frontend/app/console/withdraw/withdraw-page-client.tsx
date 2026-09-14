"use client";

// 탈퇴 화면 (#100, ADR-0025) — 콘솔 안에 선다. 인증 구역이라 SSR하지 않는다
// (ADR-0015) — 다른 console/** 화면과 같은 클라이언트 SPA 모양이다.
//
// **막는 판정은 서버가 한다.** 이 화면은 Contest·Payout 상태를 보고 다시
// 판정하지 않는다 — `GET /api/accounts/withdrawal`이 준 `blocking_reasons`를
// 그대로 보여줄 뿐이다(#100 AC — "화면이 원시 상태에서 재파생하지 않는다").
//
// **되돌릴 수 없다.** CI를 지우므로 재가입해도 예전 참가작과 이어 붙일 방법이
// 없다 — 그래서 확인 버튼 앞에 체크박스를 둔다: 실수로 누르는 클릭 한 번이
// 되돌릴 수 없는 결정이 되지 않도록 한 단계를 더 둔다.
//
// **`returnOrigin`은 강의실에서 건너온 사람에게만 있다**(#307, 검증은
// `page.tsx`의 `resolveSiblingOrigin` — profile-page-client.tsx와 같은 계약).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorNote, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import { useSession } from "@/lib/auth/use-session";
import {
  BLOCK_REASON_LABELS,
  executeWithdrawal,
  useWithdrawalEligibility,
} from "@/lib/withdrawal/use-withdrawal";

export function WithdrawPageClient({ returnOrigin }: { returnOrigin: string | null }) {
  const session = useSession();
  const eligibility = useWithdrawalEligibility();
  const router = useRouter();

  const [acknowledged, setAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || eligibility.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="withdraw-loading">불러오는 중...</p>
      </main>
    );
  }

  async function handleWithdraw() {
    setSubmitting(true);
    setError(null);
    try {
      const result = await executeWithdrawal();
      if (result.ok) {
        setDone(true);
        // 탈퇴는 서버에서 이미 즉시 반영됐다(is_active=False, 토큰 즉시
        // 무효화) — 로그아웃 호출은 이 브라우저에 남은 쿠키를 마저 지워
        // 같은 자리에서 다시 로그인 화면을 보여주기 위한 것뿐이다.
        await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
        router.replace("/login");
        return;
      }
      setError(result.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <PageShell>
      <div className="flex items-center justify-between gap-3">
        <Link className="text-sm text-ink/60" href="/" data-testid="withdraw-back">
          ← 홈
        </Link>
        {returnOrigin && (
          <a
            className="text-sm text-ink/60"
            href={returnOrigin}
            data-testid="withdraw-return-to-classroom"
          >
            강의실로 돌아가기 →
          </a>
        )}
      </div>
      <PageHeader title="탈퇴" titleTestId="withdraw-heading" />

      {done ? (
        <p data-testid="withdraw-done">탈퇴가 완료되었습니다.</p>
      ) : eligibility.status === "error" ? (
        <ErrorNote>
          <span data-testid="withdraw-load-error">
            탈퇴 가능 여부를 확인하지 못했습니다. 잠시 후 다시 시도해주세요.
          </span>
        </ErrorNote>
      ) : (
        <>
          <WhatHappensSection />

          {!eligibility.eligibility.can_withdraw ? (
            <section
              className="mt-6 border border-attention bg-surface p-4"
              data-testid="withdraw-blocked"
            >
              <p className="font-semibold text-attention">
                지금은 탈퇴할 수 없습니다 — 다음을 끝내야 합니다.
              </p>
              <ul className="mt-3 flex flex-col gap-2" data-testid="withdraw-blocking-reasons">
                {eligibility.eligibility.blocking_reasons.map((reason) => (
                  <li
                    key={reason}
                    className="text-sm"
                    data-testid={`withdraw-blocking-reason-${reason}`}
                  >
                    {BLOCK_REASON_LABELS[reason]}
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <section className="mt-8" data-testid="withdraw-confirm-section">
              <label className="flex items-start gap-2 text-sm" data-testid="withdraw-ack-label">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  data-testid="withdraw-ack-checkbox"
                />
                <span>
                  신원이 파기되며 되돌릴 수 없다는 것을 이해했습니다. 재가입해도 지금 참가작과
                  다시 이어 붙일 수 없습니다.
                </span>
              </label>

              {error ? (
                <ErrorNote>
                  <span data-testid="withdraw-error">{error}</span>
                </ErrorNote>
              ) : null}

              <button
                type="button"
                onClick={handleWithdraw}
                disabled={!acknowledged || submitting}
                data-testid="withdraw-submit"
                className={`mt-4 ${buttonClass("dangerFilled")}`}
              >
                {submitting ? "탈퇴 처리 중..." : "탈퇴한다"}
              </button>
            </section>
          )}
        </>
      )}
    </PageShell>
  );
}

function WhatHappensSection() {
  return (
    <section className="mt-6 flex flex-col gap-4" data-testid="withdraw-explanation">
      <div>
        <p className="font-semibold">사라지는 것</p>
        <ul className="mt-1 list-disc pl-5 text-sm text-ink/60">
          <li>실명·생년월일·CI·DI·전화번호(본인확인 정보)</li>
          <li>표시 이름과 소개</li>
          <li>공개 프로필 — 더 이상 검색되지 않습니다</li>
        </ul>
      </div>
      <div>
        <p className="font-semibold">남는 것</p>
        <ul className="mt-1 list-disc pl-5 text-sm text-ink/60">
          <li>참가한 공모전과 제출물 — 다만 이름 없이 남습니다</li>
          <li>결제·지급 원장 — 계약 상대방의 기록이라 법이 보존을 요구합니다</li>
        </ul>
      </div>
      <p className="text-sm font-semibold text-attention" data-testid="withdraw-irreversible">
        탈퇴는 되돌릴 수 없습니다. 신원(CI)을 지우기 때문에, 나중에 같은 계정으로 다시
        가입해도 지금의 참가작·기록과 다시 이어 붙일 방법이 없습니다.
      </p>
    </section>
  );
}
