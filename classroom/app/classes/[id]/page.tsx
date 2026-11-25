"use client";

// 클래스 상세 (#278/#279/#281/#282, 시안 v2 #633). 머리(이름·상태·통계 바) · 가입 링크 띠 · 탭 셋
// (문제 · 참여자 · 강사) · 문제 탭의 표와 오른쪽 「채점」·「최근 제출」 카드. 비강사에게는 백엔드가 404를 준다
// (존재를 알려주지 않는다) — 그때의 문구는 `AccessNotice` 가 그 사람의 목록 둘로 고른다(#1390). 「클래스를 템플릿으로
// 공개」는 여기 살지 않는다 — 학기에 한 번 할까 말까 한 일이라 「클래스 설정」으로 옮겼다(#323).
//
// 화면에 설명 문장을 두지 않는다 — 라벨·값·배지·버튼만. 채점 연결의 문제(키 없음·거부됨·크레딧
// 소진·서버 연결 불가)는 배너가 아니라 「채점」 카드의 상태 한 줄이 말한다.
// 강사 탭의 내용은 #635 가 다시 짠다 — 그때까지는 예전 화면을 그 자리에 둔다.
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { AccessNotice } from "@/app/components/AccessNotice";
import { ErrorNote, PageShell } from "@/app/components/ui";
import { ProblemImportSheet } from "@/app/components/ProblemImportSheet";
import { parseDetailTab } from "@/lib/classes/detail-tab";
import { scoringStatus } from "@/lib/classes/scoring-status";
import { offerEndNote } from "@/lib/co-instructors/transfer-end-note";
import { useClass } from "@/lib/classes/use-class";
import { INSTRUCTORS_CHANGED, NOTIFICATION_CHANGED, isClassSignal, type StreamEvent } from "@/lib/events/types";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";
import type { PickerTab } from "@/lib/problem-templates/picker-selection";
import { useProblems } from "@/lib/problems/use-problems";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

import { ClassDetailTabs } from "./class-detail-tabs";
import { ClassHead } from "./class-head";
import { GettingStartedCard, startSteps } from "./getting-started-card";
import { InstructorsSection } from "./instructors-section";
import { JoinLinkStrip } from "./join-link-strip";
import {
  OwnershipTransferAcceptedNote,
  OwnershipTransferDeclinedNote,
  OwnershipTransferOffer,
  OwnershipTransferTakenNote,
} from "./ownership-transfer-offer";
import { ParticipantsTab } from "./participants-tab";
import { ProblemsTable } from "./problems-table";
import { RecentAttemptsCard } from "./recent-attempts-card";
import { ScoringCard } from "./scoring-card";

function joinLinkUrl(joinCode: string): string {
  if (typeof window === "undefined") return "";
  return `${window.location.origin}/join/${joinCode}`;
}

const TRANSFER_FALLBACK_POLL_MS = 30_000;

