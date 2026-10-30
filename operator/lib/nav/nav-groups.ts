// 왼쪽 내비 — 「할 일 · 기준 · 운영」 셋으로 묶은 **한 곳에 선언된 데이터**(#422,
// 부모 #421). 지금 내가 처리해야 하는 일(이의·지급·신고)과, 바꾸면 서비스가
// 흔들리는 기준데이터(정책·카테고리·산출물 종류)와, 계정·권한·알림·무료
// 공모전·사용 현황(운영)을 한 바구니에 담지 않는다 — `docs/design/operator/_lib.py` 의
// `NAV` 와 같은 묶음·순서다.
//
// **순수 데이터다.** `Sidebar` 가 이 배열을 그려 화면을 만들지만, 이 파일
// 자체는 React 를 모른다 — `lib/nav/nav-groups.test.ts` 가 화면을 띄우지
// 않고도 그 항목이 실재하는 라우트를 가리키는지를 잰다.
//
// **`countKey`가 있는 항목만 건수를 보인다**(「할 일」 셋) — 기준·운영은 처리해야
// 할 대기열이 아니라 건수 개념이 없다. 값 자체는 `lib/nav/use-nav-queue-counts.ts`
// 가 계산한다.
export interface NavQueueCounts {
  pendingAppeals: number;
  blockedPayouts: number;
  reportedTemplates: number;
}

export interface NavItem {
  readonly label: string;
  readonly href: string;
  readonly testId: string;
  readonly countKey?: keyof NavQueueCounts;
}

export interface NavGroup {
  readonly title: string;
  readonly items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    title: "할 일",
    items: [
      { label: "이의 심판", href: "/appeals", testId: "nav-appeals", countKey: "pendingAppeals" },
      { label: "지급", href: "/payouts", testId: "nav-payouts", countKey: "blockedPayouts" },
      {
        label: "신고된 템플릿",
        href: "/problem-template-reports",
        testId: "nav-problem-template-reports",
        countKey: "reportedTemplates",
      },
    ],
  },
  {
    title: "기준",
    items: [
      { label: "플랫폼 정책", href: "/policy", testId: "nav-policy" },
      { label: "카테고리", href: "/categories", testId: "nav-categories" },
      { label: "산출물 종류", href: "/deliverable-types", testId: "nav-deliverable-types" },
    ],
  },
  {
    title: "운영",
    items: [
      { label: "운영자 계정", href: "/operators", testId: "nav-operators" },
      { label: "개최 권한", href: "/hosting-permissions", testId: "nav-hosting-permissions" },
      { label: "운영팀 알림", href: "/notifications", testId: "nav-notifications" },
      { label: "무료 공모전", href: "/contests/free", testId: "nav-free-contests" },
      { label: "사용 현황", href: "/usage", testId: "nav-usage" },
      { label: "운영 지표", href: "/ops", testId: "nav-ops" },
    ],
  },
];

/** 지금 보는 화면이 이 항목 아래인가 — 항목 주소 그 자체이거나 그 하위 경로. */
export function isActiveHref(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * 「할 일」 건수의 합 — 좁은 화면에서 내비가 접혀 있을 때 머리의 메뉴 버튼 옆에
 * 이 한 숫자만 보인다(#523). 항목별 건수는 메뉴를 열면 각 줄에 그대로 있다.
 * 어느 항목을 더할지는 `countKey` 가 붙은 항목이 정한다 — 키를 손으로 나열하지 않아야
 * 「할 일」에 항목이 늘 때 이 합이 조용히 빠뜨리지 않는다.
 */
export function totalQueueCount(counts: NavQueueCounts): number {
  let total = 0;
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.countKey) total += counts[item.countKey];
    }
  }
  return total;
}
