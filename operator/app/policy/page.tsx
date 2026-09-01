"use client";

// 정책 화면(#77) — 지금 요율표를 보고, 이력을 읽고, 상위 등급이면 바꾼다.
//
// **분기 순서(#69의 함정).** `session.status === "unauthenticated"` 검사를
// 로딩 검사보다 먼저 둔다 — 세션이 죽으면(쿠키는 남았지만 백엔드가 더 이상
// 인정하지 않으면) session.status는 "loading"을 거치지 않고 곧장
// "unauthenticated"로 간다. 이 검사를 나중에 두면 `usePolicy`의 effect가 한
// 번도 실행되지 않아 정책 조회 state가 초기값 "loading"에 영원히 머물고,
// 그 state를 반영하는 로딩 게이트가 화면을 스피너에 가둬 useSession이 이미
// 시작한 /login 리다이렉트를 가린다(`operator/app/operators/page.tsx`와 같은
// 원칙).
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { usePolicy } from "@/lib/policies/use-policy";
import { usePolicyHistory } from "@/lib/policies/use-policy-history";
import { PolicyEditor } from "@/lib/policies/policy-editor";
import { PolicyHistoryTable } from "@/lib/policies/policy-history";
import { PolicyValuesTable } from "@/lib/policies/policy-values-table";

export default function PolicyPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = usePolicy(session.status === "authenticated");
  const { state: historyState, reload: reloadHistory } = usePolicyHistory(
    session.status === "authenticated",
  );

  function handleSessionExpired() {
    router.replace("/login");
  }

  function handleSaved() {
    reload();
    reloadHistory();
  }

  if (session.status === "unauthenticated") {
    return null;
  }

  if (session.status === "loading" || state.status === "loading") {
    return (
      <main>
        <p data-testid="policy-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <main>
      <h1 data-testid="policy-heading">플랫폼 정책</h1>

      {state.status === "error" && (
        <p role="alert" data-testid="policy-error">
          정책값을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {state.status === "loaded" && (
        <>
          <PolicyValuesTable policy={state.policy} />

          {session.user.is_superuser ? (
            <PolicyEditor
              policy={state.policy}
              onSaved={handleSaved}
              onNeedsReload={reload}
              onSessionExpired={handleSessionExpired}
            />
          ) : (
            // 「너는 안 된다」와 「여기엔 아무것도 없다」가 다르게 읽혀야 한다
            // (계정 관리 화면이 세운 관용구, #69). 값 표는 이미 위에서
            // 정상적으로 보였으므로, 여기서는 편집만 못 한다는 사실을 명시적으로
            // 말한다 — 편집 폼을 그냥 생략해 "여기엔 아무것도 없다"처럼 보이게
            // 두지 않는다.
            <p role="alert" data-testid="policy-edit-forbidden">
              이 값을 바꾸려면 상위 등급 Operator 권한이 필요합니다. 지금은 조회만 가능합니다.
            </p>
          )}
        </>
      )}

      <h2>변경 이력</h2>
      {historyState.status === "loading" && (
        <p data-testid="policy-history-loading">이력을 불러오는 중...</p>
      )}
      {historyState.status === "error" && (
        <p role="alert" data-testid="policy-history-error">
          변경 이력을 불러오지 못했습니다.
        </p>
      )}
      {historyState.status === "loaded" && <PolicyHistoryTable changes={historyState.changes} />}

      <p>
        <Link href="/" data-testid="policy-back-link">
          홈으로
        </Link>
      </p>
    </main>
  );
}
