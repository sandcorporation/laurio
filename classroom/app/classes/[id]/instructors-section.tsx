"use client";

// 클래스 관리의 「강사」 영역(#561·#562, CONTEXT.md 「공동 강사」·「공동 강사 초대」).
// 이 클래스를 함께 가르치는 사람들(소유자 먼저, 그다음 공동 강사를 수락한 순서로)과
// 아직 쓰이지 않은 공동 강사 초대를 보여 준다. 초대는 소유자 전용이 아니다 — 강사 누구나
// 만들고, 누가 만든 초대든 복사하고 취소한다. 보관된 클래스에서도 된다(사람을 들이는 일은
// 클래스의 존폐 쪽이다). 여러 개를 만들어도 앞의 것이 죽지 않는다 — 가입 링크의
// 「다시 뽑기」와 다르다.
import { useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { Badge, Card, CardHeader, CardSection, ErrorNote, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import {
  cancelCoInstructorInvite,
  classInstructorsPath,
  coInstructorInviteUrl,
  createCoInstructorInvite,
  pendingCoInstructorInvitesPath,
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

function InstructorRow({ instructor }: { instructor: ClassInstructor }) {
  const owner = instructor.role === "owner";
  return (
    <li data-testid="class-instructor-row" className="flex flex-wrap items-center gap-x-2.5 gap-y-1 px-4 py-2.5">
      <span data-testid="class-instructor-name" className="text-[13.5px]">
        {instructor.display_name || (owner ? "이름을 정하지 않은 소유자" : "이름 없음")}
      </span>
      {instructor.is_me ? <span className="text-[12px] text-ink/45">나</span> : null}
      <span data-testid="class-instructor-role">
        <Badge tone={owner ? "verified" : "neutral"}>{owner ? "소유자" : "공동 강사"}</Badge>
      </span>
      {instructor.accepted_at ? (
        <span className="ml-auto text-[12px] text-ink/45">
          {formatWhen(instructor.accepted_at)} 수락
        </span>
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

export function InstructorsSection({ classId }: { classId: number }) {
  const { state: rosterState } = useBackendQuery<ClassInstructor[]>(bffClient, classInstructorsPath(classId));
  const { state: invitesState, reload: reloadInvites } = useBackendQuery<PendingCoInstructorInvite[]>(
    bffClient,
    pendingCoInstructorInvitesPath(classId),
  );
  const [creating, setCreating] = useState(false);
  const [cancellingId, setCancellingId] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

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
            {rosterState.data.map((instructor, index) => (
              <InstructorRow key={index} instructor={instructor} />
            ))}
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
                문제·명단·보관을 소유자와 똑같이 다루고, 채점 키·예산과 클래스 삭제는 소유자만 합니다.
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
      </div>
    </Card>
  );
}
