"use client";

// 무료 공모전 개최 권한 관리 화면(#414, ADR-0048). 계정을 검색해 켜고 끄고,
// 지금 권한을 가진 계정 목록과 변경 이력을 본다. 조회는 일반 등급도 되고
// (#76의 규율을 그대로 옮긴다), 켜고 끄는 것은 상위 등급만 —
// `app/deliverable-types/page.tsx`와 같은 모양이다.
//
// 분기 순서는 다른 화면들과 같다 — session.status === "unauthenticated"를
// 로딩 게이트보다 먼저 검사한다(#69의 함정).
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { useGrantedHostingPermissionAccounts } from "@/lib/hosting-permissions/use-granted-accounts";
import { useHostingPermissionHistory } from "@/lib/hosting-permissions/use-history";
import { HostingPermissionAccountSearch } from "@/lib/hosting-permissions/account-search";
import { HostingPermissionAccountRow } from "@/lib/hosting-permissions/account-row";
import { HostingPermissionHistoryTable } from "@/lib/hosting-permissions/history-table";

export default function HostingPermissionsPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useGrantedHostingPermissionAccounts(
    session.status === "authenticated",
  );
  const { state: historyState, reload: reloadHistory } = useHostingPermissionHistory(
    session.status === "authenticated",
  );
  // 「권한 보유 계정」 표에서 바꾼 결과를 검색 결과 표에도 반영한다(위
  // account-search.tsx의 refreshSignal 주석 참고) — 검색은 자기 상태라 저절로
  // 안 바뀐다.
  const [searchRefresh, setSearchRefresh] = useState(0);

  function handleSessionExpired() {
    router.replace("/login");
  }

  function handleChanged() {
    reload();
    reloadHistory();
    setSearchRefresh((v) => v + 1);
  }

  if (session.status === "unauthenticated") {
    return null;
  }

  if (session.status === "loading") {
    return (
      <main>
        <p data-testid="hosting-permissions-loading">불러오는 중...</p>
      </main>
    );
  }

  const canEdit = session.status === "authenticated" && session.user.is_superuser;

  return (
    <main>
      <h1 data-testid="hosting-permissions-heading">무료 공모전 개최 권한</h1>

      {!canEdit && (
        <p role="alert" data-testid="hosting-permissions-edit-forbidden">
          권한을 켜고 끄려면 상위 등급 Operator 권한이 필요합니다. 지금은 조회만
          가능합니다.
        </p>
      )}

      <h2>계정 검색</h2>
      <HostingPermissionAccountSearch
        canEdit={canEdit}
        refreshSignal={searchRefresh}
        onChanged={handleChanged}
        onSessionExpired={handleSessionExpired}
      />

      <h2>권한 보유 계정</h2>
      {state.status === "loading" && (
        <p data-testid="hosting-permission-granted-loading">불러오는 중...</p>
      )}
      {state.status === "error" && (
        <p role="alert" data-testid="hosting-permission-granted-error">
          목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}
      {state.status === "loaded" && state.accounts.length === 0 && (
        <p data-testid="hosting-permission-granted-empty">권한을 가진 계정이 없습니다.</p>
      )}
      {state.status === "loaded" && state.accounts.length > 0 && (
        <table data-testid="hosting-permission-granted-table">
          <thead>
            <tr>
              <th>이메일</th>
              <th>닉네임</th>
              <th>개최 권한</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {state.accounts.map((account) => (
              <HostingPermissionAccountRow
                key={account.user_id}
                account={account}
                canEdit={canEdit}
                onChanged={handleChanged}
                onSessionExpired={handleSessionExpired}
              />
            ))}
          </tbody>
        </table>
      )}

      <h2>변경 이력</h2>
      {historyState.status === "loading" && (
        <p data-testid="hosting-permission-history-loading">이력을 불러오는 중...</p>
      )}
      {historyState.status === "error" && (
        <p role="alert" data-testid="hosting-permission-history-error">
          변경 이력을 불러오지 못했습니다.
        </p>
      )}
      {historyState.status === "loaded" && (
        <HostingPermissionHistoryTable changes={historyState.changes} />
      )}

      <p>
        <Link href="/" data-testid="hosting-permissions-back-link">
          홈으로
        </Link>
      </p>
    </main>
  );
}
