"use client";

// 클래스 상세 (#278/#279/#281/#282). 이름·만든 날짜에 이어 가입 링크·참여자
// 명단으로 가는 문, 그리고 문제 목록을 순서대로 보여준다. 남의 클래스는
// 백엔드가 404를 주므로 그대로 "찾을 수 없다"로 보여준다(존재를 알려주지
// 않는다). 「클래스를 템플릿으로 공개」는 여기 살지 않는다 — 학기에 한 번
// 할까 말까 한 일이라 매일 보는 이 화면 대신 「클래스 설정」으로 옮겼다(#323).
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Note,
  Num,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
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
    <Card>
      <CardHeader title="가입 링크" hint="이 링크로 들어오면 회원가입과 클래스 가입이 한 번에 끝납니다" />
      <div className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <p
            data-testid="join-link"
            className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap border border-rule bg-paper px-3 py-2 font-mono text-[13px]"
          >
            {url}
          </p>
          <button type="button" data-testid="join-link-copy" onClick={copy} className={buttonClass("secondary", "sm")}>
            복사
          </button>
          <button
            type="button"
            data-testid="join-link-regenerate"
            onClick={onRegenerate}
            className={buttonClass("danger", "sm")}
          >
            다시 뽑기
          </button>
          {copied ? (
            <span data-testid="join-link-copied" className="text-[12px] text-verified">
              복사됨
            </span>
          ) : null}
        </div>
        <p className="text-[11.5px] leading-relaxed text-ink/45">
          다시 뽑으면 이전 링크는 더 이상 이 클래스로 들어오지 못합니다.
        </p>
        {regenerateError ? (
          <ErrorNote>
            <span data-testid="join-link-regenerate-error">다시 뽑지 못했습니다. 다시 시도해주세요.</span>
          </ErrorNote>
        ) : null}
      </div>
    </Card>
  );
}

type DetailTab = "problems" | "grid";
function ArchiveSection({
  archived,
  archiveError,
  onToggle,
}: {
  archived: boolean;
  archiveError: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      {archived ? (
        <Note tone="attention">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span data-testid="classroom-archived-banner" className="flex-1">
              이 클래스는 보관되어 끝났습니다 — 새 가입과 새 제출은 받지 않지만, 지난 문제·제출물·판정은
              그대로 볼 수 있습니다.
            </span>
            <button
              type="button"
              data-testid="classroom-unarchive"
              onClick={onToggle}
              className={buttonClass("secondary", "sm")}
            >
              보관 되돌리기
            </button>
          </div>
        </Note>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 text-[12.5px] text-ink/45">
          <span>수업이 끝나면 보관합니다 — 새 가입과 새 제출만 닫히고, 언제든 되돌릴 수 있습니다.</span>
          <button
            type="button"
            data-testid="classroom-archive"
            onClick={onToggle}
            className={buttonClass("secondary", "sm")}
          >
            보관하기
          </button>
        </div>
      )}
      {archiveError ? (
        <ErrorNote>
          <span data-testid="classroom-archive-error">
            {archived ? "되돌리지" : "보관하지"} 못했습니다. 다시 시도해주세요.
          </span>
        </ErrorNote>
      ) : null}
    </div>
  );
}

