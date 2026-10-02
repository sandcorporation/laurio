"use client";

// Category 관리 화면(#231, #425 — 골간으로 옮긴다). 조회는 일반 등급도 되고
// (#76의 규율을 그대로 옮긴다), 생성·이름 수정·감추기는 상위 등급만 —
// deliverable-types 화면(#80)의 관용구를 그대로 따른다: 편집 없음이 「빈
// 화면」이 아니라 명시적인 안내로 나타난다.
//
// 분기 순서는 operator/app/policy/page.tsx·operator/app/deliverable-types/
// page.tsx와 같다 — session.status === "unauthenticated"를 로딩 게이트보다
// 먼저 검사한다(#69의 함정).
import { useRouter } from "next/navigation";

import { PageHeader } from "@/app/components/page-header";
import { TableScroll } from "@/app/components/table-scroll";
import { useSession } from "@/lib/auth/use-session";
import { useCategories } from "@/lib/categories/use-categories";
import { useCategoryHistory } from "@/lib/categories/use-category-history";
import { CreateCategoryForm } from "@/lib/categories/create-category-form";
import { CategoryRow } from "@/lib/categories/category-row";
import { CategoryHistoryTable } from "@/lib/categories/history-table";

export default function CategoriesPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useCategories(session.status === "authenticated");
  const { state: historyState, reload: reloadHistory } = useCategoryHistory(
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
      <div className="p-4 sm:p-8">
        <p data-testid="categories-loading">불러오는 중...</p>
      </div>
    );
  }

  const canEdit = session.status === "authenticated" && session.user.is_superuser;

  return (
    <>
      <PageHeader
        crumb="기준 · 카테고리"
        title="카테고리 관리"
        description="공개 목록의 분류 축이다. 지우지 않고 감추기만 한다 — 이미 참조하는 공모전이 있어서다."
      />
      <div className="flex flex-1 flex-col gap-6 p-4 sm:p-8">
        {state.status === "error" && (
          <p role="alert" data-testid="categories-error" className="text-[13px] text-attention">
            목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
          </p>
        )}

        {state.status === "loaded" && (
          <>
            {!canEdit && (
              <p role="alert" data-testid="categories-edit-forbidden" className="text-[13px] text-attention">
                카테고리를 추가·수정·감추려면 상위 등급 Operator 권한이 필요합니다. 지금은
                조회만 가능합니다.
              </p>
            )}

            <div data-testid="categories-table" className="border border-rule bg-surface">
              <TableScroll minWidth={500}>
                <div className="flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
                  <div className="min-w-0 flex-1">이름</div>
                  <div className="w-[70px] shrink-0">활성 여부</div>
                  <div className="w-[220px] shrink-0 text-right">작업</div>
                </div>
                {state.categories.length === 0 ? (
                  <p data-testid="categories-empty" className="px-4 py-3 text-[13px] text-ink/62">
                    아직 등록된 카테고리가 없습니다.
                  </p>
                ) : (
                  state.categories.map((category, i) => (
                    <CategoryRow
                      key={category.id}
                      category={category}
                      canEdit={canEdit}
                      zebra={i % 2 === 1}
                      onChanged={handleChanged}
                      onSessionExpired={handleSessionExpired}
                    />
                  ))
                )}
              </TableScroll>
            </div>

            {canEdit && (
              <CreateCategoryForm onCreated={handleChanged} onSessionExpired={handleSessionExpired} />
            )}
          </>
        )}

        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h2 className="text-[15px] font-semibold tracking-[-0.01em]">변경 이력</h2>
            <p data-testid="category-history-immutable-note" className="text-[12px] text-ink/62">
              이 이력은 고치거나 지울 수 없습니다.
            </p>
          </div>
          <div className="mt-2.5">
            {historyState.status === "loading" && (
              <p data-testid="category-history-loading" className="text-[13px] text-ink/62">
                이력을 불러오는 중...
              </p>
            )}
            {historyState.status === "error" && (
              <p role="alert" data-testid="category-history-error" className="text-[13px] text-attention">
                변경 이력을 불러오지 못했습니다.
              </p>
            )}
            {historyState.status === "loaded" && (
              <CategoryHistoryTable
                changes={historyState.changes}
                categories={state.status === "loaded" ? state.categories : []}
              />
            )}
          </div>
        </div>
      </div>
    </>
  );
}
