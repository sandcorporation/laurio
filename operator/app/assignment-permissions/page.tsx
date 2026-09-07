"use client";

// AssignmentPermission 관리 화면(#206, ADR-0028/0029). 조회는 일반 등급도 되고
// (#76의 규율을 그대로 옮긴다), 부여·회수는 상위 등급만 — 정책·산출물 종류
// 화면(#77/#80)의 관용구를 그대로 따른다: 편집 없음이 「빈 화면」이 아니라
// 명시적인 안내로 나타난다.
//
// 분기 순서는 operator/app/policy/page.tsx와 같다 — session.status ===
// "unauthenticated"를 로딩 게이트보다 먼저 검사한다(#69의 함정).
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { useAssignmentPermissionHolders } from "@/lib/assignment-permissions/use-assignment-permission-holders";
import { useAssignmentPermissionHistory } from "@/lib/assignment-permissions/use-assignment-permission-history";
import { GrantForm } from "@/lib/assignment-permissions/grant-form";
import { HolderRow } from "@/lib/assignment-permissions/holder-row";
import { AssignmentPermissionHistoryTable } from "@/lib/assignment-permissions/history-table";

export default function AssignmentPermissionsPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useAssignmentPermissionHolders(session.status === "authenticated");
  const { state: historyState, reload: reloadHistory } = useAssignmentPermissionHistory(
    session.status === "authenticated",
  );

  function handleSessionExpired() {
    router.replace("/login");
  }

  function handleChanged() {
    reload();
    reloadHistory();
  }

  if (session.status === "unauthenticated") {
    return null;
  }

  if (session.status === "loading" || state.status === "loading") {
    return (
      <main>
        <p data-testid="assignment-permissions-loading">불러오는 중...</p>
      </main>
    );
  }

  const canEdit = session.status === "authenticated" && session.user.is_superuser;

  return (
    <main>
      <h1 data-testid="assignment-permissions-heading">과제 개최 자격 관리</h1>
      <p>
        Assignment(상금 없는 과제)에는 결제가 없어 비용이 스스로 제어되지 않습니다. 개최비가
        서 있던 자리를 이 자격이 대신합니다 — 여기서 준 자격만이 새 과제를 열 수 있습니다.
      </p>

      {state.status === "error" && (
        <p role="alert" data-testid="assignment-permissions-error">
          목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {state.status === "loaded" && (
        <>
          {!canEdit && (
            <p role="alert" data-testid="assignment-permissions-edit-forbidden">
              자격을 주거나 거두려면 상위 등급 Operator 권한이 필요합니다. 지금은 조회만
              가능합니다.
            </p>
          )}

          {state.holders.length === 0 ? (
            <p data-testid="assignment-permissions-empty">
              지금 과제 개최 자격을 가진 Sponsor가 없습니다.
            </p>
          ) : (
            <table data-testid="assignment-permissions-table">
              <thead>
                <tr>
                  <th>사용자명</th>
                  <th>표시 이름</th>
                  <th>작업</th>
                </tr>
              </thead>
              <tbody>
                {state.holders.map((holder) => (
                  <HolderRow
                    key={holder.sponsor_profile_id}
                    holder={holder}
                    canEdit={canEdit}
                    onChanged={handleChanged}
                    onSessionExpired={handleSessionExpired}
                  />
                ))}
              </tbody>
            </table>
          )}

          {canEdit && <GrantForm onGranted={handleChanged} onSessionExpired={handleSessionExpired} />}
        </>
      )}

      <h2>변경 이력</h2>
      {historyState.status === "loading" && (
        <p data-testid="assignment-permission-history-loading">이력을 불러오는 중...</p>
      )}
      {historyState.status === "error" && (
        <p role="alert" data-testid="assignment-permission-history-error">
          변경 이력을 불러오지 못했습니다.
        </p>
      )}
      {historyState.status === "loaded" && (
        <AssignmentPermissionHistoryTable changes={historyState.changes} />
      )}

      <p>
        <Link href="/" data-testid="assignment-permissions-back-link">
          홈으로
        </Link>
      </p>
    </main>
  );
}
