"use client";

// 받는 공동 강사에게 온 소유권 이전 요청(#564, CONTEXT.md 「소유권 이전」). 클래스 화면 맨 위에서
// 무엇을 떠안는지 — 채점 키가 비워지고, 키를 넣을 때까지 채점이 멈추고, 사용량은 남고, 지금
// 소유자는 공동 강사로 남는다 — 를 말한 뒤 넘겨받거나 거절하게 한다. 받는 사람에게만 그린다.
import Link from "next/link";
import { useEffect, useId, useRef, useState, type RefObject } from "react";

import { Card, CardHeader, ErrorNote, Note, buttonClass } from "@/app/components/ui";
import type { PendingOwnershipTransfer } from "@/lib/classes/api";
import { takenOverNoteText } from "@/lib/co-instructors/transfer-notes";
import { acceptOwnershipTransfer, declineOwnershipTransfer } from "@/lib/co-instructors/api";

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function OwnershipTransferOffer({
  classId,
  transfer,
  ownerName,
  sectionRef,
  onDone,
}: {
  classId: number;
  transfer: PendingOwnershipTransfer;
  // 지금 소유자가 이 클래스에서 불리는 강사 이름 — 비어 있으면 「소유자」.
  ownerName: string;
  // 카드가 나타났을 때 초점을 받는 자리(#1490) — 열린 쪽이 초점이 갈 곳을 정한다.
  sectionRef: RefObject<HTMLElement | null>;
  onDone: (accepted: boolean) => void;
}) {
  const introId = useId();
  const [busy, setBusy] = useState<"accept" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 이름이 없으면 조사가 달라진다(님이/님은 · 소유자가/소유자는).
  const ownerSubject = ownerName ? `${ownerName}님이` : "소유자가";
  const ownerTopic = ownerName ? `${ownerName}님은` : "지금 소유자는";

  async function answer(accept: boolean) {
    setBusy(accept ? "accept" : "decline");
    setError(null);
    const result = accept
      ? await acceptOwnershipTransfer(classId, transfer.id)
      : await declineOwnershipTransfer(classId, transfer.id);
    setBusy(null);
    if (!result.ok) {
      setError(result.detail);
      return;
    }
    onDone(accept);
  }

  return (
    <section
      ref={sectionRef}
      aria-label="소유권 이전 요청"
      aria-describedby={introId}
      tabIndex={-1}
      className="outline-none focus-visible:ring-2 focus-visible:ring-ink/40"
    >
    <Card>
      <CardHeader title="소유권 이전 요청" hint={`${formatWhen(transfer.expires_at)}까지 답할 수 있습니다`} />
      <div data-testid="ownership-transfer-offer" className="flex flex-col gap-3 px-4 py-4">
        <p id={introId} className="text-[13.5px] leading-relaxed">
          {ownerSubject} 이 클래스의 소유권을 나에게 넘기려 합니다. 넘겨받으면 이렇게 됩니다.
        </p>
        <ul className="flex list-disc flex-col gap-1 pl-5 text-[12.5px] leading-relaxed text-ink/70">
          <li>
            지금 채점 키가 비워집니다. 내 채점 키를 넣을 때까지 참여자의 제출은 채점되지 않고 기다렸다가, 키를
            넣으면 이어서 채점됩니다. 채점 비용은 내 키로 나갑니다.
          </li>
          <li>지금까지 쓴 양은 그대로 남습니다.</li>
          <li>채점 키, 클래스 삭제, 소유권 이전, 공동 강사 내보내기를 내가 맡습니다.</li>
          <li>{ownerTopic} 공동 강사로 남습니다.</li>
        </ul>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="ownership-transfer-accept"
            onClick={() => void answer(true)}
            disabled={busy !== null}
            className={buttonClass("primary", "sm")}
          >
            {busy === "accept" ? "넘겨받는 중..." : "넘겨받기"}
          </button>
          <button
            type="button"
            data-testid="ownership-transfer-decline"
            onClick={() => void answer(false)}
            disabled={busy !== null}
            className={buttonClass("secondary", "sm")}
          >
            {busy === "decline" ? "거절하는 중..." : "거절하기"}
          </button>
        </div>
        {error ? (
          <ErrorNote>
            <span data-testid="ownership-transfer-offer-error">{error}</span>
          </ErrorNote>
        ) : null}
      </div>
    </Card>
    </section>
  );
}

/** 답한 뒤 누른 단추가 사라진다 — 결과 문구가 읽히고 초점도 받는다(#1435). */
function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return ref;
}

/** 방금 넘겨받은 사람에게 한 번 보이는 안내 — 다음에 할 일(채점 키 넣기)로 가는 길을 준다. */
export function OwnershipTransferAcceptedNote({ classId }: { classId: number }) {
  const ref = useFocusOnMount<HTMLDivElement>();
  return (
    <div ref={ref} role="status" tabIndex={-1} className="outline-none focus-visible:ring-2 focus-visible:ring-ink/40">
    <Note>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span data-testid="ownership-transfer-accepted-note" className="flex-1">
          이제 이 클래스의 소유자입니다. 내 채점 키를 넣으면 기다리던 제출이 채점됩니다.
        </span>
        <Link
          href={`/classes/${classId}/settings#scoring-key`}
          data-testid="ownership-transfer-accepted-key-link"
          className={buttonClass("primary", "sm")}
        >
          채점 키 넣기
        </Link>
      </div>
    </Note>
    </div>
  );
}

/** 거절한 사람에게 한 번 보이는 한 줄 — 카드가 사라진 자리에서 결과를 읽는다. */
export function OwnershipTransferDeclinedNote() {
  const ref = useFocusOnMount<HTMLDivElement>();
  return (
    <div ref={ref} role="status" tabIndex={-1} className="outline-none focus-visible:ring-2 focus-visible:ring-ink/40">
      <Note>
        <span data-testid="ownership-transfer-declined-note">소유권 이전 요청을 거절했습니다. 소유권은 그대로입니다.</span>
      </Note>
    </div>
  );
}

/** 소유자 화면에서 소유권이 이미 넘어갔음을 말한다 — 눌렀던 「요청 취소」가 사라진 자리에서 읽히고 초점을 받는다(#1441). */
export function OwnershipTransferTakenNote({ newOwnerName, afterCancelAttempt }: { newOwnerName: string; afterCancelAttempt: boolean }) {
  const ref = useFocusOnMount<HTMLDivElement>();
  return (
    <div ref={ref} role="status" tabIndex={-1} className="outline-none focus-visible:ring-2 focus-visible:ring-ink/40">
      <Note>
        <span data-testid="ownership-transfer-taken-note">{takenOverNoteText(newOwnerName, afterCancelAttempt)}</span>
      </Note>
    </div>
  );
}
