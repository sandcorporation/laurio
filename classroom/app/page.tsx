"use client";

// 「내 클래스」 홈 (#278, 스타일 #298, 참여자 동선 #328). 여기 닿는다는 것
// 자체가 미들웨어 가드를 통과했다는 뜻이라(middleware.ts) 여기서 다시 세션을
// 확인하지 않는다.
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
} from "@/app/components/ui";
import type { ClassRow, JoinedClassRow } from "@/lib/classes/api";
import { useMyClasses } from "@/lib/classes/use-my-classes";
import { useJoinedClasses } from "@/lib/classes/use-joined-classes";

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
        {classes.map((classroom) => (
          <li
            key={classroom.id}
            data-testid={`classroom-row-${classroom.id}`}
            className="flex flex-wrap items-center justify-between gap-3 px-4 py-4"
          >
            <div className="min-w-0">
              <Link
                href={`/classes/${classroom.id}`}
                data-testid={`classroom-row-${classroom.id}-link`}
                className={`text-[15px] font-medium hover:underline ${archived ? "text-ink/45" : "text-ink"}`}
              >
                {classroom.name}
              </Link>
              <div className="mt-1 text-[12px] text-ink/45">
                <Num>{new Date(classroom.created_at).toLocaleDateString("ko-KR")}</Num> 만듦
              </div>
            </div>
            {archived ? (
              // 보관의 약속은 "새 가입·새 제출은 닫히고 읽기는 남는다"다(#294,
              // CONTEXT.md 「Class」) — 첫 화면도 그 읽기를 가장 눈에 띄는
              // 자리에 둔다(#331). 복사해서 새로 여는 것도 흔한 쓰임이라
              // 여전히 할 수 있지만, 제목 링크만 아는 사람만 쓰는 부차 행동으로
              // 내린다. 둘 다 같은 상세 화면으로 간다 — 복사 자체는 그 화면이
              // 한다.
              <div className="flex shrink-0 gap-2">
                <Link
                  href={`/classes/${classroom.id}`}
                  data-testid={`classroom-row-${classroom.id}-view`}
                  className={buttonClass("primary", "sm")}
                >
                  지난 기록 보기
                </Link>
                <Link
                  href={`/classes/${classroom.id}`}
                  data-testid={`classroom-row-${classroom.id}-copy`}
                  className={buttonClass("secondary", "sm")}
                >
                  복사해서 새로 열기
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
        ))}
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
          return (
            <li
              key={classroom.id}
              data-testid={`classroom-joined-row-${classroom.id}`}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-4"
            >
              <div className="min-w-0">
                <Link
                  href={href}
                  data-testid={`classroom-joined-row-${classroom.id}-link`}
                  className="text-[15px] font-medium text-ink hover:underline"
                >
                  {classroom.name}
                </Link>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-ink/45">
                  {classroom.instructor_display_name ? (
                    <span>{classroom.instructor_display_name} 강사</span>
                  ) : null}
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
              </div>
              <Link href={href} className={buttonClass("secondary", "sm")}>
                열기
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

  const loading = taught.status === "loading" || joined.status === "loading";
  // 아무 데도 안 속한 사람 — 강사로 연 것도, 참여자로 들어간 것도 없다.
  const nothingAtAll =
    taught.status === "ready" &&
    joined.status === "ready" &&
    taught.classes.length === 0 &&
    joined.classes.length === 0;
  // 강사로 연 클래스가 하나도 없으면 그 섹션 자체를 숨긴다 — 참여자로만 속한
  // 사람에게 「새 클래스 열기」 빈 상태 카드 둘(진행중·보관)이 화면을 채우는
  // 것을 막는다(#328 AC "강사가 아닌 사람에게 강사 기능이 첫 화면을 채우지
  // 않는다"). 「새 클래스 열기」·「템플릿 둘러보기」 버튼 자체는 감추지
  // 않는다 — 이 서비스는 역할을 미리 정하지 않으므로(누구나 클래스를 열면
  // 그 순간 강사다, CONTEXT.md 「Class」) 그 행동 자체를 숨길 이유가 없다.
  const hasJoinedSection = joined.status === "ready" && joined.classes.length > 0;

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스"
        title="내 클래스"
        titleTestId="classroom-home-heading"
        description={
          <span data-testid="classroom-home-heading-note">
            문제를 내고 참여자의 제출을 채점하는 공간입니다. 지난 클래스를 복사하면 문제와
            체크리스트를 그대로 가져와 새로 시작할 수 있습니다.
          </span>
        }
        actions={
          <>
            <Link
              href="/templates"
              data-testid="classroom-browse-templates-link"
              className={buttonClass("secondary")}
            >
              템플릿 둘러보기
            </Link>
            <Link href="/classes/new" data-testid="classroom-new-class-link" className={buttonClass("primary")}>
              새 클래스 열기
            </Link>
          </>
        }
      />

      {loading ? (
        <p data-testid="classroom-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      ) : nothingAtAll ? (
        <Card>
          <EmptyState>
            <span data-testid="classroom-empty-state">
              아직 가입하거나 연 클래스가 없습니다. 위 「새 클래스 열기」로 시작하거나, 초대
              링크를 받았다면 그 링크로 들어가 보세요.
            </span>
          </EmptyState>
        </Card>
      ) : (
        <div className="flex flex-col gap-7">
          {joined.status === "error" ? (
            // 조회 실패와 0건은 반드시 다르게 보여야 한다 — 같아 보이면 조회가
            // 죽은 날 참여자는 자기 클래스가 사라졌다고 읽는다.
            <ErrorNote>
              <span data-testid="classroom-joined-error">
                참여 중인 클래스 목록을 불러오지 못했습니다.
              </span>
            </ErrorNote>
          ) : joined.status === "ready" && joined.classes.length > 0 ? (
            <section className="flex flex-col gap-2.5">
              <SectionHeading title="참여 중인 클래스" hint={joined.classes.length} />
              <JoinedClassList classes={joined.classes} />
            </section>
          ) : null}

          {taught.status === "error" ? (
            <ErrorNote>
              <span data-testid="classroom-error">클래스 목록을 불러오지 못했습니다.</span>
            </ErrorNote>
          ) : taught.status === "ready" && taught.classes.length > 0 ? (
            (() => {
              // 진행중과 보관을 갈라 보여준다(#294 AC) — 보관은 "고장"이 아니라
              // "끝났다"로 읽혀야 하므로 따로 묶어 조용히 아래에 둔다.
              const ongoing = taught.classes.filter((c) => !c.archived);
              const archived = taught.classes.filter((c) => c.archived);
              return (
                <div className="flex flex-col gap-7">
                  {/* 참여 중인 클래스 섹션과 나란히 있을 때만 "내가 연 클래스"를
                      밝힌다 — 참여자 없이 강사 클래스만 있으면 이 화면 전체가
                      이미 그 뜻이라 덧붙일 이유가 없다(#328). 머리글 위계를
                      늘리지 않도록 `<h2>`가 아니라 PageHeader의 눈썹과 같은
                      장식용 라벨로 둔다. */}
                  {hasJoinedSection ? (
                    <div
                      data-testid="classroom-taught-group-label"
                      className="text-[11px] tracking-[0.08em] text-ink/45"
                    >
                      내가 연 클래스
                    </div>
                  ) : null}

                  <section className="flex flex-col gap-2.5">
                    <SectionHeading title="진행중" hint={ongoing.length} />
                    {ongoing.length === 0 ? (
                      <Card>
                        <EmptyState>
                          <span data-testid="classroom-ongoing-empty-state">
                            진행중인 클래스가 없습니다. 위 「새 클래스 열기」로 새로 시작해 보세요.
                          </span>
                        </EmptyState>
                      </Card>
                    ) : (
                      <ClassList classes={ongoing} testId="classroom-ongoing-list" archived={false} />
                    )}
                  </section>

                  <section className="flex flex-col gap-2.5">
                    <SectionHeading
                      title="보관"
                      hint="새로 가입하거나 제출할 수는 없지만, 지난 기록은 그대로 볼 수 있습니다"
                    />
                    {archived.length === 0 ? (
                      <Card>
                        <EmptyState>
                          <span data-testid="classroom-archived-empty-state">
                            보관된 클래스가 없습니다. 클래스를 다 쓰면 상세 화면에서 보관해 목록을
                            정리할 수 있습니다.
                          </span>
                        </EmptyState>
                      </Card>
                    ) : (
                      <ClassList classes={archived} testId="classroom-archived-list" archived />
                    )}
                  </section>
                </div>
              );
            })()
          ) : null}
        </div>
      )}
    </PageShell>
  );
}
