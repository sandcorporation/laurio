"use client";

// 클래스 관리의 「강사」 영역(#561·#562, CONTEXT.md 「공동 강사」·「공동 강사 초대」).
// 이 클래스를 함께 가르치는 사람들(소유자 먼저, 그다음 공동 강사를 수락한 순서로)과
// 아직 쓰이지 않은 공동 강사 초대를 보여 준다. 초대는 소유자 전용이 아니다 — 강사 누구나
// 만들고, 누가 만든 초대든 복사하고 취소한다. 보관된 클래스에서도 된다(사람을 들이는 일은
// 클래스의 존폐 쪽이다). 여러 개를 만들어도 앞의 것이 죽지 않는다 — 가입 링크의
// 「다시 뽑기」와 다르다. 취소는 되돌릴 수 없어 그 줄에서 「정말 취소」를 한 번 더 누른다(#1378).
//
// 떠나기·내보내기(#563): 소유자는 공동 강사 줄마다 「내보내기」를, 공동 강사는 맨 아래
// 「이 클래스 떠나기」를 본다. 둘 다 한 번 더 확인한다. 소유자는 떠날 수 없어 그 카드가 없다(#1381).
//
// 소유권 이전(#564, CONTEXT.md 「소유권 이전」): 소유자는 공동 강사 줄마다 「소유권 넘기기」를
// 보고, 넘기면 채점 키가 비워진다는 것을 확인한 뒤 요청한다. 요청은 클래스마다 하나라 대기 중이면
// 받는 사람의 줄에 「이전 요청 대기」와 (소유자에게) 「요청 취소」가 붙는다. 받는 사람의 수락·거절은
// 클래스 화면 맨 위의 `OwnershipTransferOffer` 가 묻는다.
//
// 배치(시안 v2, #635): 「강사」 탭의 왼쪽에 「이 클래스의 강사 N명」과 「공동 강사 초대」 두 카드,
// 공동 강사에게만 오른쪽에 「이 클래스 떠나기」 카드. 화면에는 설명 문장을 두지 않는다 — 역할 전용
// 행동은 다른 역할에게 그 버튼이 없는 것으로 말한다.
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState, type RefObject } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { Badge, Card, ErrorNote, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import type { PendingOwnershipTransfer } from "@/lib/classes/api";
import { pendingTransferEndNote, pendingTransferRowText } from "@/lib/co-instructors/transfer-end-note";
import { formatDay } from "@/lib/classes/format-day";
import { useInlineConfirm } from "@/lib/util/use-inline-confirm";
import { cancelTransferButtonLabel, removeButtonLabel, transferButtonLabel } from "@/lib/co-instructors/instructor-labels";
import {
  cancelCoInstructorInvite,
  cancelOwnershipTransfer,
  requestOwnershipTransfer,
  classInstructorsPath,
  coInstructorInviteUrl,
  createCoInstructorInvite,
  leaveClass,
  pendingCoInstructorInvitesPath,
  removeCoInstructor,
  type ClassInstructor,
  type PendingCoInstructorInvite,
} from "@/lib/co-instructors/api";

// 시안의 줄 끝 행동 — 테두리 없는 밑줄 글자.
const LINK_ACTION =
  "inline-flex items-center whitespace-nowrap px-3 py-1.5 text-xs text-ink/60 underline underline-offset-[3px] " +
  "transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-45";

type RowConfirm = "remove" | "transfer" | null;

function InstructorRow({
  instructor,
  canRemove,
  confirming,
  busy,
  transferPending,
  canTransfer,
  onAsk,
  onRemove,
  onTransfer,
  onCancelTransfer,
  onKeep,
  focusPending,
  onFocusedPending,
}: {
  instructor: ClassInstructor;
  // 부른 사람이 소유자이고 이 줄이 공동 강사일 때만 참이다.
  canRemove: boolean;
  confirming: RowConfirm;
  busy: boolean;
  // 이 줄의 사람에게 대기 중인 소유권 이전 요청이 있으면 그 요청.
  transferPending: PendingOwnershipTransfer | null;
  // 소유자이고 이 줄이 공동 강사이며 클래스에 대기 중인 요청이 없을 때만 참이다.
  canTransfer: boolean;
  onAsk: (what: Exclude<RowConfirm, null>) => void;
  onRemove: () => void;
  onTransfer: () => void;
  onCancelTransfer: () => void;
  onKeep: () => void;
  // 방금 보낸 이전 요청이면 「답을 기다립니다」 줄이 그려질 때 초점을 받는다.
  // 상태라서 신호·재조회가 응답보다 먼저 줄을 그렸어도, 요청이 끝나 참이 되는 순간 소비된다(#1496 ⑥).
  focusPending: boolean;
  onFocusedPending: () => void;
}) {
  const pendingRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (transferPending && focusPending && pendingRef.current) {
      pendingRef.current.focus();
      onFocusedPending();
    }
  }, [transferPending, focusPending, onFocusedPending]);
  const transferConfirm = useInlineConfirm(confirming === "transfer", onKeep);
  // 되돌리기 어려운 결과(채점 키가 비워짐)의 경고 문단도 확인 묶음의 설명에 든다 — 낭독기가 질문과 함께 읽는다(#1489).
  const transferWarningId = useId();
  const transferGroupProps = {
    ...transferConfirm.groupProps,
    "aria-describedby": `${transferConfirm.questionId} ${transferWarningId}`,
  };
  const removeConfirm = useInlineConfirm(confirming === "remove", onKeep);
  const owner = instructor.role === "owner";
  const name = instructor.display_name || (owner ? "이름을 정하지 않은 소유자" : "이름 없음");
  return (
    <li data-testid="class-instructor-row" className="flex flex-col gap-2 border-t border-rule px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span data-testid="class-instructor-name" className="text-[14px]">
          {name}
        </span>
        <span data-testid="class-instructor-role">
          <Badge>{owner ? "소유자" : "공동 강사"}</Badge>
        </span>
        {transferPending ? <Badge tone="warning">소유권 이전 대기</Badge> : null}
        {instructor.is_me ? (
          <span className="text-[12px] text-ink/45">나</span>
        ) : instructor.accepted_at ? (
          <span className="text-[12px] text-ink/45">
            {formatDay(instructor.accepted_at)} {instructor.joined_by === "ownership_transfer" ? "소유권 넘김" : "수락"}
          </span>
        ) : null}
        {transferPending && canRemove ? (
          <span
            ref={pendingRef}
            role="status"
            tabIndex={-1}
            data-testid="ownership-transfer-pending"
            className="text-[12px] text-ink/45 outline-none focus-visible:ring-2 focus-visible:ring-ink/40"
          >
            {pendingTransferRowText(transferPending, formatDay(transferPending.expires_at))}
          </span>
        ) : transferPending ? (
          // 보내는 쪽(소유자)만 상태로 읽힌다 — 받는 사람·다른 강사에게는 「답을 기다립니다」가 맥락에 맞지 않거나
          // 남의 일이라 알리지 않는다. 받는 사람에게는 클래스 화면 맨 위 카드가 알린다(#1490).
          <span data-testid="ownership-transfer-pending-other" className="text-[12px] text-ink/45">
            {pendingTransferRowText(transferPending, formatDay(transferPending.expires_at))}
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-1.5">
          {canTransfer && !confirming ? (
            <button
              type="button"
              data-testid="ownership-transfer-start"
              ref={transferConfirm.triggerRef}
              aria-label={transferButtonLabel(name)}
              onClick={() => onAsk("transfer")}
              className={LINK_ACTION}
            >
              소유권 넘기기
            </button>
          ) : null}
          {/* 이전 요청이 대기 중이면 「요청 취소」만 — 내보내려면 요청부터 거둔다(#669, 시안 Instructors). */}
          {canRemove && !confirming && !transferPending ? (
            <button
              type="button"
              data-testid="co-instructor-remove"
              ref={removeConfirm.triggerRef}
              aria-label={removeButtonLabel(name)}
              onClick={() => onAsk("remove")}
              className={LINK_ACTION}
            >
              내보내기
            </button>
          ) : null}
          {transferPending && canRemove ? (
            <button
              type="button"
              data-testid="ownership-transfer-cancel"
              aria-label={cancelTransferButtonLabel(name)}
              onClick={onCancelTransfer}
              disabled={busy}
              className={LINK_ACTION}
            >
              {busy ? "취소하는 중..." : "요청 취소"}
            </button>
          ) : null}
        </span>
      </div>
      {canTransfer && confirming === "transfer" ? (
        <div data-testid="ownership-transfer-confirm" {...transferGroupProps} className="flex flex-col gap-2 border border-rule bg-paper px-3 py-2.5">
          <p id={transferConfirm.questionId} className="text-[12.5px] leading-relaxed text-ink/70">
            {name}님에게 이 클래스의 소유권을 넘길까요? {name}님이 수락해야 넘어가고, 수락하면 {name}님이
            소유자가 되고 나는 공동 강사로 남습니다.
          </p>
          <p id={transferWarningId} className="text-[12.5px] leading-relaxed text-ink/70">
            넘어가는 순간 지금 채점 키가 비워져, 새 소유자가 자기 키를 넣을 때까지 참여자의 제출은 채점되지
            않고 기다립니다. 지금까지 쓴 양은 그대로 남습니다. 요청은 7일 동안 유효합니다.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              data-testid="ownership-transfer-confirm-button"
              onClick={onTransfer}
              disabled={busy}
              className={buttonClass("primary", "sm")}
            >
              {busy ? "요청하는 중..." : "이전 요청 보내기"}
            </button>
            <button ref={transferConfirm.keepRef} type="button" onClick={onKeep} disabled={busy} className={buttonClass("secondary", "sm")}>
              그만두기
            </button>
          </div>
        </div>
      ) : null}
      {canRemove && confirming === "remove" ? (
        <div data-testid="co-instructor-remove-confirm" {...removeConfirm.groupProps} className="flex flex-col gap-2 border border-rule bg-paper px-3 py-2.5">
          <p id={removeConfirm.questionId} className="text-[12.5px] leading-relaxed text-ink/70">
            {name}님을 내보낼까요? 이 클래스를 더는 다룰 수 없고, {name}님이 만든 아직 쓰이지 않은 초대도
            함께 취소됩니다. 이 클래스에서 낸 시도가 있으면 내보낸 참여자의 기록으로 남고 달성률에는 들지 않습니다.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              data-testid="co-instructor-remove-confirm-button"
              onClick={onRemove}
              disabled={busy}
              className={buttonClass("dangerFilled", "sm")}
            >
              {busy ? "내보내는 중..." : "내보내기"}
            </button>
            <button ref={removeConfirm.keepRef} type="button" onClick={onKeep} disabled={busy} className={buttonClass("secondary", "sm")}>
              취소
            </button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function PendingInviteRow({
  invite,
  copied,
  focusCopy,
  onFocusedCopy,
  confirming,
  cancelling,
  onCopy,
  onAsk,
  onCancel,
  onKeep,
}: {
  invite: PendingCoInstructorInvite;
  copied: boolean;
  // 방금 만든 링크 — 그 줄의 「복사」가 초점을 받는다(#1465 3).
  focusCopy: boolean;
  onFocusedCopy: () => void;
  confirming: boolean;
  cancelling: boolean;
  onCopy: (url: string) => void;
  onAsk: () => void;
  onCancel: () => void;
  onKeep: () => void;
}) {
  const cancelConfirm = useInlineConfirm(confirming, onKeep);
  const copyRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!focusCopy) return;
    copyRef.current?.focus();
    onFocusedCopy();
  }, [focusCopy, onFocusedCopy]);
  const url = typeof window === "undefined" ? "" : coInstructorInviteUrl(window.location.origin, invite.token);
  const maker = invite.created_by_me ? "내가" : `${invite.created_by_name || "소유자"}님이`;
  return (
    <li data-testid="co-instructor-invite-row" className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule px-4 py-2.5">
      <p
        data-testid="co-instructor-invite-link"
        className="min-w-0 flex-1 basis-64 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[12.5px]"
      >
        {url}
      </p>
      <span data-testid="co-instructor-invite-meta" className="text-[12px] text-ink/45">
        {maker} {formatDay(invite.created_at)} 만듦 · {formatDay(invite.expires_at)} 까지
      </span>
      <span
        className="flex items-center gap-1.5"
        {...(confirming ? { role: "group", "aria-describedby": cancelConfirm.questionId } : {})}
        onKeyDown={cancelConfirm.onKeyDown}
      >
        {confirming ? (
          <span id={cancelConfirm.questionId} className="sr-only">
            이 초대 링크를 취소할까요? 취소한 링크는 다시 쓸 수 없습니다.
          </span>
        ) : null}
        <button
          type="button"
          data-testid="co-instructor-invite-copy"
          ref={copyRef}
          onClick={() => onCopy(url)}
          className={buttonClass("secondary", "sm")}
        >
          {copied ? "복사됨" : "복사"}
        </button>
        {confirming ? (
          <>
            <button
              type="button"
              data-testid="co-instructor-invite-cancel-confirm-button"
              onClick={onCancel}
              disabled={cancelling}
              className={buttonClass("dangerFilled", "sm")}
            >
              {cancelling ? "취소하는 중..." : "정말 취소"}
            </button>
            <button
              type="button"
              data-testid="co-instructor-invite-cancel-keep"
              ref={cancelConfirm.keepRef}
              onClick={onKeep}
              disabled={cancelling}
              className={buttonClass("secondary", "sm")}
            >
              그대로 두기
            </button>
          </>
        ) : (
          <button
            ref={cancelConfirm.triggerRef}
            type="button"
            data-testid="co-instructor-invite-cancel"
            onClick={onAsk}
            className={LINK_ACTION}
          >
            취소
          </button>
        )}
      </span>
    </li>
  );
}

function LeaveSection({ classId }: { classId: number }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const leaveConfirm = useInlineConfirm(confirming, () => setConfirming(false));

  async function leave() {
    setLeaving(true);
    setError(null);
    const result = await leaveClass(classId);
    if (result.ok) {
      // 떠난 클래스는 더 열리지 않는다 — 내 클래스 목록으로 간다.
      router.replace("/");
      return;
    }
    setError(result.detail);
    setLeaving(false);
  }

  return (
    <Card>
      <h2 className="border-b border-rule px-4 py-3 text-[15px] font-semibold tracking-[-0.005em]">이 클래스 떠나기</h2>
      <div className="flex flex-col gap-3 px-4 py-3">
        {confirming ? (
          <div data-testid="class-leave-confirm" {...leaveConfirm.groupProps} className="flex flex-col gap-2 border border-rule bg-paper px-3 py-2.5">
            <p id={leaveConfirm.questionId} className="text-[12.5px] leading-relaxed text-ink/70">
              이 클래스를 떠날까요? 내 클래스 목록에서 사라지고, 다시 함께 가르치려면 새 초대를 받아야
              합니다. 내가 만든 아직 쓰이지 않은 초대는 취소되고, 이 클래스에서 낸 시도는 지워지지 않고
              남습니다.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                data-testid="class-leave-confirm-button"
                onClick={() => void leave()}
                disabled={leaving}
                className={buttonClass("dangerFilled", "sm")}
              >
                {leaving ? "떠나는 중..." : "떠나기"}
              </button>
              <button
                ref={leaveConfirm.keepRef}
                type="button"
                onClick={() => setConfirming(false)}
                disabled={leaving}
                className={buttonClass("secondary", "sm")}
              >
                그대로 있기
              </button>
            </div>
          </div>
        ) : (
          <div>
            <button
              type="button"
              data-testid="class-leave"
              ref={leaveConfirm.triggerRef}
              onClick={() => setConfirming(true)}
              className={buttonClass("danger", "sm")}
            >
              떠나기
            </button>
          </div>
        )}
        {error ? (
          <ErrorNote>
            <span data-testid="class-leave-error">{error}</span>
          </ErrorNote>
        ) : null}
      </div>
    </Card>
  );
}

export function InstructorsSection({
  classId,
  role,
  pendingTransfer,
  onCommandStart,
  onTransferChanged,
  focusPendingTransfer,
  onFocusedPendingTransfer,
  classVersion,
  signalPending,
}: {
  classId: number;
  // 부른 사람의 이 클래스 역할 — 클래스 응답에서 온다. 바뀌면(넘겨받기·넘겨주기) 목록을 다시 읽는다.
  role: "owner" | "co_instructor";
  // 클래스의 대기 중 소유권 이전 요청 — 클래스 응답(`ClassRow`)에서 온다.
  pendingTransfer: PendingOwnershipTransfer | null;
  // 요청·취소 뒤 클래스를 다시 읽는다. 취소가 거절당하면(그 사이 끝났을 수 있다) `cancel-failed`.
  // 명령을 보내기 직전 — 그때까지 본 신호 번호를 받아 끝날 때 `onTransferChanged` 에 돌려준다(#1484 ④).
  onCommandStart: () => number;
  onTransferChanged: (change: "requested" | "cancel-failed" | undefined, seenRevAtStart: number) => void;
  // 요청을 보낸 뒤 강사 목록이 다시 그려지므로(key) 초점 표시는 그 바깥에 둔다.
  focusPendingTransfer: boolean;
  onFocusedPendingTransfer: () => void;
  // 클래스 응답 — 새로 도착할 때마다 바뀐다. 신호로 시작된 재조회의 응답이 오면 명단·대기 초대를 한 번 다시 읽는다(#1459 ⑥).
  classVersion: unknown;
  // 신호가 클래스 재조회를 시작했고 그 응답을 아직 못 받았다 — 재조회는 클래스 화면이 한 번만 시작하고 이 영역이 그 응답에 맞춰 읽는다.
  signalPending: RefObject<boolean>;
}) {
  const { state: rosterState, reload: reloadRoster } = useBackendQuery<ClassInstructor[]>(bffClient, classInstructorsPath(classId));
  const { state: invitesState, reload: reloadInvites } = useBackendQuery<PendingCoInstructorInvite[]>(
    bffClient,
    pendingCoInstructorInvitesPath(classId),
  );
  const [creating, setCreating] = useState(false);
  // 내보내기·초대 취소가 끝나면 누른 줄이 사라진다 — 초점을 늘 있는 「초대 링크 만들기」로 옮긴다(#1400).
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  // 만든 링크는 그 줄의 「복사」로 초점을 옮기고 늘 있는 상태 영역에 적는다(#1465 3, 템플릿 공개 #1447 1-3 과 같은 꼴).
  const [createdNote, setCreatedNote] = useState("");
  const [focusInviteId, setFocusInviteId] = useState<number | null>(null);
  const clearFocusInvite = useCallback(() => setFocusInviteId(null), []);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [confirmingInviteId, setConfirmingInviteId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 한 번에 한 줄의 한 확인만 연다 — 내보내기 또는 소유권 넘기기.
  const [confirming, setConfirming] = useState<{ id: number; what: Exclude<RowConfirm, null> } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const reloadBoth = useCallback(() => {
    reloadRoster();
    reloadInvites();
  }, [reloadRoster, reloadInvites]);
  // 대기 요청이 끝났는데(거절·만료·취소) 소유자로 남았으면 결과를 알린다 — 그 줄의 「요청 취소」가 사라지므로
  // 초점이 그 안에 있었으면 강사 표 제목으로 옮긴다(#1448 ③). 역할이 바뀐 끝(넘겨줌)은 클래스 화면의 안내가 맡는다.
  const rootRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusWithin = useRef(false);
  const cancelledByMe = useRef(false);
  const [transferNote, setTransferNote] = useState("");
  const previous = useRef({ role, pendingTransfer });
  useEffect(() => {
    const before = previous.current;
    previous.current = { role, pendingTransfer };
    const signalled = signalPending.current;
    signalPending.current = false;
    const changed = !(before.role === role && before.pendingTransfer?.id === pendingTransfer?.id);
    // 상대가 초대를 수락하거나 이전에 답했거나(신호) 역할·대기 요청이 바뀌면(명단의 줄 모양이 바뀐다) 한 번만 다시 읽는다.
    if (signalled || changed) reloadBoth();
    if (!changed) return;
    setConfirming(null);
    const note = pendingTransferEndNote({
      ended: before.pendingTransfer,
      now: pendingTransfer,
      stillOwner: before.role === "owner" && role === "owner",
      cancelledByMe: cancelledByMe.current,
    });
    cancelledByMe.current = false;
    // 새 요청이 걸렸거나 역할이 바뀌었으면 앞의 끝남 문구는 더 맞지 않는다(#1464).
    setTransferNote(note ?? "");
    if (note === null) return;
    const active = document.activeElement;
    const lost = active === null || active === document.body || !rootRef.current?.contains(active);
    if (focusWithin.current && lost) headingRef.current?.focus();
  }, [role, pendingTransfer, classVersion, signalPending, reloadBoth]);

  const roster = rosterState.status === "ready" ? rosterState.data : [];

  // 상대가 초대를 수락하면 명단이 늘고 그 대기 초대 줄이 사라진다 — 수락은 늘 있는 상태 영역으로 읽히고, 초점이
  // 사라진 줄 안에 있었으면 늘 있는 「초대 링크 만들기」로 옮긴다(#1459 ④).
  const inviteListFocus = useRef(false);
  const knownInstructorIds = useRef<Set<number> | null>(null);
  const knownInviteIds = useRef<Set<number> | null>(null);
  const [acceptedNote, setAcceptedNote] = useState("");
  useEffect(() => {
    if (rosterState.status !== "ready") return;
    const known = knownInstructorIds.current;
    knownInstructorIds.current = new Set(
      rosterState.data.flatMap((instructor) => (instructor.co_instructor_id === null ? [] : [instructor.co_instructor_id])),
    );
    if (known === null) return;
    const joined = rosterState.data.filter(
      (instructor) =>
        instructor.co_instructor_id !== null && !known.has(instructor.co_instructor_id) && instructor.joined_by === "invite",
    );
    if (joined.length > 0) setAcceptedNote(`${joined.map((instructor) => instructor.display_name).join(", ")} 님이 초대를 수락했습니다`);
  }, [rosterState]);
  useEffect(() => {
    if (invitesState.status !== "ready") return;
    const known = knownInviteIds.current;
    knownInviteIds.current = new Set(invitesState.data.map((invite) => invite.id));
    if (known === null || !inviteListFocus.current) return;
    if (![...known].some((id) => !knownInviteIds.current?.has(id))) return;
    const active = document.activeElement;
    if (active === null || active === document.body || !rootRef.current?.contains(active)) {
      createButtonRef.current?.focus();
      inviteListFocus.current = false;
    }
  }, [invitesState]);
  const me = roster.find((instructor) => instructor.is_me);
  const iAmOwner = me?.role === "owner";

  async function transfer(coInstructorId: number) {
    const seenRevAtStart = onCommandStart();
    setBusyId(coInstructorId);
    setError(null);
    const result = await requestOwnershipTransfer(classId, coInstructorId);
    if (!result.ok) {
      setError(result.detail);
    }
    setConfirming(null);
    setBusyId(null);
    onTransferChanged(result.ok ? "requested" : undefined, seenRevAtStart);
  }

  async function cancelTransfer(coInstructorId: number, transferId: number) {
    const seenRevAtStart = onCommandStart();
    setBusyId(coInstructorId);
    setError(null);
    const result = await cancelOwnershipTransfer(classId, transferId);
    if (!result.ok) {
      setError(result.detail);
    } else {
      cancelledByMe.current = true;
    }
    setBusyId(null);
    onTransferChanged(result.ok ? undefined : "cancel-failed", seenRevAtStart);
  }

  async function remove(coInstructorId: number) {
    const seenRevAtStart = onCommandStart();
    setBusyId(coInstructorId);
    setError(null);
    const result = await removeCoInstructor(classId, coInstructorId);
    if (!result.ok) {
      setError(result.detail);
    }
    // 내보낸 사람이 만든 대기 초대도 취소되므로 명단·초대를 다시 읽는다 — 같은 변경의 서버 신호와 한 번에(#1471 ②).
    if (result.ok) createButtonRef.current?.focus();
    setConfirming(null);
    setBusyId(null);
    // 내보낸 사람에게 온 대기 이전 요청도 사라진다.
    onTransferChanged(undefined, seenRevAtStart);
  }

  async function create() {
    const seenRevAtStart = onCommandStart();
    setCreating(true);
    setError(null);
    setCreatedNote("");
    const result = await createCoInstructorInvite(classId);
    if (result.ok) {
      setFocusInviteId(result.data.id);
      setCreatedNote("초대 링크를 만들었습니다");
      // 같은 변경의 서버 신호와 합쳐 클래스 화면이 한 번만 다시 읽는다(#1471 ②).
      onTransferChanged(undefined, seenRevAtStart);
    } else {
      setError(result.detail);
    }
    setCreating(false);
  }

  async function cancel(inviteId: number) {
    const seenRevAtStart = onCommandStart();
    setCancellingId(inviteId);
    setError(null);
    const result = await cancelCoInstructorInvite(classId, inviteId);
    if (!result.ok) {
      setError(result.detail);
    }
    // 실패해도 다시 읽는다 — 그 사이 누가 수락했거나 다른 강사가 먼저 취소했으면 목록에서 빠진다.
    onTransferChanged(undefined, seenRevAtStart);
    if (result.ok) createButtonRef.current?.focus();
    setConfirmingInviteId(null);
    setCancellingId(null);
  }

  async function copy(inviteId: number, url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedId(inviteId);
      window.setTimeout(() => setCopiedId((current) => (current === inviteId ? null : current)), 2000);
    } catch {
      setCopiedId(null);
    }
  }

  const invites = invitesState.status === "ready" ? invitesState.data : [];

  return (
    <div
      ref={rootRef}
      onFocus={() => {
        focusWithin.current = true;
      }}
      onBlur={(event) => {
        // 줄이 사라져 초점이 빠질 때는 relatedTarget 이 없다 — 그때는 「안에 있었다」를 지우지 않는다.
        const next = event.relatedTarget;
        if (next !== null && !rootRef.current?.contains(next)) focusWithin.current = false;
      }}
      className="flex flex-col gap-5 pt-5 lg:flex-row lg:items-start"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-5">
        <p role="status" data-testid="ownership-transfer-ended-note" className={transferNote ? "text-[13px] text-ink/70" : "sr-only"}>
          {transferNote}
        </p>
        <p role="status" data-testid="co-instructor-accepted-note" className={acceptedNote ? "text-[13px] text-ink/70" : "sr-only"}>
          {acceptedNote}
        </p>
        <p role="status" data-testid="co-instructor-created-note" className="sr-only">
          {createdNote}
        </p>
        <Card>
          <h2
            ref={headingRef}
            tabIndex={-1}
            data-testid="class-instructors-heading"
            className="flex items-baseline gap-2.5 px-4 py-3 text-[15px] font-semibold tracking-[-0.005em] outline-none focus-visible:ring-2 focus-visible:ring-ink/40"
          >
            이 클래스의 강사
            {rosterState.status === "ready" ? (
              <span data-testid="class-instructors-count" className="text-[12.5px] font-normal text-ink/45">
                {rosterState.data.length}명
              </span>
            ) : null}
          </h2>
          {rosterState.status === "ready" ? (
            <ul data-testid="class-instructors">
              {rosterState.data.map((instructor) => {
                const id = instructor.co_instructor_id;
                const pendingHere =
                  pendingTransfer !== null && id !== null && pendingTransfer.recipient_co_instructor_id === id
                    ? pendingTransfer
                    : null;
                return (
                  <InstructorRow
                    key={id ?? "owner"}
                    instructor={instructor}
                    canRemove={iAmOwner && id !== null}
                    confirming={id !== null && confirming?.id === id ? confirming.what : null}
                    busy={id !== null && busyId === id}
                    transferPending={pendingHere}
                    canTransfer={iAmOwner && id !== null && pendingTransfer === null}
                    onAsk={(what) => id !== null && setConfirming({ id, what })}
                    onRemove={() => id !== null && void remove(id)}
                    onTransfer={() => id !== null && void transfer(id)}
                    onCancelTransfer={() => id !== null && pendingHere && void cancelTransfer(id, pendingHere.id)}
                    onKeep={() => setConfirming(null)}
                    focusPending={focusPendingTransfer}
                    onFocusedPending={onFocusedPendingTransfer}
                  />
                );
              })}
            </ul>
          ) : rosterState.status === "error" ? (
            <div className="border-t border-rule px-4 py-3">
              <ErrorNote>강사 목록을 불러오지 못했습니다.</ErrorNote>
            </div>
          ) : null}
        </Card>

        <Card>
          <div className="flex items-center justify-between gap-3 px-4 py-3">
            <h2 className="text-[15px] font-semibold tracking-[-0.005em]">공동 강사 초대</h2>
            <button
              type="button"
              data-testid="co-instructor-invite-create"
              ref={createButtonRef}
              onClick={() => void create()}
              disabled={creating}
              className={buttonClass("primary", "sm")}
            >
              {creating ? "만드는 중..." : "초대 링크 만들기"}
            </button>
          </div>
          {invites.length > 0 ? (
            <ul
              data-testid="co-instructor-invites"
              onFocus={() => {
                inviteListFocus.current = true;
              }}
              onBlur={(event) => {
                // 줄이 사라져 초점이 빠질 때는 relatedTarget 이 없다 — 그때는 「안에 있었다」를 지우지 않는다.
                const next = event.relatedTarget;
                if (next !== null && !event.currentTarget.contains(next as Node)) inviteListFocus.current = false;
              }}
            >
              {invites.map((invite) => (
                <PendingInviteRow
                  key={invite.id}
                  invite={invite}
                  copied={copiedId === invite.id}
                  focusCopy={focusInviteId === invite.id}
                  onFocusedCopy={clearFocusInvite}
                  confirming={confirmingInviteId === invite.id}
                  cancelling={cancellingId === invite.id}
                  onCopy={(url) => void copy(invite.id, url)}
                  onAsk={() => setConfirmingInviteId(invite.id)}
                  onCancel={() => void cancel(invite.id)}
                  onKeep={() => setConfirmingInviteId(null)}
                />
              ))}
            </ul>
          ) : invitesState.status === "error" ? (
            <div className="border-t border-rule px-4 py-3">
              <ErrorNote>초대 목록을 불러오지 못했습니다.</ErrorNote>
            </div>
          ) : null}
          {error ? (
            <div className="border-t border-rule px-4 py-3">
              <ErrorNote>
                <span data-testid="co-instructor-invite-error">{error}</span>
              </ErrorNote>
            </div>
          ) : null}
        </Card>
      </div>
      {me && !iAmOwner ? (
        <div className="w-full shrink-0 lg:w-80">
          <LeaveSection classId={classId} />
        </div>
      ) : null}
    </div>
  );
}
