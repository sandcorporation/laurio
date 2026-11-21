"use client";

// 제보 권한 관리 화면(#1243, 스펙 #1237) — `app/hosting-permissions/page.tsx` 꼴이다. 계정을
// 검색해 켜고 끄고, 지금 권한을 가진 계정 목록과 변경 이력을 본다. 조회는 일반
// 등급도 되고(#76의 규율을 그대로 옮긴다), 켜고 끄는 것은 상위 등급만 —
// `app/deliverable-types/page.tsx`와 같은 모양이다.
//
// 분기 순서는 다른 화면들과 같다 — session.status === "unauthenticated"를
// 로딩 게이트보다 먼저 검사한다(#69의 함정).
import { useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
import { TableScroll } from "@/app/components/table-scroll";
import { useSession } from "@/lib/auth/use-session";
import { useGrantedFeedbackPermissionAccounts } from "@/lib/feedback-permissions/use-granted-accounts";
import { useFeedbackPermissionHistory } from "@/lib/feedback-permissions/use-history";
import { FeedbackPermissionAccountSearch } from "@/lib/feedback-permissions/account-search";
import { FeedbackPermissionAccountRow } from "@/lib/feedback-permissions/account-row";
import { FeedbackPermissionHistoryTable } from "@/lib/feedback-permissions/history-table";
import { FeedbackPermissionTableHead } from "@/lib/feedback-permissions/table-columns";

export default function FeedbackPermissionsPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useGrantedFeedbackPermissionAccounts(
    session.status === "authenticated",
  );
  const { state: historyState, reload: reloadHistory } = useFeedbackPermissionHistory(
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
      <div className="p-4 sm:p-8">
        <p data-testid="feedback-permissions-loading">불러오는 중...</p>
      </div>
    );
  }

  const canEdit = session.status === "authenticated" && session.user.is_superuser;

  return (
    <>
      <PageHeader
        crumb="운영 · 제보 권한"
        title="제보 권한"
      />
      <div className="flex flex-1 flex-col gap-[18px] p-4 sm:p-8">
        {!canEdit && (
          <p role="alert" data-testid="feedback-permissions-edit-forbidden" className="text-[13px] text-attention">
            권한을 켜고 끄려면 상위 등급 Operator 권한이 필요합니다. 지금은 조회만
            가능합니다.
          </p>
        )}

        <FeedbackPermissionAccountSearch
          canEdit={canEdit}
          refreshSignal={searchRefresh}
          onChanged={handleChanged}
          onSessionExpired={handleSessionExpired}
        />

        <Panel title="권한 보유 계정">
          {state.status === "loading" && (
            <p data-testid="feedback-permission-granted-loading" className="px-[15px] py-[14px] text-[13px] text-ink/62">
              불러오는 중...
            </p>
          )}
          {state.status === "error" && (
            <p role="alert" data-testid="feedback-permission-granted-error" className="px-[15px] py-[14px] text-[13px] text-attention">
              목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
            </p>
          )}
          {state.status === "loaded" && state.accounts.length === 0 && (
            <p data-testid="feedback-permission-granted-empty" className="px-[15px] py-[14px] text-[13px] text-ink/62">
              권한을 가진 계정이 없습니다.
            </p>
          )}
          {state.status === "loaded" && state.accounts.length > 0 && (
            <div data-testid="feedback-permission-granted-table">
              <TableScroll minWidth={680}>
                <FeedbackPermissionTableHead />
                {state.accounts.map((account) => (
                  <FeedbackPermissionAccountRow
                    key={account.user_id}
                    account={account}
                    canEdit={canEdit}
                    onChanged={handleChanged}
                    onSessionExpired={handleSessionExpired}
                  />
                ))}
              </TableScroll>
            </div>
          )}
        </Panel>

        <Panel title="변경 이력">
          {historyState.status === "loading" && (
            <p data-testid="feedback-permission-history-loading" className="px-[15px] py-[14px] text-[13px] text-ink/62">
              이력을 불러오는 중...
            </p>
          )}
          {historyState.status === "error" && (
            <p role="alert" data-testid="feedback-permission-history-error" className="px-[15px] py-[14px] text-[13px] text-attention">
              변경 이력을 불러오지 못했습니다.
            </p>
          )}
          {historyState.status === "loaded" && (
            <FeedbackPermissionHistoryTable changes={historyState.changes} />
          )}
        </Panel>
      </div>
    </>
  );
}
