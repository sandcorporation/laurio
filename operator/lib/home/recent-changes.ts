// 홈의 「최근 변경 이력」 표(#427, 부모 #421 시안 `docs/design/operator/Home.dc.html`)
// — 기준데이터 넷(정책·카테고리·산출물 종류·개최 권한)이 각자 화면에 이미 갖고
// 있는 변경 이력 조회를 그대로 재사용해 합친다. 새 백엔드 조회를 만들지 않는다
// (#421 「바꾸지 않는 것」) — 각 화면의 `use*History` 훅이 부르는 것과 같은 액션
// 함수를 홈도 그대로 부른다.
//
// **순수 함수만 여기 둔다.** 합치고 정렬하는 로직을 훅(`use-recent-changes.ts`)
// 에서 떼어내 화면을 띄우지 않고도 잴 수 있게 한다 — `nav-groups.ts`와 같은
// 원칙.
// 상대 경로로 임포트한다 — 이 파일의 vitest(`vitest.config.mts`)는 `@/` 별칭을
// 해석하지 않는다(다른 순수 모듈 테스트도 전부 상대 경로다).
import { actionLabel as categoryActionLabel } from "../categories/types";
import type { CategoryChangeEntry } from "../categories/types";
import { actionLabel as deliverableTypeActionLabel } from "../deliverable-types/types";
import type { DeliverableTypeChangeEntry } from "../deliverable-types/types";
import { actionLabel as hostingPermissionActionLabel } from "../hosting-permissions/types";
import type { HostingPermissionChangeEntry } from "../hosting-permissions/types";
import { POLICY_FIELD_LABELS } from "../policies/types";
import type { PolicyChangeEntry, PolicyField } from "../policies/types";

export interface RecentChangeEntry {
  key: string;
  /** 「무엇」 열 — 어느 화면의 이력인지. */
  what: string;
  /** 「무슨 값이 어떻게」 열. */
  summary: string;
  operatorUsername: string;
  changedAt: string;
}

function formatPolicyDiff(change: PolicyChangeEntry): string {
  const fields = Object.keys(change.after) as PolicyField[];
  return fields
    .map((field) => {
      const label = POLICY_FIELD_LABELS[field] ?? field;
      return `${label} ${change.before[field]} → ${change.after[field]}`;
    })
    .join(", ");
}

function formatRecordDiff(before: Record<string, unknown>, after: Record<string, unknown>): string {
  const keys = Object.keys(after);
  if (keys.length === 0) return "생성";
  return keys.map((key) => `${key} ${String(before[key] ?? "-")} → ${String(after[key])}`).join(", ");
}

export function policyChangesToEntries(changes: readonly PolicyChangeEntry[]): RecentChangeEntry[] {
  return changes.map((change) => ({
    key: `policy-${change.id}`,
    what: "플랫폼 정책",
    summary: formatPolicyDiff(change),
    operatorUsername: change.operator_username,
    changedAt: change.changed_at,
  }));
}

export function categoryChangesToEntries(changes: readonly CategoryChangeEntry[]): RecentChangeEntry[] {
  return changes.map((change) => ({
    key: `category-${change.id}`,
    what: "카테고리",
    summary: `${categoryActionLabel(change.action)} #${change.category_id} — ${formatRecordDiff(change.before, change.after)}`,
    operatorUsername: change.operator_username,
    changedAt: change.changed_at,
  }));
}

export function deliverableTypeChangesToEntries(
  changes: readonly DeliverableTypeChangeEntry[],
): RecentChangeEntry[] {
  return changes.map((change) => ({
    key: `deliverable-type-${change.id}`,
    what: "산출물 종류",
    summary: `${deliverableTypeActionLabel(change.action)} #${change.deliverable_type_id} — ${formatRecordDiff(change.before, change.after)}`,
    operatorUsername: change.operator_username,
    changedAt: change.changed_at,
  }));
}

export function hostingPermissionChangesToEntries(
  changes: readonly HostingPermissionChangeEntry[],
): RecentChangeEntry[] {
  return changes.map((change) => ({
    key: `hosting-permission-${change.id}`,
    what: "개최 권한",
    summary: `${hostingPermissionActionLabel(change.action)} — ${change.user_email}`,
    operatorUsername: change.operator_username,
    changedAt: change.changed_at,
  }));
}

/** 네 출처를 합쳐 최신순으로 자른다. */
export function mergeRecentChanges(entryLists: readonly RecentChangeEntry[][], limit: number): RecentChangeEntry[] {
  return entryLists
    .flat()
    .sort((a, b) => new Date(b.changedAt).getTime() - new Date(a.changedAt).getTime())
    .slice(0, limit);
}
