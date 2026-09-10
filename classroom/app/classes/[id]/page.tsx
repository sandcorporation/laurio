"use client";

// 클래스 상세 (#278/#279/#281/#282). 이름·만든 날짜에 이어 가입 링크·참여자
// 명단으로 가는 문, 그리고 문제 목록을 순서대로 보여준다. 남의 클래스는
// 백엔드가 404를 주므로 그대로 "찾을 수 없다"로 보여준다(존재를 알려주지
// 않는다).
import Link from "next/link";
import { useParams } from "next/navigation";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { copyClass } from "@/lib/classes/api";
import { useClass } from "@/lib/classes/use-class";
import { formatAchievementRate } from "@/lib/problems/achievement";
import { useProblems } from "@/lib/problems/use-problems";

import { RosterGridTab } from "./roster-grid-tab";

const STATUS_LABEL: Record<string, string> = {
  draft: "초안",
  open: "열림",
};

function joinLinkUrl(joinCode: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/join/${joinCode}`;
}

function JoinLinkSection({
  joinCode,
  regenerateError,
  onRegenerate,
}: {
  joinCode: string;
  regenerateError: boolean;
  onRegenerate: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const url = joinLinkUrl(joinCode);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section>
      <h2>가입 링크</h2>
      <p data-testid="join-link">{url}</p>
      <button type="button" data-testid="join-link-copy" onClick={copy}>
        복사
      </button>
      {copied ? <span data-testid="join-link-copied"> 복사됨</span> : null}
      <p>
        <button type="button" data-testid="join-link-regenerate" onClick={onRegenerate}>
          다시 뽑기
        </button>
      </p>
      <p>다시 뽑으면 이전 링크는 더 이상 이 클래스로 들어오지 못합니다.</p>
      {regenerateError ? (
        <p data-testid="join-link-regenerate-error">다시 뽑지 못했습니다. 다시 시도해주세요.</p>
      ) : null}
    </section>
  );
}

type DetailTab = "problems" | "grid";

export default function ClassDetailPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state: classState, regenerateJoinCode } = useClass(classId);
  const { state: problemsState, move } = useProblems(classId);
  const [tab, setTab] = useState<DetailTab>("problems");
  const router = useRouter();
  const { state: classState } = useClass(classId);
  const { state: problemsState, move } = useProblems(classId);
  const [copying, setCopying] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  async function handleCopyClass() {
    setCopyError(null);
    setCopying(true);
    try {
      const copy = await copyClass(classId);
      router.push(`/classes/${copy.id}`);
    } catch {
      setCopyError("클래스를 복사하지 못했습니다. 잠시 후 다시 시도해주세요.");
      setCopying(false);
    }
  }

  if (classState.status === "loading") {
    return (
      <main>
        <p data-testid="classroom-detail-loading">불러오는 중...</p>
      </main>
    );
  }

  if (classState.status === "notFound") {
    return (
      <main>
        <h1 data-testid="classroom-detail-not-found">클래스를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (classState.status === "error") {
    return (
      <main>
        <p data-testid="classroom-detail-error">클래스 정보를 불러오지 못했습니다.</p>
      </main>
    );
  }

  return (
    <main>
      <h1 data-testid="classroom-detail-heading">{classState.classroom.name}</h1>
      <p data-testid="classroom-detail-created-at">
        {new Date(classState.classroom.created_at).toLocaleDateString("ko-KR")} 만듦
      </p>
      <p>
        <Link href={`/classes/${classId}/settings`} data-testid="scoring-settings-link">
          채점 설정
        </Link>
      </p>
      <p>
        <button type="button" data-testid="copy-class-button" onClick={handleCopyClass} disabled={copying}>
          {copying ? "복사하는 중..." : "복사해서 새 기수 열기"}
        </button>
      </p>
      {copyError ? <p data-testid="copy-class-error">{copyError}</p> : null}

      <JoinLinkSection
        joinCode={classState.classroom.join_code}
        regenerateError={classState.regenerateError}
        onRegenerate={regenerateJoinCode}
      />

      <p>
        <Link href={`/classes/${classId}/members`} data-testid="members-link">
          참여자 명단
        </Link>
      </p>

      {/* 클래스 상세의 두 탭(#290) — 「문제 중심」은 문제마다 달성률을 보여주고
          (#289), 「참여자별 현황」은 참여자 × 문제 격자로 누가 막혔는지 보여준다.
          같은 사실을 두 번 셈하지 않도록 달성률 값은 둘 다 백엔드의 같은
          계산에서 나온다(#290 AC). */}
      <div role="tablist" aria-label="클래스 상세 탭">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "problems"}
          data-testid="detail-tab-problems"
          onClick={() => setTab("problems")}
        >
          문제 중심
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "grid"}
          data-testid="detail-tab-grid"
          onClick={() => setTab("grid")}
        >
          참여자별 현황
        </button>
      </div>

      {tab === "problems" ? (
        <>
          <h2>문제</h2>
          <p>
            <Link href={`/classes/${classId}/problems/new`} data-testid="new-problem-link">
              새 문제
            </Link>
          </p>

          {problemsState.status === "loading" ? (
            <p data-testid="problems-loading">불러오는 중...</p>
          ) : problemsState.status === "error" ? (
            <p data-testid="problems-error">문제 목록을 불러오지 못했습니다.</p>
          ) : problemsState.problems.length === 0 ? (
            <p data-testid="problems-empty-state">아직 만든 문제가 없습니다.</p>
          ) : (
            <>
              {problemsState.reorderError ? (
                <p data-testid="problems-reorder-error">순서를 바꾸지 못했습니다. 다시 시도해주세요.</p>
              ) : null}
              <ol data-testid="problems-list">
                {problemsState.problems.map((problem, index) => (
                  <li key={problem.id} data-testid={`problem-row-${problem.id}`}>
                    <Link
                      href={`/classes/${classId}/problems/${problem.id}`}
                      data-testid={`problem-row-${problem.id}-link`}
                    >
                      {problem.title}
                    </Link>
                    <span data-testid={`problem-row-${problem.id}-status`}> · {STATUS_LABEL[problem.status]}</span>
                    <span data-testid={`problem-row-${problem.id}-achievement-rate`}>
                      {" "}
                      · 달성률 {formatAchievementRate(problem)}
                    </span>
                    <button
                      type="button"
                      data-testid={`problem-row-${problem.id}-move-up`}
                      disabled={index === 0}
                      onClick={() => move(problem.id, "up")}
                    >
                      위로
                    </button>
                    <button
                      type="button"
                      data-testid={`problem-row-${problem.id}-move-down`}
                      disabled={index === problemsState.problems.length - 1}
                      onClick={() => move(problem.id, "down")}
                    >
                      아래로
                    </button>
                  </li>
                ))}
              </ol>
            </>
          )}
        </>
      ) : (
        <RosterGridTab classId={classId} />
      )}
    </main>
  );
}