function ClassDetail() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const tab = parseDetailTab(useSearchParams().get("tab"));
  const { state: classState, reload: reloadClass, regenerateJoinCode } = useClass(classId);
  // 방금 소유권을 넘겨받았는가(#564) — 키 넣기로 가는 안내를 한 번 보인다.
  const [justTookOver, setJustTookOver] = useState(false);
  const [justDeclined, setJustDeclined] = useState(false);
  // 이전 요청을 보낸 직후 한 번 — 강사 탭이 다시 그려진 뒤 「이전 대기」 줄로 초점을 옮긴다(#1435).
  const focusPendingTransfer = useRef(false);
  // 소유자가 보낸 이전 요청을 눌러 취소하려다 거절당했는가 — 그 사이 넘어갔으면 「이미 넘겨받았습니다」로 말한다(#1441).
  const cancelFailed = useRef(false);
  const [ownershipTaken, setOwnershipTaken] = useState<{ afterCancelAttempt: boolean } | null>(null);
  const previousRole = useRef<string | null>(null);
  const ready = classState.status === "ready" ? classState.classroom : null;
  const waitingForAnswer = ready?.role === "owner" && ready.pending_ownership_transfer !== null;
  // 강사 쪽 상태가 바뀌면(초대 수락·이전 요청·답, #1447 10-1) 클래스를 다시 읽는다 — 역할과 대기 요청이 여기 있다.
  // 소유권 이전의 답은 요청한 사람에게 알림으로도 온다(#1441) — 답을 기다리는 동안만 그 신호도 본다. 탭으로
  // 돌아오면 스트림이 다시 열리며 한 번 다시 읽는다(`decideStreamRefresh`).
  const matchesClassChange = useCallback(
    (event: StreamEvent) =>
      isClassSignal(event, INSTRUCTORS_CHANGED, classId) || (waitingForAnswer && event.kind === NOTIFICATION_CHANGED),
    [classId, waitingForAnswer],
  );
  useRealtimeRefresh({
    matches: matchesClassChange,
    waiting: waitingForAnswer,
    fallbackPollMs: TRANSFER_FALLBACK_POLL_MS,
    reload: reloadClass,
  });
  const currentRole = ready?.role ?? null;
  useEffect(() => {
    if (ready === null) return;
    if (previousRole.current === "owner" && currentRole !== "owner") {
      setOwnershipTaken({ afterCancelAttempt: cancelFailed.current });
    }
    previousRole.current = currentRole;
    cancelFailed.current = false;
  }, [ready, currentRole]);
  // 나에게 온 요청이 내가 답하기 전에 끝나면(소유자의 취소·만료) 맨 위 카드가 사라진다 — 끝남을 늘 있는 상태
  // 영역으로 읽고, 초점이 카드 안(수락·거절)에 있었으면 그 영역으로 옮긴다(#1447 검토, 소유자 쪽 #1448 ③과 같은 장치).
  const offerFocusWithin = useRef(false);
  const answeredByMe = useRef(false);
  const offerEndRef = useRef<HTMLParagraphElement>(null);
  const [offerEnd, setOfferEnd] = useState("");
  const offerOpen = ready?.pending_ownership_transfer?.recipient_is_me === true;
  const previousOffer = useRef(false);
  useEffect(() => {
    if (ready === null) return;
    const wasOpen = previousOffer.current;
    previousOffer.current = offerOpen;
    if (!wasOpen || offerOpen) return;
    const byMe = answeredByMe.current;
    answeredByMe.current = false;
    const hadFocus = offerFocusWithin.current;
    offerFocusWithin.current = false;
    if (byMe || ready.role !== "co_instructor") return;
    setOfferEnd(offerEndNote(ready.instructor_display_name));
    const active = document.activeElement;
    if (hadFocus && (active === null || active === document.body)) offerEndRef.current?.focus();
  }, [ready, offerOpen]);
  const { state: problemsState, reload: reloadProblems, move } = useProblems(classId);
  const router = useRouter();
  // 빈 목록의 입구가 시트를 곧장 그 탭으로 연다.
  const [pickerTab, setPickerTab] = useState<PickerTab | null>(null);

  useClassroomTabTitle({
    screenName: "클래스 상세",
    className: classState.status === "ready" ? classState.classroom.name : undefined,
  });

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
        <AccessNotice
          page="class"
          classId={classId}
          testId="classroom-detail-not-found"
          retry={{
            reload: () => {
              reloadClass();
              reloadProblems();
            },
            turns: [classState],
          }}
        />
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
      <ClassHead classroom={classroom} />

      <div className="flex flex-col gap-5">
        {/* 나에게 온 소유권 이전 요청(#564) — 답을 기다리는 일이라 맨 위에 둔다. */}
        <p
          ref={offerEndRef}
          role="status"
          tabIndex={-1}
          data-testid="ownership-transfer-offer-ended-note"
          className={offerEnd ? "text-[13px] text-ink/70 outline-none focus-visible:ring-2 focus-visible:ring-ink/40" : "sr-only"}
        >
          {offerEnd}
        </p>
        {classroom.pending_ownership_transfer?.recipient_is_me ? (
          <div
            onFocus={() => {
              offerFocusWithin.current = true;
            }}
            onBlur={(event) => {
              // 카드가 사라져 초점이 빠질 때는 relatedTarget 이 없다 — 그때는 「안에 있었다」를 지우지 않는다.
              const next = event.relatedTarget;
              if (next !== null && !event.currentTarget.contains(next)) offerFocusWithin.current = false;
            }}
          >
            <OwnershipTransferOffer
              classId={classId}
              transfer={classroom.pending_ownership_transfer}
              ownerName={classroom.instructor_display_name}
              onDone={(accepted) => {
                answeredByMe.current = true;
                setOfferEnd("");
                setJustTookOver(accepted);
                setJustDeclined(!accepted);
                reloadClass();
              }}
            />
          </div>
        ) : null}
        {justTookOver && classroom.role === "owner" ? <OwnershipTransferAcceptedNote classId={classId} /> : null}
        {justDeclined && !classroom.pending_ownership_transfer?.recipient_is_me ? <OwnershipTransferDeclinedNote /> : null}
        {ownershipTaken !== null && classroom.role !== "owner" ? (
          <OwnershipTransferTakenNote
            newOwnerName={classroom.instructor_display_name}
            afterCancelAttempt={ownershipTaken.afterCancelAttempt}
          />
        ) : null}

        <JoinLinkStrip
          joinCode={classroom.join_code}
          archived={classroom.archived}
          regenerateError={classState.regenerateError}
          onRegenerate={regenerateJoinCode}
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
            <ParticipantsTab classId={classId} onChanged={reloadClass} />
          ) : (
            // 역할과 대기 요청이 바뀌어도 영역을 새로 만들지 않는다 — 초점이 BODY 로 떨어진다(#1448 ③). 목록은 영역이 다시 읽는다.
            <InstructorsSection
              classId={classId}
              role={classroom.role}
              pendingTransfer={classroom.pending_ownership_transfer}
              onTransferChanged={(change) => {
                if (change === "requested") focusPendingTransfer.current = true;
                if (change === "cancel-failed") cancelFailed.current = true;
                reloadClass();
              }}
              focusPendingTransfer={focusPendingTransfer}
            />
          )}
        </div>
      </div>

      {pickerTab !== null ? (
        <ProblemImportSheet
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
