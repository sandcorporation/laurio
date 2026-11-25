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
import { Suspense, useEffect, useRef, useState } from "react";

import { AccessNotice } from "@/app/components/AccessNotice";
import { ErrorNote, PageShell } from "@/app/components/ui";
import { ProblemImportSheet } from "@/app/components/ProblemImportSheet";
import { parseDetailTab } from "@/lib/classes/detail-tab";
import { scoringStatus } from "@/lib/classes/scoring-status";
import { offerArrivedNote, offerEndNote } from "@/lib/co-instructors/transfer-end-note";
import { useClass } from "@/lib/classes/use-class";
import { useClassSignalReload } from "@/lib/classes/use-class-signal-reload";
import type { PickerTab } from "@/lib/problem-templates/picker-selection";
import { useProblems } from "@/lib/problems/use-problems";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

import { ClassDetailTabs, classDetailPanelProps } from "./class-detail-tabs";
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

function ClassDetail() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const tab = parseDetailTab(useSearchParams().get("tab"));
  const { state: classState, settled: classSettled, reload: reloadClass, regenerateJoinCode } = useClass(classId);
  // 방금 소유권을 넘겨받았는가(#564) — 키 넣기로 가는 안내를 한 번 보인다.
  const [justTookOver, setJustTookOver] = useState(false);
  const [justDeclined, setJustDeclined] = useState(false);
  // 이전 요청을 보낸 직후 한 번 — 강사 탭이 다시 그려진 뒤 「이전 대기」 줄로 초점을 옮긴다(#1435).
  const [focusPendingTransfer, setFocusPendingTransfer] = useState(false);
  // 소유자가 보낸 이전 요청을 눌러 취소하려다 거절당했는가 — 그 사이 넘어갔으면 「이미 넘겨받았습니다」로 말한다(#1441).
  const cancelFailed = useRef(false);
  const [ownershipTaken, setOwnershipTaken] = useState<{ afterCancelAttempt: boolean } | null>(null);
  const previousRole = useRef<string | null>(null);
  const ready = classState.status === "ready" ? classState.classroom : null;
  const waitingForAnswer = ready?.role === "owner" && ready.pending_ownership_transfer !== null;
  // 강사 쪽 상태가 바뀌면(초대 수락·이전 요청·답, #1447 10-1) 클래스를 다시 읽는다 — 역할과 대기 요청이 여기 있다.
  // 같은 변경의 재조회는 시간 창이 아니라 변경 번호로 하나가 된다(#1484 ④): 이미 읽은 번호의 신호는 건너뛴다. 재조회가
  // 실패해도 다음 신호가 다시 읽는다(#1496 ④).
  // 강사 영역은 이 응답에 맞춰 명단·대기 초대를 읽는다(`signalPending`). 탭으로 돌아오면 스트림이 다시 열리며 한 번 읽는다.
  const { signalPending, beginCommand, reloadAfterCommand } = useClassSignalReload({
    classId,
    settled: classSettled,
    // 옛 서버(겹쳐 배포 중)의 응답에는 번호가 없다 — 0 으로 채우면 읽은 번호가 신호보다 늘 작아 끝없이 다시 읽는다(#1496 ③).
    classroomSignalRev: typeof ready?.signal_rev === "number" ? ready.signal_rev : null,
    waitingForAnswer,
    reloadClass,
  });
  const currentRole = ready?.role ?? null;
  // 지난 소유권 안내(넘겨받음·거절·넘어감)는 새 이전 요청이 걸리면 걷고, 아무 일 없어도 낭독기가 읽을 시간 뒤 걷는다(#1517 취향 1).
  const pendingTransferId = ready?.pending_ownership_transfer?.id ?? null;
  // 「넘겨받았습니다」에는 할 일(채점 키 넣기)이 들어 있다 — 시간으로 걷지 않는다. 새 요청이 오거나 닫을 때만 걷힌다(#1528 A).
  const hasTimedTransferNote = justDeclined || ownershipTaken !== null;
  const lastPendingTransferId = useRef(pendingTransferId);
  // 지난 안내를 걷을 때 초점이 그 안(안내 자체·「채점 키 넣기」)에 있으면 BODY 로 떨어진다 — 걷기 직전에 다음 자리로 옮긴다.
  // 새 요청 카드가 있으면 그 카드, 없으면 제목. 초점이 안내 밖이면 건드리지 않는다.
  const pastNotesRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const offerRef = useRef<HTMLElement>(null);
  function keepFocusBeforeDroppingNotes() {
    const active = document.activeElement;
    if (active === null || !pastNotesRef.current?.contains(active)) return;
    (offerRef.current ?? titleRef.current)?.focus();
  }
  useEffect(() => {
    if (lastPendingTransferId.current === pendingTransferId) return;
    lastPendingTransferId.current = pendingTransferId;
    if (pendingTransferId === null) return;
    keepFocusBeforeDroppingNotes();
    setJustTookOver(false);
    setJustDeclined(false);
    setOwnershipTaken(null);
  }, [pendingTransferId]);
  // 채점 연결이 「연결됨」인가 — 카드가 보이는 같은 값(scoringStatus)이다. 넘겨받은 안내가 처음 보인 때의 값을 기억해 두고,
  // 키 없이 시작했다가 다시 불러온 결과에서 연결이 확인되면 안내를 걷고 완료 문구를 한 번 알린다(#1532 ②).
  const connectedNow = ready ? scoringStatus(ready).kind === "connected" : null;
  const [takeoverBaseline, setTakeoverBaseline] = useState<boolean | null>(null);
  const [keyAddedNote, setKeyAddedNote] = useState("");
  const takeoverNoteShown = justTookOver && ready?.role === "owner";
  useEffect(() => {
    if (!takeoverNoteShown) {
      setTakeoverBaseline(null);
      return;
    }
    if (connectedNow === null) return;
    if (takeoverBaseline === null) {
      setTakeoverBaseline(connectedNow);
      return;
    }
    if (takeoverBaseline === false && connectedNow) {
      keepFocusBeforeDroppingNotes();
      setJustTookOver(false);
      setKeyAddedNote("채점 키를 넣었습니다");
    }
  }, [takeoverNoteShown, connectedNow, takeoverBaseline]);
  useEffect(() => {
    if (!hasTimedTransferNote) return;
    const timer = window.setTimeout(() => {
      keepFocusBeforeDroppingNotes();
      setJustDeclined(false);
      setOwnershipTaken(null);
    }, 20_000);
    return () => window.clearTimeout(timer);
  }, [hasTimedTransferNote, justDeclined, ownershipTaken]);
  // 다른 사람(소유자)이 클래스를 보관·해제하면 머리 배지만 바뀐다 — 낭독기에 한 번 알린다(#1528 C). 초점은 건드리지 않는다.
  const archivedNow = ready?.archived ?? null;
  const previousArchived = useRef<boolean | null>(null);
  const [archivedNote, setArchivedNote] = useState("");
  useEffect(() => {
    if (archivedNow === null) return;
    if (previousArchived.current !== null && previousArchived.current !== archivedNow) {
      setArchivedNote(archivedNow ? "클래스가 보관됐습니다" : "클래스 보관이 해제됐습니다");
    }
    previousArchived.current = archivedNow;
  }, [archivedNow]);
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
  // 나에게 온 요청이 나타났을 때(열어 둔 채 신호로 오거나 처음 열 때) — 초점이 아무 데도 없으면 카드로 가서 읽히고,
  // 다른 곳에 있으면 초점을 빼앗지 않고 늘 있는 상태 영역이 읽어 준다(#1490).
  const [offerArrived, setOfferArrived] = useState("");
  useEffect(() => {
    if (ready === null) return;
    const wasOpen = previousOffer.current;
    previousOffer.current = offerOpen;
    if (offerOpen && !wasOpen) {
      setOfferEnd("");
      const active = document.activeElement;
      if (active === null || active === document.body || active === offerRef.current) {
        offerRef.current?.focus();
        setOfferArrived("");
      } else {
        setOfferArrived(offerArrivedNote(ready.instructor_display_name));
      }
      return;
    }
    if (!offerOpen) setOfferArrived("");
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
  // 화면이 그려져 있던 클래스가 접근을 잃으면(강사에서 빠짐) 쓰던 화면과 함께 초점이 사라진다 — 안내가 받는다(#1465 2).
  const [hadClass, setHadClass] = useState(false);
  useEffect(() => {
    if (classState.status === "ready") setHadClass(true);
  }, [classState.status]);
  // 빈 목록의 입구가 시트를 곧장 그 탭으로 연다.
  const [pickerTab, setPickerTab] = useState<PickerTab | null>(null);
  const pickerOpener = useRef<HTMLElement | null>(null);

  // 삭제 뒤 이동처럼 초점이 갈 곳 없이 body 에 있을 때만 제목이 받는다(#1517) — 다른 곳의 초점은 빼앗지 않는다.
  const classReady = classState.status === "ready";
  useEffect(() => {
    if (classReady && document.activeElement === document.body) titleRef.current?.focus();
  }, [classReady]);

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
          focusOnShow={hadClass}
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
      <ClassHead classroom={classroom} titleRef={titleRef} />

      <div className="flex flex-col gap-5">
        {/* 나에게 온 소유권 이전 요청(#564) — 답을 기다리는 일이라 맨 위에 둔다. */}
        <p role="status" data-testid="ownership-transfer-offer-arrived-note" className="sr-only">
          {offerArrived}
        </p>
        <p
          ref={offerEndRef}
          role="status"
          tabIndex={-1}
          data-testid="ownership-transfer-offer-ended-note"
          className={offerEnd ? "text-[13px] text-ink/70 outline-none focus-visible:ring-2 focus-visible:ring-ink/40" : "sr-only"}
        >
          {offerEnd}
        </p>
        <p role="status" data-testid="class-archived-note" className="sr-only">
          {archivedNote}
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
              sectionRef={offerRef}
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
        <div ref={pastNotesRef} className="contents">
        <p role="status" data-testid="scoring-key-added-note" className="sr-only">
          {keyAddedNote}
        </p>
        {justTookOver && classroom.role === "owner" ? <OwnershipTransferAcceptedNote
            classId={classId}
            onDismiss={() => {
              titleRef.current?.focus();
              setJustTookOver(false);
            }}
          /> : null}
        {justDeclined && !classroom.pending_ownership_transfer?.recipient_is_me ? <OwnershipTransferDeclinedNote /> : null}
        {ownershipTaken !== null && classroom.role !== "owner" ? (
          <OwnershipTransferTakenNote
            newOwnerName={classroom.instructor_display_name}
            afterCancelAttempt={ownershipTaken.afterCancelAttempt}
          />
        ) : null}
        </div>

        <JoinLinkStrip
          joinCode={classroom.join_code}
          archived={classroom.archived}
          regenerateError={classState.regenerateError}
          onRegenerate={regenerateJoinCode}
        />

        <div>
          <ClassDetailTabs classId={classId} active={tab} />

          <div {...classDetailPanelProps(tab)}>
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
                  onOpenPicker={(tab, opener) => {
                    pickerOpener.current = opener;
                    setPickerTab(tab);
                  }}
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
              onCommandStart={beginCommand}
              onTransferChanged={(change, seenRevAtStart) => {
                if (change === "requested") setFocusPendingTransfer(true);
                if (change === "cancel-failed") cancelFailed.current = true;
                // 같은 변경의 서버 신호는 번호로 알아본다 — 이미 읽은 번호면 건너뛰고, 명령 사이에 먼저 왔으면 그 신호가 읽는다(#1484 ④).
                reloadAfterCommand(seenRevAtStart);
              }}
              focusPendingTransfer={focusPendingTransfer}
              onFocusedPendingTransfer={() => setFocusPendingTransfer(false)}
              classVersion={classroom}
              signalPending={signalPending}
            />
          )}
          </div>
        </div>
      </div>

      {pickerTab !== null ? (
        <ProblemImportSheet
          classId={classId}
          initialTab={pickerTab}
          opener={pickerOpener.current}
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
