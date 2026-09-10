"use client";

// 「내 클래스」 홈 (#278). Class 모델이 생겨 실제 목록을 그린다 — #276이 남긴
// 뼈대(항상 빈 상태)를 대체한다. 여기 닿는다는 것 자체가 미들웨어 가드를
// 통과했다는 뜻이라(middleware.ts) 여기서 다시 세션을 확인하지 않는다.
//
// 인증 구역이므로 SSR 하지 않는다(frontend/app/console/contests/page.tsx와
// 같은 이유, ADR-0015) — 클라이언트 컴포넌트로 목록을 받아온다.
import Link from "next/link";

import { useMyClasses } from "@/lib/classes/use-my-classes";
import type { ClassRow } from "@/lib/classes/api";

function ClassList({ classes, testId }: { classes: ClassRow[]; testId: string }) {
  return (
    <ul data-testid={testId}>
      {classes.map((classroom) => (
        <li key={classroom.id} data-testid={`classroom-row-${classroom.id}`}>
          <Link href={`/classes/${classroom.id}`} data-testid={`classroom-row-${classroom.id}-link`}>
            {classroom.name}
          </Link>
          <span>
            {" "}
            · {new Date(classroom.created_at).toLocaleDateString("ko-KR")} 만듦
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function ClassroomHome() {
  const state = useMyClasses();

  return (
    <main>
      <h1 data-testid="classroom-home-heading">내 클래스</h1>

      <p>
        <Link href="/classes/new" data-testid="classroom-new-class-link">
          새 클래스
        </Link>
      </p>

      {state.status === "loading" ? (
        <p data-testid="classroom-loading">불러오는 중...</p>
      ) : state.status === "error" ? (
        // 조회 실패와 0건은 반드시 다르게 보여야 한다 — 같아 보이면 조회가 죽은
        // 날 강사는 자기 클래스가 사라졌다고 읽는다.
        <p data-testid="classroom-error">클래스 목록을 불러오지 못했습니다.</p>
      ) : state.classes.length === 0 ? (
        <p data-testid="classroom-empty-state">아직 가입하거나 개설한 클래스가 없습니다.</p>
      ) : (
        (() => {
          // 진행중과 보관을 갈라 보여준다(#294 AC) — 보관은 "고장"이 아니라
          // "끝났다"로 읽혀야 하므로 따로 묶어 조용히 아래에 둔다.
          const ongoing = state.classes.filter((c) => !c.archived);
          const archived = state.classes.filter((c) => c.archived);
          return (
            <>
              <h2>진행중</h2>
              {ongoing.length === 0 ? (
                <p data-testid="classroom-ongoing-empty-state">진행중인 클래스가 없습니다.</p>
              ) : (
                <ClassList classes={ongoing} testId="classroom-ongoing-list" />
              )}

              <h2>보관</h2>
              {archived.length === 0 ? (
                <p data-testid="classroom-archived-empty-state">보관된 클래스가 없습니다.</p>
              ) : (
                <ClassList classes={archived} testId="classroom-archived-list" />
              )}
            </>
          );
        })()
      )}
    </main>
  );
}
