"use client";

// 「할 일」 홈(#65, 골간으로 옮긴다 — #427, 부모 #421). 운영자가 이 앱을 여는
// 이유는 단 하나 — 자기를 기다리는 것이 무엇인지 알기 위해서다. 시안
// (`docs/design/operator/Home.dc.html`)의 두 조각만 옮긴다: 세 큐를 건수·
// 「가장 오래 밀린 것」과 함께 한 표로 보여주는 것, 그리고 그 아래 최근 변경
// 이력 표. 화면 열둘을 오가는 옛 링크 목록은 왼쪽 내비(`nav-groups.ts`)가
// 이미 대신하므로 다시 만들지 않는다 — 단 하나(`policy-nav-link`)만 남긴다,
// 기존 e2e(policy.spec.ts)가 홈에서 그 testid로 정책 화면에 들어가기 때문이다.
import { useState } from "react";

import { normalizeDetail } from "@codemit/bff-client";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
import { TableScroll } from "@/app/components/table-scroll";
import { useSession } from "@/lib/auth/use-session";
import { appealsDetail, payoutsDetail } from "@/lib/home/queue-row-detail";
import { useQueueCounts } from "@/lib/home/use-queue-counts";
import { useRecentChanges } from "@/lib/home/use-recent-changes";
import { useReportedTemplatesCount } from "@/lib/home/use-reported-templates-count";

interface TodoRow {
  testId: string;
  label: string;
  href: string;
  count: number | null;
  loading: boolean;
  error: boolean;
  detail: string | null;
}

const COL = {
  label: "w-[240px]",
  count: "w-[64px]",
  action: "w-[64px]",
};

function TodoTableHead() {
  return (
    <div className="flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className={`${COL.label} shrink-0`}>큐</div>
      <div className={`${COL.count} shrink-0`}>건수</div>
      <div className="min-w-0 flex-1" />
      <div className={`${COL.action} shrink-0`} />
    </div>
  );
}

