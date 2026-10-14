"use client";

// 클래스 관리의 「강사」 영역(#561·#562, CONTEXT.md 「공동 강사」·「공동 강사 초대」).
// 이 클래스를 함께 가르치는 사람들(소유자 먼저, 그다음 공동 강사를 수락한 순서로)과
// 아직 쓰이지 않은 공동 강사 초대를 보여 준다. 초대는 소유자 전용이 아니다 — 강사 누구나
// 만들고, 누가 만든 초대든 복사하고 취소한다. 보관된 클래스에서도 된다(사람을 들이는 일은
// 클래스의 존폐 쪽이다). 여러 개를 만들어도 앞의 것이 죽지 않는다 — 가입 링크의
// 「다시 뽑기」와 다르다.
//
// 떠나기·내보내기(#563): 소유자는 공동 강사 줄마다 「내보내기」를, 공동 강사는 맨 아래
// 「이 클래스 떠나기」를 본다. 둘 다 한 번 더 확인한다. 소유자는 떠날 수 없어 그 자리에
// 대신 할 일(넘기기·보관·삭제)을 말한다.
//
// 소유권 이전(#564, CONTEXT.md 「소유권 이전」): 소유자는 공동 강사 줄마다 「소유권 넘기기」를
// 보고, 넘기면 채점 키가 비워진다는 것을 확인한 뒤 요청한다. 요청은 클래스마다 하나라 대기 중이면
// 받는 사람의 줄에 「이전 요청 대기」와 (소유자에게) 「요청 취소」가 붙는다. 받는 사람의 수락·거절은
// 클래스 화면 맨 위의 `OwnershipTransferOffer` 가 묻는다.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { Badge, Card, CardHeader, CardSection, ErrorNote, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import type { PendingOwnershipTransfer } from "@/lib/classes/api";
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

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

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
}) {
  const owner = instructor.role === "owner";
  const name = instructor.display_name || (owner ? "이름을 정하지 않은 소유자" : "이름 없음");
  return (
    <li data-testid="class-instructor-row" className="flex flex-col gap-2 px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span data-testid="class-instructor-name" className="text-[13.5px]">
          {name}
        </span>
        {instructor.is_me ? <span className="text-[12px] text-ink/45">나</span> : null}
        <span data-testid="class-instructor-role">
          <Badge tone={owner ? "verified" : "neutral"}>{owner ? "소유자" : "공동 강사"}</Badge>
        </span>
        <span className="ml-auto flex items-center gap-2.5">
          {instructor.accepted_at ? (
            <span className="text-[12px] text-ink/45">
              {formatWhen(instructor.accepted_at)}{" "}
              {instructor.joined_by === "ownership_transfer" ? "소유권 넘김" : "수락"}
            </span>
          ) : null}
          {canTransfer && !confirming ? (
            <button
              type="button"
              data-testid="ownership-transfer-start"
              onClick={() => onAsk("transfer")}
              className={buttonClass("secondary", "sm")}
            >
              소유권 넘기기
            </button>
          ) : null}
          {canRemove && !confirming ? (
            <button
              type="button"
              data-testid="co-instructor-remove"
              onClick={() => onAsk("remove")}
              className={buttonClass("danger", "sm")}
            >
              내보내기
            </button>
          ) : null}
        </span>
      </div>
      {transferPending ? (
        <div
          data-testid="ownership-transfer-pending"
          className="flex flex-wrap items-center justify-between gap-2 border border-rule bg-paper px-3 py-2"
        >
          <span className="flex flex-wrap items-center gap-2 text-[12.5px] text-ink/70">
            <Badge tone="attention">소유권 이전 대기</Badge>
            {instructor.is_me
              ? `${formatWhen(transferPending.expires_at)}까지 답할 수 있습니다.`
              : `${name}님의 수락을 기다립니다 · ${formatWhen(transferPending.expires_at)}에 만료`}
          </span>
          {canRemove ? (
            <button
              type="button"
              data-testid="ownership-transfer-cancel"
              onClick={onCancelTransfer}
              disabled={busy}
              className={buttonClass("secondary", "sm")}
            >
              {busy ? "취소하는 중..." : "요청 취소"}
            </button>
          ) : null}
        </div>
      ) : null}
      {canTransfer && confirming === "transfer" ? (
        <div data-testid="ownership-transfer-confirm" className="flex flex-col gap-2 border border-rule bg-paper px-3 py-2.5">
          <p className="text-[12.5px] leading-relaxed text-ink/70">
            {name}님에게 이 클래스의 소유권을 넘길까요? {name}님이 수락해야 넘어가고, 수락하면 {name}님이
            소유자가 되고 나는 공동 강사로 남습니다.
          </p>
          <p className="text-[12.5px] leading-relaxed text-ink/70">
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
            <button type="button" onClick={onKeep} disabled={busy} className={buttonClass("secondary", "sm")}>
              그만두기
            </button>
          </div>
        </div>
      ) : null}
      {canRemove && confirming === "remove" ? (
        <div data-testid="co-instructor-remove-confirm" className="flex flex-col gap-2 border border-rule bg-paper px-3 py-2.5">
          <p className="text-[12.5px] leading-relaxed text-ink/70">
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
            <button type="button" onClick={onKeep} disabled={busy} className={buttonClass("secondary", "sm")}>
              그대로 두기
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
  cancelling,
  onCopy,
  onCancel,
}: {
  invite: PendingCoInstructorInvite;
  copied: boolean;
  cancelling: boolean;
  onCopy: (url: string) => void;
  onCancel: () => void;
}) {
  const url = typeof window === "undefined" ? "" : coInstructorInviteUrl(window.location.origin, invite.token);
  const maker = invite.created_by_me ? "내가" : `${invite.created_by_name || "소유자"}님이`;
  return (
    <li data-testid="co-instructor-invite-row" className="flex flex-col gap-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <p
          data-testid="co-instructor-invite-link"
          className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap border border-rule bg-paper px-3 py-2 font-mono text-[13px]"
        >
          {url}
        </p>
        <button
          type="button"
          data-testid="co-instructor-invite-copy"
          onClick={() => onCopy(url)}
          className={buttonClass("secondary", "sm")}
        >
          {copied ? "복사됨" : "복사"}
        </button>
        <button
          type="button"
          data-testid="co-instructor-invite-cancel"
          onClick={onCancel}
          disabled={cancelling}
          className={buttonClass("danger", "sm")}
        >
          {cancelling ? "취소하는 중..." : "취소"}
        </button>
      </div>
      <p data-testid="co-instructor-invite-meta" className="text-[12px] text-ink/50">
        {maker} {formatWhen(invite.created_at)}에 만듦 · {formatWhen(invite.expires_at)}까지 쓸 수 있음
      </p>
    </li>
  );
}

function LeaveSection({ classId, owner }: { classId: number; owner: boolean }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  if (owner) {
    return (
      <CardSection title="이 클래스 떠나기">
        <p data-testid="class-leave-owner-note" className="px-4 pb-4 pt-2 text-[12.5px] leading-relaxed text-ink/60">
          소유자는 클래스를 떠날 수 없습니다. 떠나려면 먼저 위 강사 목록에서 공동 강사에게 소유권을
          넘기세요 — 넘기면 공동 강사가 되어 떠날 수 있습니다. 수업을 끝내려면 이 화면에서 클래스를
          보관하고, 없던 일로 하려면{" "}
          <Link href={`/classes/${classId}/settings`} className="underline underline-offset-2">
            클래스 설정
          </Link>
          에서 삭제하세요.
        </p>
      </CardSection>
    );
  }

  return (
    <CardSection title="이 클래스 떠나기">
      <div className="flex flex-col gap-3 px-4 pb-4 pt-2">
        {confirming ? (
          <div data-testid="class-leave-confirm" className="flex flex-col gap-2 border border-rule bg-paper px-3 py-2.5">
            <p className="text-[12.5px] leading-relaxed text-ink/70">
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
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-[12px] leading-relaxed text-ink/45">
              공동 강사는 언제든 스스로 떠날 수 있습니다.
            </span>
            <button
              type="button"
              data-testid="class-leave"
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
    </CardSection>
  );
}

export function InstructorsSection({
  classId,
  pendingTransfer,
  onTransferChanged,
}: {
  classId: number;
  // 클래스의 대기 중 소유권 이전 요청 — 클래스 응답(`ClassRow`)에서 온다.
  pendingTransfer: PendingOwnershipTransfer | null;
  // 요청·취소 뒤 클래스를 다시 읽는다.
  onTransferChanged: () => void;
}) {
  const { state: rosterState, reload: reloadRoster } = useBackendQuery<ClassInstructor[]>(bffClient, classInstructorsPath(classId));
  const { state: invitesState, reload: reloadInvites } = useBackendQuery<PendingCoInstructorInvite[]>(
    bffClient,
    pendingCoInstructorInvitesPath(classId),
  );
  const [creating, setCreating] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 한 번에 한 줄의 한 확인만 연다 — 내보내기 또는 소유권 넘기기.
  const [confirming, setConfirming] = useState<{ id: number; what: Exclude<RowConfirm, null> } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const roster = rosterState.status === "ready" ? rosterState.data : [];
  const me = roster.find((instructor) => instructor.is_me);
  const iAmOwner = me?.role === "owner";

  async function transfer(coInstructorId: number) {
    setBusyId(coInstructorId);
    setError(null);
    const result = await requestOwnershipTransfer(classId, coInstructorId);
    if (!result.ok) {
      setError(result.detail);
    }
    setConfirming(null);
    setBusyId(null);
    onTransferChanged();
  }

  async function cancelTransfer(coInstructorId: number, transferId: number) {
    setBusyId(coInstructorId);
    setError(null);
    const result = await cancelOwnershipTransfer(classId, transferId);
    if (!result.ok) {
      setError(result.detail);
    }
    setBusyId(null);
    onTransferChanged();
  }

  async function remove(coInstructorId: number) {
    setBusyId(coInstructorId);
    setError(null);
    const result = await removeCoInstructor(classId, coInstructorId);
    if (!result.ok) {
      setError(result.detail);
    }
    // 내보낸 사람이 만든 대기 초대도 취소되므로 둘 다 다시 읽는다.
    reloadRoster();
    reloadInvites();
    setConfirming(null);
    setBusyId(null);
    // 내보낸 사람에게 온 대기 이전 요청도 사라진다.
    onTransferChanged();
  }

  async function create() {
    setCreating(true);
    setError(null);
    const result = await createCoInstructorInvite(classId);
    if (result.ok) {
      reloadInvites();
    } else {
      setError(result.detail);
    }
    setCreating(false);
  }

  async function cancel(inviteId: number) {
    setCancellingId(inviteId);
    setError(null);
    const result = await cancelCoInstructorInvite(classId, inviteId);
    if (!result.ok) {
      setError(result.detail);
    }
    // 실패해도 다시 읽는다 — 그 사이 누가 수락했거나 다른 강사가 먼저 취소했으면 목록에서 빠진다.
    reloadInvites();
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
    <Card>
      <CardHeader title="강사" hint="이 클래스를 함께 가르치는 사람들" />
      <div className="divide-y divide-rule">
        {rosterState.status === "ready" ? (
          <ul data-testid="class-instructors" className="divide-y divide-rule">
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
                />
              );
            })}
          </ul>
        ) : rosterState.status === "error" ? (
          <div className="px-4 py-3">
            <ErrorNote>강사 목록을 불러오지 못했습니다.</ErrorNote>
          </div>
        ) : null}

        <CardSection
          title="공동 강사 초대"
          hint="함께 가르칠 사람에게 건넬 링크입니다 — 한 사람이 한 번만 쓸 수 있습니다"
        >
          <div className="flex flex-col gap-3 pb-4 pt-2">
            {invites.length > 0 ? (
              <ul data-testid="co-instructor-invites" className="divide-y divide-rule border-y border-rule">
                {invites.map((invite) => (
                  <PendingInviteRow
                    key={invite.id}
                    invite={invite}
                    copied={copiedId === invite.id}
                    cancelling={cancellingId === invite.id}
                    onCopy={(url) => void copy(invite.id, url)}
                    onCancel={() => void cancel(invite.id)}
                  />
                ))}
              </ul>
            ) : invitesState.status === "ready" ? (
              <p data-testid="co-instructor-invites-empty" className="px-4 text-[12.5px] text-ink/60">
                아직 쓰이지 않은 초대가 없습니다.
              </p>
            ) : invitesState.status === "error" ? (
              <div className="px-4">
                <ErrorNote>초대 목록을 불러오지 못했습니다.</ErrorNote>
              </div>
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-3 px-4">
              <span className="text-[12px] leading-relaxed text-ink/45">
                링크는 7일 뒤 만료됩니다. 여러 사람을 초대하려면 사람마다 하나씩 만드세요. 수락한 사람은
                문제·명단·보관을 소유자와 똑같이 다루고, 채점 키, 클래스 삭제, 소유권 이전, 공동 강사 내보내기는 소유자만 합니다.
              </span>
              <button
                type="button"
                data-testid="co-instructor-invite-create"
                onClick={() => void create()}
                disabled={creating}
                className={buttonClass("secondary", "sm")}
              >
                {creating ? "만드는 중..." : "초대 링크 만들기"}
              </button>
            </div>
            {error ? (
              <div className="px-4">
                <ErrorNote>
                  <span data-testid="co-instructor-invite-error">{error}</span>
                </ErrorNote>
              </div>
            ) : null}
          </div>
        </CardSection>
        {me ? <LeaveSection classId={classId} owner={iAmOwner} /> : null}
      </div>
    </Card>
  );
}
