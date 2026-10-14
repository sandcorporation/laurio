"use client";

// 클래스 상세 (#278/#279/#281/#282, 시안 v2 #633). 머리(이름·상태·통계 바) · 가입 링크 띠 · 탭 셋
// (문제 · 참여자 · 강사) · 문제 탭의 표와 오른쪽 「채점」·「최근 제출」 카드. 남의 클래스는 백엔드가
// 404를 주므로 그대로 "찾을 수 없다"로 보여준다(존재를 알려주지 않는다). 「클래스를 템플릿으로
// 공개」는 여기 살지 않는다 — 학기에 한 번 할까 말까 한 일이라 「클래스 설정」으로 옮겼다(#323).
//
// 화면에 설명 문장을 두지 않는다 — 라벨·값·배지·버튼만. 채점 연결의 문제(키 없음·거부됨·크레딧
// 소진·서버 연결 불가)는 배너가 아니라 「채점」 카드의 상태 한 줄이 말한다.
// 참여자·강사 탭의 내용은 각자 티켓(#634·#635)이 다시 짠다 — 그때까지는 예전 화면을 그 자리에 둔다.
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ErrorNote, PageShell, buttonClass } from "@/app/components/ui";
import { TemplatePickerSheet } from "@/app/components/TemplatePickerSheet";
import { copyClass } from "@/lib/classes/api";
import { parseDetailTab } from "@/lib/classes/detail-tab";
import { scoringStatus } from "@/lib/classes/scoring-status";
import { useClass } from "@/lib/classes/use-class";
import type { PickerTab } from "@/lib/problem-templates/picker-selection";
import { useProblems } from "@/lib/problems/use-problems";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

import { ClassDetailTabs } from "./class-detail-tabs";
import { ClassHead } from "./class-head";
import { GettingStartedCard, startSteps } from "./getting-started-card";
import { InstructorsSection } from "./instructors-section";
import { JoinLinkStrip } from "./join-link-strip";
import { OwnershipTransferAcceptedNote, OwnershipTransferOffer } from "./ownership-transfer-offer";
import { ProblemsTable } from "./problems-table";
import { RecentAttemptsCard } from "./recent-attempts-card";
import { RosterGridTab } from "./roster-grid-tab";
import { ScoringCard } from "./scoring-card";

