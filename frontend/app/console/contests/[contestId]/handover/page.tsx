"use client";

// 인수 확인 화면 (#179, #14) — Sponsor가 Award 이후 인수를 확인해 Escrow를
// 해제한다.
//
// Award 직후 「내 공모전」은 Sponsor에게 「내 차례 · 인수를 확인하세요」라고
// 정확히 말했지만, 그 문구 옆에 갈 곳이 없었다 — 상태 라벨은 있는데 링크가
// 그려지지 않아 안내가 막다른 길이었다. 이 화면이 그 자리다.
//
// **확인은 상금을 내보내는, 되돌릴 수 없는 행위다.** Award가 「정말
// 선정하시겠습니까? 되돌릴 수 없습니다」라는 확인 단계를 두는 것과 같은 무게로
// 다룬다(judge/page.tsx의 award-confirm과 같은 2단계 패턴) — 실수로 누른
// 클릭 하나가 Escrow를 되돌릴 수 없이 비운다.
//
// **자동 해제가 있다는 사실을 숨기지 않는다.** 확인하지 않아도 기한이 지나면
// 스캔이 자동으로 해제한다(handovers.scans) — 방치가 상금을 Sponsor에게
// 돌려주지 않는다는 것을, 심사 화면의 무응답 배분 경고와 같은 규율로 미리
// 말한다.
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015).
import Link from "next/link";
import { use, useState } from "react";

import { useSession } from "@/lib/auth/use-session";
import { acceptHandover, useHandover, type Handover } from "@/lib/handovers/use-handover";

type AcceptState = { status: "idle" | "confirming" | "saving" | "error"; message?: string };

export default function HandoverPage({ params }: { params: Promise<{ contestId: string }> }) {
  const { contestId } = use(params);
  const session = useSession();
  const { state } = useHandover(contestId);
  const [accept, setAccept] = useState<AcceptState>({ status: "idle" });
  // POST /handover/accept 가 이미 최신 Handover 를 돌려준다 — 그 값을 직접
  // 반영한다. 다시 GET 을 걸면, 그 응답이 오기 전까지 화면이 잠깐 옛
  // pending_acceptance 상태로 되돌아가 "확인이 씹혔나?" 로 보이고, 하필 그
  // 재조회가 실패하면 **성공한, 되돌릴 수 없는 확인**을 조회 실패 문구로
  // 덮어버린다 — 서버가 이미 답을 줬으므로 다시 묻지 않는다.
  const [acceptedHandover, setAcceptedHandover] = useState<Handover | null>(null);
  const displayedHandover =
    acceptedHandover ?? (state.status === "ready" ? state.handover : null);

  // 세션 만료를 로딩 게이트보다 먼저 본다(#69).
  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || (state.status === "loading" && displayedHandover === null)) {
    return (
      <main className="p-10">
        <p data-testid="handover-loading">불러오는 중...</p>
      </main>
    );
  }

  async function handleAccept() {
    setAccept({ status: "saving" });
    const result = await acceptHandover(contestId);
    if (!result.ok) {
      setAccept({ status: "error", message: result.message });
      return;
    }
    setAccept({ status: "idle" });
    setAcceptedHandover(result.handover);
  }

  return (
    <main className="mx-auto max-w-2xl p-10">
      <Link className="text-sm text-muted" href="/console/contests" data-testid="handover-back">
        ← 내 공모전
      </Link>
      <h1 className="mt-2 text-2xl font-semibold" data-testid="handover-heading">
        인수 확인
      </h1>

      {displayedHandover !== null ? (
        displayedHandover.status === "released" ? (
          <ReleasedNotice handover={displayedHandover} />
        ) : (
          <PendingAcceptance
            handover={displayedHandover}
            accept={accept}
            onAcceptClick={() => setAccept({ status: "confirming" })}
            onCancel={() => setAccept({ status: "idle" })}
            onConfirm={handleAccept}
          />
        )
      ) : state.status === "not-found" ? (
        <p className="mt-6" data-testid="handover-not-found">
          이 공모전은 아직 Award되지 않아 인수 정보가 없습니다.
        </p>
      ) : state.status === "forbidden" ? (
        <p className="mt-6 text-attention" role="alert" data-testid="handover-forbidden">
          {state.message}
        </p>
      ) : (
        <p className="mt-6 text-attention" role="alert" data-testid="handover-error">
          인수 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}
    </main>
  );
}

function ReleasedNotice({ handover }: { handover: Handover }) {
  const via = handover.released_via === "timeout" ? "확인 없이 기한이 지나 자동으로" : "직접 확인해";
  const releasedAt = handover.released_at
    ? new Date(handover.released_at).toLocaleString("ko-KR")
    : "";

  return (
    <p className="mt-6 font-semibold text-verified" data-testid="handover-released">
      {via} Escrow가 해제되었습니다{releasedAt ? ` (${releasedAt})` : ""} — 개발자에게 상금이
      지급됩니다.
    </p>
  );
}

function PendingAcceptance({
  handover,
  accept,
  onAcceptClick,
  onCancel,
  onConfirm,
}: {
  handover: Handover;
  accept: AcceptState;
  onAcceptClick: () => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const deadline = new Date(handover.release_deadline_at).toLocaleString("ko-KR");
  const isConfirming = accept.status === "confirming";
  const isSaving = accept.status === "saving";

  return (
    <div className="mt-6 flex flex-col gap-4">
      <p data-testid="handover-pending-notice">
        인수를 확인하면 <strong>Escrow가 해제되어 개발자에게 상금이 지급됩니다</strong> — 되돌릴
        수 없습니다.
      </p>

      {/* 자동 해제가 있다는 사실을 숨기지 않는다 — 확인하지 않아도 상금이
          영구히 묶이지 않는다는 것을 안내한다(심사 화면의 무응답 배분 경고와
          같은 규율). */}
      <p className="text-sm text-ink" data-testid="handover-deadline-notice">
        확인하지 않아도 {deadline}에 자동으로 해제됩니다 — 방치해도 개발자의 상금이
        영구히 묶이지 않습니다.
      </p>

      {!isConfirming ? (
        <button
          type="button"
          onClick={onAcceptClick}
          className="w-fit rounded bg-accent px-4 py-2 text-white disabled:opacity-50"
          data-testid="handover-accept-button"
        >
          인수 확인
        </button>
      ) : (
        <div className="flex flex-col gap-2 rounded border border-attention p-4">
          <p data-testid="handover-accept-confirm-notice">
            정말 확인하시겠습니까? Escrow가 즉시 해제되며 되돌릴 수 없습니다.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onConfirm}
              disabled={isSaving}
              className="rounded border border-attention bg-attention px-3 py-2 text-sm text-paper disabled:opacity-50"
              data-testid="handover-accept-confirm"
            >
              {isSaving ? "확인하는 중..." : "확인 — Escrow 해제"}
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={isSaving}
              className="rounded border border-rule px-3 py-2 text-sm hover:border-ink"
              data-testid="handover-accept-cancel"
            >
              취소
            </button>
          </div>
        </div>
      )}

      {accept.status === "error" ? (
        <p role="alert" className="text-attention" data-testid="handover-accept-error">
          {accept.message}
        </p>
      ) : null}
    </div>
  );
}