function TodoRowView({ row, index }: { row: TodoRow; index: number }) {
  return (
    <Link
      href={row.href}
      data-testid={row.testId}
      className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
        index % 2 === 1 ? "bg-ink/[2%]" : ""
      }`}
    >
      <div className={`${COL.label} shrink-0 truncate`}>{row.label}</div>
      <div className={`${COL.count} shrink-0`}>
        {row.loading && <span data-testid={`${row.testId}-loading`}>...</span>}
        {row.error && (
          <span role="alert" data-testid={`${row.testId}-error`} className="text-attention">
            !
          </span>
        )}
        {!row.loading && !row.error && row.count === 0 && (
          <span data-testid={`${row.testId}-empty`} className="text-ink/45">
            0
          </span>
        )}
        {!row.loading && !row.error && row.count !== null && row.count > 0 && (
          <span data-testid={`${row.testId}-count`} className="font-mono text-[14px] font-semibold">
            {row.count}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1 truncate text-[12.5px] text-ink/62">{row.detail}</div>
      <div className={`${COL.action} shrink-0`}>
        <Badge tone="neutral">보기</Badge>
      </div>
    </Link>
  );
}

export default function OperatorHome() {
  const session = useSession();
  const enabled = session.status === "authenticated";
  const counts = useQueueCounts(enabled);
  const reportedTemplates = useReportedTemplatesCount(enabled);
  const recentChanges = useRecentChanges(enabled);
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
      <div className="p-4 sm:p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한
    // 프레임 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다.
    return null;
  }

  const rows: TodoRow[] = [
    {
      testId: "queue-appeals-pending",
      label: "심판 대기 중인 이의",
      href: "/appeals?status=pending",
      count: counts.status === "loaded" ? counts.counts.pendingAppeals : null,
      loading: counts.status === "loading",
      error: counts.status === "error",
      detail:
        counts.status === "loaded"
          ? appealsDetail(counts.counts.pendingAppeals, counts.counts.oldestPendingAppealDays)
          : null,
    },
    {
      testId: "queue-payouts-blocked",
      label: "지급 대기",
      href: "/payouts",
      count:
        counts.status === "loaded"
          ? counts.counts.identityPendingPayouts +
            counts.counts.sellerPendingPayouts +
            counts.counts.transferPendingPayouts
          : null,
      loading: counts.status === "loading",
      error: counts.status === "error",
      detail:
        counts.status === "loaded"
          ? payoutsDetail(
              counts.counts.identityPendingPayouts,
              counts.counts.sellerPendingPayouts,
              counts.counts.transferPendingPayouts,
            )
          : null,
    },
    {
      testId: "queue-reported-templates",
      label: "신고된 템플릿",
      href: "/problem-template-reports",
      count: reportedTemplates.status === "loaded" ? reportedTemplates.count : null,
      loading: reportedTemplates.status === "loading",
      error: reportedTemplates.status === "error",
      detail: "검토하면 목록에서 사라진다",
    },
  ];

  return (
    <>
      <PageHeader
        crumb="운영자 · 할 일"
        title={`환영합니다, ${session.user.username}`}
        titleTestId="operator-home-heading"
        description="사람이 판단할 일만 모인다 — 스캔이 도는 일은 여기 오지 않는다."
        actions={
          <button
            type="button"
            data-testid="logout-button"
            onClick={handleLogout}
            disabled={loggingOut}
            className="border border-rule bg-surface px-2.5 py-1 text-[11.5px] text-ink/62 hover:border-ink hover:text-ink disabled:opacity-50"
          >
            {loggingOut ? "로그아웃 중..." : "로그아웃"}
          </button>
        }
      />
      <div className="flex flex-1 flex-col gap-[18px] p-4 sm:p-8">
        <div className="flex items-center gap-2 text-[12.5px] text-ink/62">
          <span data-testid="operator-home-grade">
            {session.user.is_superuser ? "상위 등급" : "일반 등급"}
          </span>
          {/* AC(auth.spec.ts)가 인증 뒤 이 요소가 여전히 있는지를 기준으로 삼는다 —
              내용을 화면에 크게 말할 이유가 없어 화면 낭독기용으로만 남긴다. */}
          <span data-testid="operator-home-protected-content" className="sr-only">
            이 화면은 로그인해야만 보입니다.
          </span>
        </div>

        {logoutError && (
          <p role="alert" data-testid="logout-error" className="text-[12.5px] text-attention">
            {logoutError}
          </p>
        )}

        <div data-testid="operator-home-queues" className="border border-rule bg-surface">
          <TableScroll minWidth={560}>
            <TodoTableHead />
            {rows.map((row, i) => (
              <TodoRowView key={row.testId} row={row} index={i} />
            ))}
          </TableScroll>
        </div>

        <Panel
          title="최근 변경 이력"
          meta="바꾼 사람과 시각이 남는다 — 지울 수 없다"
          actions={
            <Link
              href="/policy"
              data-testid="policy-nav-link"
              className="text-[12px] text-ink/62 hover:text-ink"
            >
              플랫폼 정책 화면
            </Link>
          }
        >
          {recentChanges.status === "loading" && (
            <p data-testid="recent-changes-loading" className="px-4 py-3.5 text-[13px] text-ink/62">
              불러오는 중...
            </p>
          )}
          {recentChanges.status === "error" && (
            <p role="alert" data-testid="recent-changes-error" className="px-4 py-3.5 text-[13px] text-attention">
              불러오지 못했습니다.
            </p>
          )}
          {recentChanges.status === "loaded" && recentChanges.changes.length === 0 && (
            <p data-testid="recent-changes-empty" className="px-4 py-3.5 text-[13px] text-ink/62">
              아직 변경 이력이 없습니다.
            </p>
          )}
          {recentChanges.status === "loaded" && recentChanges.changes.length > 0 && (
            <div data-testid="recent-changes-table">
              <TableScroll minWidth={680}>
                <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
                  <div className="w-[110px] shrink-0">무엇</div>
                  <div className="min-w-0 flex-1">무슨 값이 어떻게</div>
                  <div className="w-[110px] shrink-0">누가</div>
                  {/* `toLocaleString("ko-KR")` 이 「2026. 9. 15. 오후 3:19:00」 까지 낸다 —
                      130px 에서는 넓은 화면에서도 끝이 잘렸다(2026-09-16 스크린샷). 형식을
                      줄이지 않고 칸을 넓힌다: 다른 이력 표들과 같은 형식이어야 한다. */}
                  <div className="w-[206px] shrink-0">언제</div>
                </div>
                {recentChanges.changes.map((change, i) => (
                  <div
                    key={change.key}
                    data-testid={`recent-changes-row-${change.key}`}
                    className={`flex gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
                      i % 2 === 1 ? "bg-ink/[2%]" : ""
                    }`}
                  >
                    <div className="w-[110px] shrink-0 truncate">{change.what}</div>
                    <div className="min-w-0 flex-1 truncate">{change.summary}</div>
                    <div className="w-[110px] shrink-0 truncate font-mono">{change.operatorUsername}</div>
                    <div className="w-[206px] shrink-0 truncate font-mono text-ink/62">
                      {new Date(change.changedAt).toLocaleString("ko-KR")}
                    </div>
                  </div>
                ))}
              </TableScroll>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