export default function ClassDetailPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state: classState, regenerateJoinCode, setArchived } = useClass(classId);
  const { state: problemsState, move } = useProblems(classId);
  const [tab, setTab] = useState<DetailTab>("problems");
  const router = useRouter();
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
      <PageShell>
        <p data-testid="classroom-detail-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (classState.status === "notFound") {
    return (
      <PageShell>
        <h1 data-testid="classroom-detail-not-found" className="text-[22px] font-semibold">
          클래스를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (classState.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="classroom-detail-error">클래스 정보를 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const classroom = classState.classroom;

  return (
    <PageShell>
      <PageHeader
        eyebrow="내 클래스"
        title={classroom.name}
        titleTestId="classroom-detail-heading"
        description={
          <span data-testid="classroom-detail-created-at">
            <Num>{new Date(classroom.created_at).toLocaleDateString("ko-KR")}</Num> 만듦
          </span>
        }
        actions={
          <>
            <span data-testid="classroom-detail-status">
              <Badge tone={classroom.archived ? "neutral" : "verified"}>
                {classroom.archived ? "보관됨" : "진행중"}
              </Badge>
            </span>
            <Link href={`/classes/${classId}/members`} data-testid="members-link" className={buttonClass()}>
              참여자 명단
            </Link>
            <Link href={`/classes/${classId}/settings`} data-testid="class-settings-link" className={buttonClass()}>
              클래스 설정
            </Link>
            {/* 보관된 클래스에서는 이것이 주 행동이다 — 지난 클래스를 복사해 다음
                클래스를 여는 것이 이 제품의 흔한 쓰임이다
                (docs/design/classroom/README.md). */}
            <button
              type="button"
              data-testid="copy-class-button"
              onClick={handleCopyClass}
              disabled={copying}
              className={buttonClass(classroom.archived ? "primary" : "secondary")}
            >
              {copying ? "복사하는 중..." : "복사해서 새로 열기"}
            </button>
          </>
        }
      />

      <div className="flex flex-col gap-5">
        {copyError ? (
          <ErrorNote>
            <span data-testid="copy-class-error">{copyError}</span>
          </ErrorNote>
        ) : null}

        <ArchiveSection
          archived={classroom.archived}
          archiveError={classState.archiveError}
          onToggle={() => setArchived(!classroom.archived)}
        />

        <JoinLinkSection
          joinCode={classroom.join_code}
          regenerateError={classState.regenerateError}
          onRegenerate={regenerateJoinCode}
        />

        {/* 클래스 상세의 두 탭(#290) — 「문제 중심」은 문제마다 달성률을 보여주고
            (#289), 「참여자별 현황」은 참여자 × 문제 격자로 누가 막혔는지 보여준다.
            같은 사실을 두 번 셈하지 않도록 달성률 값은 둘 다 백엔드의 같은
            계산에서 나온다(#290 AC). */}
        <div>
          <div role="tablist" aria-label="클래스 상세 탭" className="flex items-end gap-0.5 border-b border-rule">
            {(
              [
                ["problems", "문제 중심", "detail-tab-problems"],
                ["grid", "참여자별 현황", "detail-tab-grid"],
              ] as const
            ).map(([key, label, testId]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                data-testid={testId}
                onClick={() => setTab(key)}
                className={
                  tab === key
                    ? "-mb-px border border-rule border-b-surface bg-surface px-4 py-2 text-[13.5px] font-medium"
                    : "px-4 py-2 text-[13.5px] text-ink/60 hover:text-ink"
                }
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "problems" ? (
            <Card className="border-t-0">
              <div className="flex items-center justify-between gap-3 border-b border-rule px-4 py-3">
                <h2 className="text-[15px] font-semibold">문제</h2>
                <Link
                  href={`/classes/${classId}/problems/new`}
                  data-testid="new-problem-link"
                  className={buttonClass("primary", "sm")}
                >
                  새 문제
                </Link>
              </div>

              {problemsState.status === "loading" ? (
                <p data-testid="problems-loading" className="px-4 py-6 text-[13px] text-ink/45">
                  불러오는 중...
                </p>
              ) : problemsState.status === "error" ? (
                <div className="p-4">
                  <ErrorNote>
                    <span data-testid="problems-error">문제 목록을 불러오지 못했습니다.</span>
                  </ErrorNote>
                </div>
              ) : problemsState.problems.length === 0 ? (
                <EmptyState>
                  <span data-testid="problems-empty-state">
                    아직 만든 문제가 없습니다. 위 「새 문제」로 첫 문제를 내보세요.
                  </span>
                </EmptyState>
              ) : (
                <>
                  {problemsState.reorderError ? (
                    <div className="p-4 pb-0">
                      <ErrorNote>
                        <span data-testid="problems-reorder-error">
                          순서를 바꾸지 못했습니다. 다시 시도해주세요.
                        </span>
                      </ErrorNote>
                    </div>
                  ) : null}
                  <ol data-testid="problems-list" className="divide-y divide-rule">
                    {problemsState.problems.map((problem, index) => (
                      <li
                        key={problem.id}
                        data-testid={`problem-row-${problem.id}`}
                        className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3.5"
                      >
                        <span className="w-5 shrink-0 font-mono text-[12px] text-ink/30">{index + 1}</span>
                        <Link
                          href={`/classes/${classId}/problems/${problem.id}`}
                          data-testid={`problem-row-${problem.id}-link`}
                          className="min-w-0 flex-1 text-[14px] hover:underline"
                        >
                          {problem.title}
                        </Link>
                        <span data-testid={`problem-row-${problem.id}-status`} className="shrink-0">
                          <Badge tone={problem.status === "open" ? "verified" : "neutral"}>
                            {STATUS_LABEL[problem.status]}
                          </Badge>
                        </span>
                        <span
                          data-testid={`problem-row-${problem.id}-achievement-rate`}
                          className="w-[110px] shrink-0 text-right font-mono text-[13px] text-ink/60"
                        >
                          달성률 {formatAchievementRate(problem)}
                        </span>
                        <span className="flex shrink-0 gap-1">
                          <button
                            type="button"
                            data-testid={`problem-row-${problem.id}-move-up`}
                            disabled={index === 0}
                            onClick={() => move(problem.id, "up")}
                            className={buttonClass("secondary", "sm")}
                          >
                            위로
                          </button>
                          <button
                            type="button"
                            data-testid={`problem-row-${problem.id}-move-down`}
                            disabled={index === problemsState.problems.length - 1}
                            onClick={() => move(problem.id, "down")}
                            className={buttonClass("secondary", "sm")}
                          >
                            아래로
                          </button>
                        </span>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </Card>
          ) : (
            <RosterGridTab classId={classId} />
          )}
        </div>
      </div>
    </PageShell>
  );
}
