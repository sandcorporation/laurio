"use client";

// 「내 클래스」 홈 (#278, 스타일 #298). 여기 닿는다는 것 자체가 미들웨어 가드를
// 통과했다는 뜻이라(middleware.ts) 여기서 다시 세션을 확인하지 않는다.
//
// 인증 구역이므로 SSR 하지 않는다(frontend/app/console/contests/page.tsx와
// 같은 이유, ADR-0015) — 클라이언트 컴포넌트로 목록을 받아온다.
import Link from "next/link";

import { Card, EmptyState, ErrorNote, Num, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import type { ClassRow } from "@/lib/classes/api";
import { useMyClasses } from "@/lib/classes/use-my-classes";

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
            {/* 보관된 클래스의 주 행동은 「복사해서 새 기수 열기」다 — 지난 기수를
                복사해 다음 기수를 여는 것이 이 제품의 흔한 쓰임이기 때문이다
                (docs/design/classroom/README.md). 복사 자체는 상세 화면이 한다. */}
            <Link
              href={`/classes/${classroom.id}`}
              className={buttonClass(archived ? "primary" : "secondary", "sm")}
            >
              {archived ? "복사해서 새 기수 열기" : "열기"}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function ClassroomHome() {
  const state = useMyClasses();

  return (
    <PageShell>
      <PageHeader
        eyebrow="강의실"
        title="내 클래스"
        titleTestId="classroom-home-heading"
        description={
          <span data-testid="classroom-home-heading-note">
            클래스마다 문제와 참여자가 따로 삽니다. 지난 기수를 복사하면 문제와 체크리스트가
            그대로 따라옵니다.
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

      {state.status === "loading" ? (
        <p data-testid="classroom-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      ) : state.status === "error" ? (
        // 조회 실패와 0건은 반드시 다르게 보여야 한다 — 같아 보이면 조회가 죽은
        // 날 강사는 자기 클래스가 사라졌다고 읽는다.
        <ErrorNote>
          <span data-testid="classroom-error">클래스 목록을 불러오지 못했습니다.</span>
        </ErrorNote>
      ) : state.classes.length === 0 ? (
        <Card>
          <EmptyState>
            <span data-testid="classroom-empty-state">아직 가입하거나 개설한 클래스가 없습니다.</span>
          </EmptyState>
        </Card>
      ) : (
        (() => {
          // 진행중과 보관을 갈라 보여준다(#294 AC) — 보관은 "고장"이 아니라
          // "끝났다"로 읽혀야 하므로 따로 묶어 조용히 아래에 둔다.
          const ongoing = state.classes.filter((c) => !c.archived);
          const archived = state.classes.filter((c) => c.archived);
          return (
            <div className="flex flex-col gap-7">
              <section className="flex flex-col gap-2.5">
                <h2 className="text-[15px] font-semibold">
                  진행중 <span className="font-normal text-ink/45">{ongoing.length}</span>
                </h2>
                {ongoing.length === 0 ? (
                  <Card>
                    <EmptyState>
                      <span data-testid="classroom-ongoing-empty-state">진행중인 클래스가 없습니다.</span>
                    </EmptyState>
                  </Card>
                ) : (
                  <ClassList classes={ongoing} testId="classroom-ongoing-list" archived={false} />
                )}
              </section>

              <section className="flex flex-col gap-2.5">
                <h2 className="text-[15px] font-semibold">
                  보관{" "}
                  <span className="font-normal text-ink/45">
                    새 가입과 새 제출은 닫혔고 읽기는 남습니다
                  </span>
                </h2>
                {archived.length === 0 ? (
                  <Card>
                    <EmptyState>
                      <span data-testid="classroom-archived-empty-state">보관된 클래스가 없습니다.</span>
                    </EmptyState>
                  </Card>
                ) : (
                  <ClassList classes={archived} testId="classroom-archived-list" archived />
                )}
              </section>
            </div>
          );
        })()
      )}
    </PageShell>
  );
}
