"use client";

// 홈의 「최근 변경 이력」 조회(#427). 네 화면이 이미 쓰는 이력 조회 액션을 그대로
// 부른다(`use-policy-history.ts` 등과 같은 계약) — 하나라도 실패하면 전체를
// 「불러오지 못했다」로 남긴다. 부분 실패를 부분 표시로 흘리면 「최신순 8건」이
// 사실은 「성공한 출처 안에서 최신 8건」이 되어 조용히 다른 표가 된다.
import { useEffect, useState } from "react";

import { fetchCategoryChanges } from "@/lib/categories/actions";
import { fetchDeliverableTypeChanges } from "@/lib/deliverable-types/actions";
import { fetchHostingPermissionChanges } from "@/lib/hosting-permissions/actions";
import { fetchPolicyChanges } from "@/lib/policies/actions";

import {
  categoryChangesToEntries,
  deliverableTypeChangesToEntries,
  hostingPermissionChangesToEntries,
  mergeRecentChanges,
  policyChangesToEntries,
  type RecentChangeEntry,
} from "./recent-changes";

export type RecentChangesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: RecentChangeEntry[] };

const RECENT_CHANGES_LIMIT = 8;

export function useRecentChanges(enabled: boolean): RecentChangesState {
  const [state, setState] = useState<RecentChangesState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    void Promise.all([
      fetchPolicyChanges(),
      fetchCategoryChanges(),
      fetchDeliverableTypeChanges(),
      fetchHostingPermissionChanges(),
    ]).then(([policy, category, deliverableType, hostingPermission]) => {
      if (cancelled) return;
      if (!policy.ok || !category.ok || !deliverableType.ok || !hostingPermission.ok) {
        setState({ status: "error" });
        return;
      }
      setState({
        status: "loaded",
        changes: mergeRecentChanges(
          [
            policyChangesToEntries(policy.data),
            categoryChangesToEntries(category.data),
            deliverableTypeChangesToEntries(deliverableType.data),
            hostingPermissionChangesToEntries(hostingPermission.data),
          ],
          RECENT_CHANGES_LIMIT,
        ),
      });
    });

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return state;
}
