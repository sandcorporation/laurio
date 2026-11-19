"use client";

// 개최자의 제출 명단 (#956, ADR-0079).
//
// 마감 전에도 열린다. 칸은 표시 이름과 낸 시각뿐이다 — 백엔드 응답
// (`ContestRosterOut`)에 제출 id·자료·점수가 없으므로 이 화면에서 상세로 가는
// 길도 없다. 탈퇴로 이름이 지워진 참가자(ADR-0025)는 이름 없이 한 줄로 선다.
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015) — 다른 `/console/**` 화면과 같은 경계다.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { EmptyState, ErrorNote, PageHeader } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import { formatDeadlineSeoul } from "@/lib/contest-format";
import type { ContestRosterOut } from "@/lib/submissions/types";

type ContestMeta = { id: number; title: string };

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "forbidden"; message: string }
  | { status: "error"; message: string }
  | { status: "ready"; contest: ContestMeta; roster: ContestRosterOut };

export default function ContestRosterPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    void Promise.all([
      bffClient.get<ContestMeta>(`/api/backend/contests/${contestId}`),
      bffClient.get<ContestRosterOut>(`/api/backend/contests/${contestId}/submissions/roster`),
    ]).then(([contest, roster]) => {
      if (cancelled) return;
      if (contest.ok && roster.ok) {
        setLoad({ status: "ready", contest: contest.data, roster: roster.data });
        return;
      }
      if (contest.status === 404 || roster.status === 404) {
        setLoad({ status: "not-found" });
        return;
      }
      if (!roster.ok && roster.status === 403) {
        setLoad({ status: "forbidden", message: roster.detail });
        return;
      }
      setLoad({ status: "error", message: "제출 명단을 불러오지 못했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, contestId]);

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <p data-testid="roster-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "not-found") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <p data-testid="roster-not-found">공모전을 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (load.status === "forbidden" || load.status === "error") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <ErrorNote>
          <span data-testid={`roster-${load.status}`}>{load.message}</span>
        </ErrorNote>
      </main>
    );
  }

  const { contest, roster } = load;

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-10 sm:px-10">
      <PageHeader
        title={`${contest.title} — 제출 명단`}
        titleTestId="roster-contest-title"
        description={
          <>
            제출{" "}
            <span data-testid="roster-count">{roster.entries.length}</span>건
          </>
        }
      />

      {roster.entries.length === 0 ? (
        <EmptyState>
          <span data-testid="roster-empty">아직 제출이 없습니다.</span>
        </EmptyState>
      ) : (
        <table className="w-full border-collapse text-sm" data-testid="roster-table">
          <thead>
            <tr>
              <th className="border border-rule bg-surface p-2 text-left">표시 이름</th>
              <th className="border border-rule bg-surface p-2 text-left">제출 시각</th>
            </tr>
          </thead>
          <tbody>
            {roster.entries.map((entry, index) => (
              <tr key={index} data-testid="roster-row">
                <td className="border border-rule p-2 break-all">
                  {entry.display_name ?? <span className="text-ink/45">이름 없음</span>}
                </td>
                <td className="border border-rule p-2 font-mono">
                  {formatDeadlineSeoul(entry.submitted_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
