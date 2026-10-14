"use client";

// 「내 클래스」 홈 (#278, 스타일 #298, 참여자 동선 #328). `app/page.tsx`가
// 로그인 쿠키가 있을 때(`lib/landing/decide-root-view.ts`) 이 컴포넌트를
// 그린다(#395) — 그 판정은 쿠키의 "존재"만 본다(가드와 같은 원칙, 유효성은
// 언제나 백엔드 몫). 쿠키가 있는데 만료된 경우는 예전과 같다 — 아래 훅들이
// 조회 실패를 "error" 상태로 보여줄 뿐, 이 화면이 스스로 `/login`으로 보내지
// 않는다(이 티켓이 바꾸는 범위 밖이다).
//
// 인증 구역이므로 SSR 하지 않는다(frontend/app/console/contests/page.tsx와
// 같은 이유, ADR-0015) — 클라이언트 컴포넌트로 목록을 받아온다.
import Link from "next/link";

import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Num,
  PageHeader,
  PageShell,
  SectionHeading,
  buttonClass,
  type ButtonTone,
} from "@/app/components/ui";
import type { ClassRow, JoinedClassRow } from "@/lib/classes/api";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import { useJoinedClasses } from "@/lib/classes/use-joined-classes";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { achievementTone } from "@/lib/problems/achievement";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

// 「새 클래스 열기」·「템플릿 둘러보기」 — 머리(강사만인 사람·둘 다인 사람·아무
// 데도 안 속한 사람)와 참여 중인 클래스 목록 뒤(참여자로만 속한 사람)에 각각
// 다른 모양(tone·크기)으로 나온다(#342 후속). href·testid·문구를 두 곳에 따로
// 적으면 라우트나 문구가 바뀔 때 한쪽만 고치고 지나가기 쉬워 여기 하나로 묶는다.
function ClassActionLinks({
  newClassTone,
  size = "md",
}: {
  newClassTone: ButtonTone;
  size?: "sm" | "md";
}) {
  return (
    <>
      <Link
        href="/templates"
        data-testid="classroom-browse-templates-link"
        className={buttonClass("secondary", size)}
      >
        템플릿 둘러보기
      </Link>
      <Link
        href="/classes/new"
        data-testid="classroom-new-class-link"
        className={buttonClass(newClassTone, size)}
      >
        새 클래스 열기
      </Link>
    </>
  );
}

const TONE_TEXT = { verified: "text-verified", attention: "text-attention", ink: "text-ink" } as const;
const TONE_BAR = { verified: "bg-verified", attention: "bg-attention", ink: "bg-ink" } as const;

// 행 오른쪽의 막대 — 가르치는 행은 「61% 달성률」, 참여 중 행은 「3/6 통과」(시안 v2 Home).
// 보관 행은 색을 빼고 흐리게 한다. `ratio` 가 null 이면 빈 막대에 「—」다.
function RowBar({
  ratio,
  value,
  caption,
  testId,
  dim = false,
  plain = false,
}: {
  ratio: number | null;
  value: string;
  caption: string;
  testId: string;
  dim?: boolean;
  /** 색 규칙(60/30)을 적용하지 않고 ink 로 둔다 — 참여 중 행의 「k/n 통과」. */
  plain?: boolean;
}) {
  const tone = ratio === null || plain ? "ink" : achievementTone(ratio);
  const fill = dim ? "bg-ink/30" : TONE_BAR[tone];
  const text = dim ? "text-ink/30" : ratio === null ? "text-ink/45" : TONE_TEXT[tone];
  return (
    <div data-testid={testId} className="flex w-[220px] shrink-0 items-center gap-2.5">
      <div className="relative h-1.5 w-[120px] shrink-0 border border-rule bg-paper">
        <div
          className={`absolute inset-y-0 left-0 ${fill}`}
          style={{ width: `${Math.round(Math.max(0, Math.min(1, ratio ?? 0)) * 100)}%` }}
        />
      </div>
      <span className={`font-mono text-[13px] font-semibold ${text}`}>{value}</span>
      <span className="text-[11px] text-ink/30">{caption}</span>
    </div>
  );
}

