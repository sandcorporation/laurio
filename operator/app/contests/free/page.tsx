"use client";

// 무료 공모전 목록 화면(#420, ADR-0048 — 골간으로 옮긴다, #426/#421). 상태·
// 마감·수상 여부를 보고, 수상자 옆에서 바로 「운영팀 알림 보내기」로 이어진다
// (#418/#419) — 받는 사람이 채워진 채로 그 작성 화면이 열린다
// (`lib/free-contests/notify-link.ts`). 조회는 일반 등급도 된다(정책·카테고리
// 조회와 같은 규율, #76) — 편집이 없는 화면이라 등급 분기 자체가 없다.
//
// 분기 순서는 다른 화면들과 같다 — session.status === "unauthenticated"를
// 로딩 게이트보다 먼저 검사한다(#69의 함정).
import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { useFreeContests } from "@/lib/free-contests/use-free-contests";
import { FreeContestListTable } from "@/lib/free-contests/list-table";

export default function FreeContestsPage() {
  const session = useSession();
  const { state } = useFreeContests(session.status === "authenticated");

  if (session.status === "unauthenticated") {
    return null;
  }

  if (session.status === "loading" || state.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="free-contests-loading">불러오는 중...</p>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        crumb="운영 · 무료 공모전"
        title="무료 공모전"
        description="상태·마감·수상자를 한눈에 보고, 수상자 옆에서 바로 알림으로 넘어갑니다."
      />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        {state.status === "error" && (
          <p role="alert" data-testid="free-contests-error" className="text-[13px] text-attention">
            목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
          </p>
        )}
        {state.status === "loaded" && state.contests.length === 0 && (
          <p data-testid="free-contests-empty" className="text-[13px] text-ink/62">
            무료 공모전이 없습니다.
          </p>
        )}
        {state.status === "loaded" && state.contests.length > 0 && (
          <FreeContestListTable contests={state.contests} />
        )}
      </div>
    </>
  );
}
