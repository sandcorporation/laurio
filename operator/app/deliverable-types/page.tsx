"use client";

// DeliverableType 관리 화면(#80). 조회는 일반 등급도 되고(#76의 규율을 그대로
// 옮긴다), 생성·수정·비활성화는 상위 등급만 — 정책 화면(#77)의 관용구를
// 그대로 따른다: 편집 없음이 「빈 화면」이 아니라 명시적인 안내로 나타난다.
//
// 분기 순서는 operator/app/policy/page.tsx와 같다 — session.status ===
// "unauthenticated"를 로딩 게이트보다 먼저 검사한다(#69의 함정).
import { useRouter } from "next/navigation";
import Link from "next/link";

import { useSession } from "@/lib/auth/use-session";
import { useDeliverableTypes } from "@/lib/deliverable-types/use-deliverable-types";
import { useDeliverableTypeHistory } from "@/lib/deliverable-types/use-deliverable-type-history";
import { CreateTypeForm } from "@/lib/deliverable-types/create-type-form";
import { TypeRow } from "@/lib/deliverable-types/type-row";
import { DeliverableTypeHistoryTable } from "@/lib/deliverable-types/history-table";

export default function DeliverableTypesPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useDeliverableTypes(session.status === "authenticated");
  const { state: historyState, reload: reloadHistory } = useDeliverableTypeHistory(
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
        <p data-testid="deliverable-types-loading">불러오는 중...</p>
      </main>
    );
  }

  const canEdit = session.status === "authenticated" && session.user.is_superuser;

  return (
    <main>
      <h1 data-testid="deliverable-types-heading">산출물 종류 관리</h1>

      {state.status === "error" && (
        <p role="alert" data-testid="deliverable-types-error">
          목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {state.status === "loaded" && (
        <>
          {!canEdit && (
            <p role="alert" data-testid="deliverable-types-edit-forbidden">
              종류를 추가·수정·비활성화하려면 상위 등급 Operator 권한이 필요합니다. 지금은
              조회만 가능합니다.
            </p>
          )}

          <table data-testid="deliverable-types-table">
            <thead>
              <tr>
                <th>이름</th>
                <th>최소 제안 상금</th>
                <th>활성 여부</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {state.types.map((type) => (
                <TypeRow
                  key={type.id}
                  type={type}
                  canEdit={canEdit}
                  onChanged={handleChanged}
                  onSessionExpired={handleSessionExpired}
                />
              ))}
            </tbody>
          </table>

          {canEdit && (
            <CreateTypeForm onCreated={handleChanged} onSessionExpired={handleSessionExpired} />
          )}
        </>
      )}

      <h2>변경 이력</h2>
      {historyState.status === "loading" && (
        <p data-testid="deliverable-type-history-loading">이력을 불러오는 중...</p>
      )}
      {historyState.status === "error" && (
        <p role="alert" data-testid="deliverable-type-history-error">
          변경 이력을 불러오지 못했습니다.
        </p>
      )}
      {historyState.status === "loaded" && (
        <DeliverableTypeHistoryTable
          changes={historyState.changes}
          types={state.status === "loaded" ? state.types : []}
        />
      )}

      <p>
        <Link href="/" data-testid="deliverable-types-back-link">
          홈으로
        </Link>
      </p>
    </main>
  );
}