function ClassList({
  classes,
  testId,
  archived,
}: {
  classes: ClassRow[];
  testId: string;
  archived: boolean;
}) {
  return (
    <Card>
      <ul data-testid={testId} className="divide-y divide-rule">
        {classes.map((classroom) => {
          const rate = classroom.average_pass_rate;
          return (
            <li
              key={classroom.id}
              data-testid={`classroom-row-${classroom.id}`}
              className="flex flex-wrap items-center gap-x-6 gap-y-3 px-[18px] py-3.5"
            >
              <div className="min-w-0 flex-1 basis-[220px]">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/classes/${classroom.id}`}
                    data-testid={`classroom-row-${classroom.id}-link`}
                    className={`text-[15px] font-medium hover:underline ${archived ? "text-ink/30" : "text-ink"}`}
                  >
                    {classroom.name}
                  </Link>
                  {/* 소유한 클래스와 공동 강사인 클래스가 한 목록에 섞인다(#561) — 어느 쪽인지
                      가른다. 소유자 쪽은 지금까지처럼 아무 표시도 없다. */}
                  {classroom.role === "co_instructor" ? (
                    <span data-testid={`classroom-row-${classroom.id}-co-instructor-badge`}>
                      <Badge>공동 강사</Badge>
                    </span>
                  ) : null}
                  {/* 나에게 온 소유권 이전 요청(#564) — 클래스 화면에서 답한다. */}
                  {classroom.pending_ownership_transfer?.recipient_is_me ? (
                    <span data-testid={`classroom-row-${classroom.id}-ownership-transfer-badge`}>
                      <Badge tone="attention">소유권 이전 요청</Badge>
                    </span>
                  ) : null}
                </div>
                <div
                  data-testid={`classroom-row-${classroom.id}-stats`}
                  className="mt-[3px] text-[12px] text-ink/45"
                >
                  참여자 <Num>{classroom.member_count}</Num>명 · 문제 <Num>{classroom.problem_count}</Num>개
                  {classroom.last_submitted_at ? (
                    <> · 마지막 제출 {formatRelativeTime(classroom.last_submitted_at)}</>
                  ) : null}
                </div>
              </div>
              <RowBar
                testId={`classroom-row-${classroom.id}-rate`}
                ratio={rate}
                value={rate === null ? "—" : `${Math.round(rate * 100)}%`}
                caption="달성률"
                dim={archived}
              />
              {archived ? (
                // 보관의 약속은 "새 가입·새 제출은 닫히고 읽기는 남는다"다(#294,
                // CONTEXT.md 「Class」) — 첫 화면도 그 읽기를 가장 눈에 띄는
                // 자리에 둔다(#331). 복사해서 새로 여는 것도 흔한 쓰임이라
                // 여전히 할 수 있지만 부차 행동이다. 둘 다 같은 상세 화면으로
                // 간다 — 복사 자체는 그 화면이 한다.
                <div className="flex shrink-0 gap-1.5">
                  <Link
                    href={`/classes/${classroom.id}`}
                    data-testid={`classroom-row-${classroom.id}-view`}
                    className={buttonClass("secondary", "sm")}
                  >
                    지난 기록 보기
                  </Link>
                  <Link
                    href={`/classes/${classroom.id}`}
                    data-testid={`classroom-row-${classroom.id}-copy`}
                    className={buttonClass("secondary", "sm")}
                  >
                    복사해서 새 기수 열기
                  </Link>
                </div>
              ) : (
                <Link
                  href={`/classes/${classroom.id}`}
                  data-testid={`classroom-row-${classroom.id}-open`}
                  className={buttonClass("secondary", "sm")}
                >
                  열기
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

// 참여자로 들어간 클래스 한 줄(#328) — 누르면 강사 전용 상세(`/classes/{id}`)가
// 아니라 참여자 화면(`/classes/{id}/problems/mine`)으로 간다. 강사 전용
// 상세는 참여자에게 404이므로, 거기로 보내면 이 티켓이 고치는 막다른 길이
// 다시 생긴다.
function JoinedClassList({ classes }: { classes: JoinedClassRow[] }) {
  return (
    <Card>
      <ul data-testid="classroom-joined-list" className="divide-y divide-rule">
        {classes.map((classroom) => {
          const href = `/classes/${classroom.id}/problems/mine`;
          const open = classroom.open_problem_count;
          return (
            <li
              key={classroom.id}
              data-testid={`classroom-joined-row-${classroom.id}`}
              className="flex flex-wrap items-center gap-x-6 gap-y-3 px-[18px] py-3.5"
            >
              <div className="min-w-0 flex-1 basis-[220px]">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={href}
                    data-testid={`classroom-joined-row-${classroom.id}-link`}
                    className="text-[15px] font-medium text-ink hover:underline"
                  >
                    {classroom.name}
                  </Link>
                  {classroom.archived ? (
                    <span data-testid={`classroom-joined-row-${classroom.id}-archived-badge`}>
                      <Badge>보관됨 · 읽기 전용</Badge>
                    </span>
                  ) : null}
                  {/* 내보내져도 행을 지우지 않는다 — 지난 시도·판정은 그대로 읽힌다
                      (member_expelled와 같은 신호, #300). 여기서는 그 상태를
                      알리기만 하고 링크는 그대로 열어 둔다. */}
                  {classroom.expelled ? (
                    <span data-testid={`classroom-joined-row-${classroom.id}-expelled-badge`}>
                      <Badge tone="attention">내보내짐</Badge>
                    </span>
                  ) : null}
                </div>
                <div className="mt-[3px] text-[12px] text-ink/45">
                  {classroom.instructor_display_name ? <>강사 {classroom.instructor_display_name} · </> : null}
                  문제 <Num>{open}</Num>개
                </div>
              </div>
              <RowBar
                testId={`classroom-joined-row-${classroom.id}-progress`}
                ratio={open === 0 ? null : classroom.passed_count / open}
                value={`${classroom.passed_count}/${open}`}
                caption="통과"
                plain
              />
              <Link
                href={href}
                data-testid={`classroom-joined-row-${classroom.id}-solve`}
                className={buttonClass("secondary", "sm")}
              >
                문제 풀기
              </Link>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export default function ClassroomHome() {
  const taught = useMyClasses();
  const joined = useJoinedClasses();
  useClassroomTabTitle({ screenName: "내 클래스" });

  const loading = taught.status === "loading" || joined.status === "loading";
  // 아무 데도 안 속한 사람 — 강사로 연 것도, 참여자로 들어간 것도 없다.
  const nothingAtAll =
    taught.status === "ready" &&
    joined.status === "ready" &&
    taught.classes.length === 0 &&
    joined.classes.length === 0;
  // 강사로 연 클래스가 하나도 없으면 그 섹션 자체를 숨긴다 — 참여자로만 속한
  // 사람에게 「새 클래스 열기」 빈 상태 카드가 화면을 채우는 것을 막는다(#328).
  // 「새 클래스 열기」·「템플릿 둘러보기」 버튼 자체는 감추지 않는다 — 이
  // 서비스는 역할을 미리 정하지 않으므로(누구나 클래스를 열면 그 순간 강사다,
  // CONTEXT.md 「Class」) 그 행동 자체를 숨길 이유가 없다.
  const hasJoinedSection = joined.status === "ready" && joined.classes.length > 0;
  // 참여자로만 속한 사람 — 강사로 연 클래스가 확실히 0건이고(조회 실패는
  // 「모른다」이지 「없다」가 아니므로 제외한다) 참여 중인 클래스가 있다.
  // 이때는 강사용 두 행동을 머리가 아니라 목록 뒤에 보조(secondary) 모양으로
  // 둔다(#342 후속) — 목록이 화면의 주인공이다. 화면에 설명 문장은 두지 않는다
  // (시안 v2, #641) — 라벨·값·배지·버튼만.
  const participantOnly = taught.status === "ready" && taught.classes.length === 0 && hasJoinedSection;
  const ongoing = taught.status === "ready" ? taught.classes.filter((c) => !c.archived) : [];
  const archived = taught.status === "ready" ? taught.classes.filter((c) => c.archived) : [];
  const headerActions =
    loading || participantOnly ? undefined : <ClassActionLinks newClassTone="primary" />;

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스"
        title="내 클래스"
        titleTestId="classroom-home-heading"
        actions={headerActions}
      />

      {loading ? (
        <p data-testid="classroom-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      ) : nothingAtAll ? (
        <Card>
          <EmptyState>
            <span data-testid="classroom-empty-state">아직 가입하거나 연 클래스가 없습니다.</span>
          </EmptyState>
        </Card>
      ) : (
        <div className="flex flex-col gap-7">
          {/* 순서는 「내가 가르치는 클래스 → 참여 중인 클래스 → 보관」(시안 v2, #641).
              진행중과 보관을 갈라 보여준다(#294 AC) — 보관은 「고장」이 아니라 「끝났다」로
              읽혀야 하므로 따로 묶어 조용히 맨 아래에 둔다. */}
          {taught.status === "error" ? (
            <ErrorNote>
              <span data-testid="classroom-error">클래스 목록을 불러오지 못했습니다.</span>
            </ErrorNote>
          ) : ongoing.length > 0 ? (
            <section className="flex flex-col gap-2.5">
              <SectionHeading title="내가 가르치는 클래스" hint={ongoing.length} />
              <ClassList classes={ongoing} testId="classroom-ongoing-list" archived={false} />
            </section>
          ) : null}

          {joined.status === "error" ? (
            // 조회 실패와 0건은 반드시 다르게 보여야 한다 — 같아 보이면 조회가
            // 죽은 날 참여자는 자기 클래스가 사라졌다고 읽는다.
            <ErrorNote>
              <span data-testid="classroom-joined-error">
                참여 중인 클래스 목록을 불러오지 못했습니다.
              </span>
            </ErrorNote>
          ) : hasJoinedSection ? (
            <section className="flex flex-col gap-2.5">
              <SectionHeading title="참여 중인 클래스" hint={joined.classes.length} />
              <JoinedClassList classes={joined.classes} />
            </section>
          ) : null}

          {/* 참여자로만 속한 사람에게는 강사용 두 행동을 목록 뒤에 보조 모양으로 둔다. */}
          {participantOnly ? (
            <div className="flex flex-wrap justify-end gap-2 border-t border-rule pt-5">
              <ClassActionLinks newClassTone="secondary" size="sm" />
            </div>
          ) : null}

          {archived.length > 0 ? (
            <section className="flex flex-col gap-2.5">
              <SectionHeading title="보관" hint={archived.length} />
              <ClassList classes={archived} testId="classroom-archived-list" archived />
            </section>
          ) : null}
        </div>
      )}
    </PageShell>
  );
}
