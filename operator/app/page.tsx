"use client";

// 「할 일」 홈(#65). 운영자가 이 앱을 여는 이유는 단 하나 — 자기를 기다리는 것이
// 무엇인지 알기 위해서다. 세 큐의 건수를 보여주고, 각 건수에서 그 목록으로 바로
// 간다. 목록 화면 자체(이의 심판 #66, 지급 큐 #68)는 다른 티켓의 몫이라 여기서는
// 만들지 않는다 — 링크의 목적지로만 남겨 둔다.
import { useState } from "react";

import { normalizeDetail } from "@laurio/bff-client";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { QueueCard } from "@/lib/home/queue-card";
import { useQueueCounts } from "@/lib/home/use-queue-counts";
import { useSession } from "@/lib/auth/use-session";

export default function OperatorHome() {
  const session = useSession();
  const counts = useQueueCounts(session.status === "authenticated");
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function handleLogout() {
    setLoggingOut(true);
    setLogoutError(null);
    try {
      const res = await fetch("/api/auth/logout", { method: "POST" });
      if (!res.ok) {
        // BFF가 실패하면 의도적으로 쿠키를 지우지 않는다(operator/app/api/auth/
        // logout/route.ts) — 세션이 살아 있는데 여기서 그냥 /login으로 보내면
        // "로그아웃됨"으로 보이지만 실제로는 세션이 죽지 않은 채로 남는다
        // (코드리뷰 지적). 실패를 화면에 말하고 여기 머문다.
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        setLogoutError(
          normalizeDetail(body?.detail, `로그아웃에 실패했습니다 (${res.status}). 다시 시도해주세요.`),
        );
        return;
      }
      router.replace("/login");
      router.refresh();
    } catch {
      setLogoutError("로그아웃 요청을 보내지 못했습니다. 네트워크를 확인해주세요.");
    } finally {
      setLoggingOut(false);
    }
  }

  if (session.status === "loading") {
    return (
      <main>
        <p data-testid="session-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한
    // 프레임 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다.
    return null;
  }

  return (
    <main>
      <h1 data-testid="operator-home-heading">환영합니다, {session.user.username}</h1>
      <p data-testid="operator-home-grade">
        {session.user.is_superuser ? "상위 등급 (계정 관리 가능)" : "일반 등급"}
      </p>
      <p data-testid="operator-home-protected-content">이 화면은 로그인해야만 보입니다.</p>

      {/* Operator 계정 관리(#69)로 가는 유일한 진입점 — 상위 등급에게만 보인다.
          URL을 직접 쳐야만 들어갈 수 있던 것을 코드리뷰가 지적했다. 일반
          Operator에게는 애초에 링크를 주지 않는다(눌러도 403이 화면에서
          "등급이 필요하다"고 말하긴 하지만, 갈 수 없는 곳으로 가는 링크를
          먼저 보여줄 이유가 없다) — 세 큐 카드(#65/#66/#68 소관)는 건드리지
          않는다. */}
      {session.user.is_superuser && (
        <p>
          <Link href="/operators" data-testid="operators-nav-link">
            Operator 계정 관리
          </Link>
        </p>
      )}

      {/* 정책 화면(#77)으로 가는 진입점 — 계정 관리와 달리 등급을 가리지
          않는다. 조회는 일반 등급도 되므로(#76) 이 링크는 두 등급 모두에게
          보인다 — 편집 가능 여부는 화면 안에서 갈린다. 「할 일」 큐 카드
          (#65/#66/#68 소관)와는 나란히 두지 않는다 — 정책은 처리해야 할
          대기열이 아니다. */}
      <p>
        <Link href="/policy" data-testid="policy-nav-link">
          플랫폼 정책
        </Link>
      </p>

      {/* 산출물 종류 관리(#80)로 가는 진입점 — 정책 화면과 같은 이유로 두
          등급 모두에게 보인다. 최소 제안 상금도 "상금미달" 배지 판정에
          쓰이는 정책값과 같은 무게의 판단이라 정책 화면의 관용구를 그대로
          따른다(#77). */}
      <p>
        <Link href="/deliverable-types" data-testid="deliverable-types-nav-link">
          산출물 종류 관리
        </Link>
      </p>

      {/* 과제 개최 자격 관리(#206)로 가는 진입점 — 정책·산출물 종류 화면과 같은
          이유로 두 등급 모두에게 보인다. 조회는 일반 등급도 되므로(#76의
          규율) 이 링크는 두 등급 모두에게 보이고, 편집 가능 여부는 화면
          안에서 갈린다. */}
      <p>
        <Link href="/assignment-permissions" data-testid="assignment-permissions-nav-link">
          과제 개최 자격 관리
        </Link>
      </p>

      <section data-testid="operator-home-queues">
        <QueueCard
          testId="queue-appeals-pending"
          label="심판 대기 중인 이의"
          href="/appeals?status=pending"
          state={counts}
          pick={(c) => c.pendingAppeals}
        />
        <QueueCard
          testId="queue-payouts-identity"
          label="신원 대기 중인 지급"
          href="/payouts?blocked_on=identity"
          state={counts}
          pick={(c) => c.identityPendingPayouts}
        />
        <QueueCard
          testId="queue-payouts-seller"
          label="Seller 대기 중인 지급"
          href="/payouts?blocked_on=seller"
          state={counts}
          pick={(c) => c.sellerPendingPayouts}
        />
        <QueueCard
          testId="queue-payouts-transfer"
          label="실이체 대기 중인 지급"
          href="/payouts?blocked_on=transfer"
          state={counts}
          pick={(c) => c.transferPendingPayouts}
        />
      </section>

      <button type="button" data-testid="logout-button" onClick={handleLogout} disabled={loggingOut}>
        {loggingOut ? "로그아웃 중..." : "로그아웃"}
      </button>
      {logoutError && (
        <p role="alert" data-testid="logout-error">
          {logoutError}
        </p>
      )}
    </main>
  );
}