function joinLinkUrl(joinCode: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/join/${joinCode}`;
}

function ClassDetail() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const tab = parseDetailTab(useSearchParams().get("tab"));
  const { state: classState, reload: reloadClass, regenerateJoinCode, setArchived } = useClass(classId);
  // 방금 소유권을 넘겨받았는가(#564) — 키 넣기로 가는 안내를 한 번 보인다.
  const [justTookOver, setJustTookOver] = useState(false);
  const { state: problemsState, move } = useProblems(classId);
  const router = useRouter();
  const [copying, setCopying] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  // 빈 목록의 입구가 시트를 곧장 그 탭으로 연다.
  const [pickerTab, setPickerTab] = useState<PickerTab | null>(null);

  useClassroomTabTitle({
    screenName: "클래스 상세",
    className: classState.status === "ready" ? classState.classroom.name : undefined,
  });

  async function handleCopyClass() {
    setCopyError(null);
    setCopying(true);
    const result = await copyClass(classId);
    if (result.ok) {
      router.push(`/classes/${result.data.id}`);
    } else {
      setCopyError(result.detail);
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
  const status = scoringStatus(classroom);
  const steps = startSteps(classroom);
  // 「시작하기」는 새 클래스의 순서다 — 문제나 참여자가 아직 없을 때. 둘 다 생기면 채점 연결이 없어도
  // 「채점」 카드가 연결 없음을 말한다. 거부됨·크레딧 소진·서버 연결 불가는 이미 연결된 뒤의 문제라
  // 언제나 「채점」 카드다.
  const showStart =
    !classroom.archived &&
    (status.kind === "connected" || status.kind === "missing") &&
    !(steps.hasProblem && steps.hasMember);

  return (
    <PageShell>
      <ClassHead
        classroom={classroom}
        copying={copying}
        onCopy={handleCopyClass}
        onArchive={() => setArchived(true)}
      />

      <div className="flex flex-col gap-5">
        {copyError ? (
          <ErrorNote>
            <span data-testid="copy-class-error">{copyError}</span>
          </ErrorNote>
        ) : null}
        {!classroom.archived && classState.archiveError ? (
          <ErrorNote>
            <span data-testid="classroom-archive-error">보관하지 못했습니다. 다시 시도해주세요.</span>
          </ErrorNote>
        ) : null}

        {/* 나에게 온 소유권 이전 요청(#564) — 답을 기다리는 일이라 맨 위에 둔다. */}
        {classroom.pending_ownership_transfer?.recipient_is_me ? (
          <OwnershipTransferOffer
            classId={classId}
            transfer={classroom.pending_ownership_transfer}
            ownerName={classroom.instructor_display_name}
            onDone={(accepted) => {
              setJustTookOver(accepted);
              reloadClass();
            }}
          />
        ) : null}
        {justTookOver && classroom.role === "owner" ? <OwnershipTransferAcceptedNote classId={classId} /> : null}

        <JoinLinkStrip
          joinCode={classroom.join_code}
          archived={classroom.archived}
          regenerateError={classState.regenerateError}
          archiveError={classState.archiveError}
          onRegenerate={regenerateJoinCode}
          onUnarchive={() => setArchived(false)}
        />

        <div>
          <ClassDetailTabs classId={classId} active={tab} />

          {tab === "problems" ? (
            <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
              <div className="min-w-0 flex-1">
                <ProblemsTable
                  classId={classId}
                  archived={classroom.archived}
                  loading={problemsState.status === "loading"}
                  error={problemsState.status === "error"}
                  problems={problemsState.status === "ready" ? problemsState.problems : []}
                  reorderError={problemsState.status === "ready" && problemsState.reorderError}
                  onMove={move}
                  onOpenPicker={setPickerTab}
                />
              </div>
              <div className="flex w-full shrink-0 flex-col gap-4 lg:w-[320px] lg:pt-5">
                {showStart ? (
                  <GettingStartedCard classroom={classroom} joinUrl={joinLinkUrl(classroom.join_code)} />
                ) : (
                  <>
                    <ScoringCard classroom={classroom} />
                    <RecentAttemptsCard classId={classId} />
                  </>
                )}
              </div>
            </div>
          ) : tab === "participants" ? (
            <div className="flex flex-col gap-3 border border-t-0 border-rule bg-surface p-4">
              {/* 명단(가입일·내보내기)은 아직 따로 있는 화면이다 — 참여자 탭(#634)이 격자와 하나로 합친다. */}
              <div>
                <Link href={`/classes/${classId}/members`} data-testid="members-link" className={buttonClass("secondary", "sm")}>
                  참여자 명단
                </Link>
              </div>
              <RosterGridTab classId={classId} />
            </div>
          ) : (
            <div className="flex flex-col gap-4 border border-t-0 border-rule bg-surface p-4">
              {/* 역할과 대기 요청이 바뀌면(넘겨받기·요청·취소) 강사 목록을 처음부터 다시 읽는다. */}
              <InstructorsSection
                key={`${classroom.role}-${classroom.pending_ownership_transfer?.id ?? "none"}`}
                classId={classId}
                pendingTransfer={classroom.pending_ownership_transfer}
                onTransferChanged={reloadClass}
              />
            </div>
          )}
        </div>
      </div>

      {pickerTab !== null ? (
        <TemplatePickerSheet
          classId={classId}
          initialTab={pickerTab}
          onClose={() => setPickerTab(null)}
          onImported={(problem) => router.push(`/classes/${classId}/problems/${problem.id}`)}
        />
      ) : null}
    </PageShell>
  );
}

export default function ClassDetailPage() {
  // `useSearchParams` 는 정적 빌드에서 Suspense 경계 안에 있어야 한다.
  return (
    <Suspense>
      <ClassDetail />
    </Suspense>
  );
}
