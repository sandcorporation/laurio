"use client";

// Category 관리 화면(#231). 조회는 일반 등급도 되고(#76의 규율을 그대로
// 옮긴다), 생성·이름 수정·감추기는 상위 등급만 — deliverable-types 화면(#80)의
// 관용구를 그대로 따른다: 편집 없음이 「빈 화면」이 아니라 명시적인 안내로
// 나타난다.
//
// 분기 순서는 operator/app/policy/page.tsx·operator/app/deliverable-types/
// page.tsx와 같다 — session.status === "unauthenticated"를 로딩 게이트보다
// 먼저 검사한다(#69의 함정).
import { useRouter } from "next/navigation";
import Link from "next/link";

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
      <main>
        <p data-testid="categories-loading">불러오는 중...</p>
      </main>
    );
  }

  const canEdit = session.status === "authenticated" && session.user.is_superuser;

  return (
    <main>
      <h1 data-testid="categories-heading">카테고리 관리</h1>

      {state.status === "error" && (
        <p role="alert" data-testid="categories-error">
          목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {state.status === "loaded" && (
        <>
          {!canEdit && (
            <p role="alert" data-testid="categories-edit-forbidden">
              카테고리를 추가·수정·감추려면 상위 등급 Operator 권한이 필요합니다. 지금은
              조회만 가능합니다.
            </p>
          )}

          <table data-testid="categories-table">
            <thead>
              <tr>
                <th>이름</th>
                <th>활성 여부</th>
                <th>예약 여부</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {state.categories.map((category) => (
                <CategoryRow
                  key={category.id}
                  category={category}
                  canEdit={canEdit}
                  onChanged={handleChanged}
                  onSessionExpired={handleSessionExpired}
                />
              ))}
            </tbody>
          </table>

          {canEdit && (
            <CreateCategoryForm onCreated={handleChanged} onSessionExpired={handleSessionExpired} />
          )}
        </>
      )}

      <h2>변경 이력</h2>
      {historyState.status === "loading" && (
        <p data-testid="category-history-loading">이력을 불러오는 중...</p>
      )}
      {historyState.status === "error" && (
        <p role="alert" data-testid="category-history-error">
          변경 이력을 불러오지 못했습니다.
        </p>
      )}
      {historyState.status === "loaded" && (
        <CategoryHistoryTable
          changes={historyState.changes}
          categories={state.status === "loaded" ? state.categories : []}
        />
      )}

      <p>
        <Link href="/" data-testid="categories-back-link">
          홈으로
        </Link>
      </p>
    </main>
  );
}
