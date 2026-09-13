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
import { dangerButtonClass } from "@/lib/ui";
import { acceptHandover, useHandover, type Handover } from "@/lib/handovers/use-handover";
import {
  buildAssetKindLabel,
  useBuildAssets,
  type BuildAssetsState,
} from "@/lib/handovers/use-build-assets";

type AcceptState = { status: "idle" | "confirming" | "saving" | "error"; message?: string };

export default function HandoverPage({ params }: { params: Promise<{ contestId: string }> }) {
  const { contestId } = use(params);
  const session = useSession();
  const { state } = useHandover(contestId);
  const [accept, setAccept] = useState<AcceptState>({ status: "idle" });
  // POST /handover/accept 가 이미 최신 Handover 를 돌려준다 — 그 값을 직접
  // 반영한다. reload()로 다시 GET을 걸면, 그 응답이 오기 전까지 화면이 잠깐
  // 옛 pending_acceptance 상태로 되돌아가 "확인이 씹혔나?" 로 보이고, 하필
  // 그 재조회가 실패하면 **성공한, 되돌릴 수 없는 확인**을 조회 실패 문구로
  // 덮어버린다(코드리뷰 지적) — 서버가 이미 answer를 줬으므로 다시 묻지 않는다.
  const [acceptedHandover, setAcceptedHandover] = useState<Handover | null>(null);
  const displayedHandover =
    acceptedHandover ?? (state.status === "ready" ? state.handover : null);

  // Handover 조회가 끝나야 어느 Submission의 빌드 자산인지 안다 — 그 전까지는
  // null을 줘 훅이 요청을 보내지 않는다(hook 순서를 지키려 조건부로 부르지
  // 않는다).
  const submissionId = displayedHandover?.submission_id ?? null;
  const buildAssets = useBuildAssets(submissionId);

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
      <Link className="text-sm text-ink/60" href="/console/contests" data-testid="handover-back">
        ← 내 공모전
      </Link>
      <h1 className="mt-2 text-2xl font-semibold" data-testid="handover-heading">
        인수 확인
      </h1>

      {displayedHandover !== null ? (
        <>
          {displayedHandover.status === "released" ? (
            <ReleasedNotice handover={displayedHandover} />
          ) : (
            <PendingAcceptance
              handover={displayedHandover}
              accept={accept}
              onAcceptClick={() => setAccept({ status: "confirming" })}
              onCancel={() => setAccept({ status: "idle" })}
              onConfirm={handleAccept}
            />
          )}

          {/* #180 — 무엇을 받았다는 확인인지 보여준다. 자료가 없어도 확인은
              막지 않는다(그 규율은 백엔드에 이미 있다 — 이 목록은 안내일
              뿐, 인수 확인 버튼의 활성 조건이 아니다). */}
          <BuildAssetsSection state={buildAssets.state} />
        </>
      ) : state.status === "not-found" ? (
        <p className="mt-6" data-testid="handover-not-found">
          이 공모전은 아직 선정되지 않아 인수 정보가 없습니다.
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

function BuildAssetsSection({ state }: { state: BuildAssetsState }) {
  if (state.status === "loading") return null;
  if (state.status === "forbidden") return null;
  if (state.status === "error") {
    // 조회 실패와 "아직 안 올렸다"는 다른 사실이다 — 같아 보이면 Sponsor는
    // 자료가 없다고 믿고 확인 버튼을 누르게 된다(위 handover-error와 같은
    // 원칙). 조용히 섹션 자체를 지우지 않는다.
    return (
      <p className="mt-8 text-sm text-attention" role="alert" data-testid="handover-build-assets-error">
        빌드 자산 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  return (
    <section className="mt-8 border-t border-rule pt-6" data-testid="handover-build-assets">
      <h2 className="text-lg font-semibold">개발자가 올린 빌드 자산</h2>
      {state.assets.length === 0 ? (
        <p className="mt-2 text-sm text-ink/60" data-testid="handover-build-assets-empty">
          아직 올린 빌드 자산이 없습니다 — 없어도 인수 확인에는 영향이 없습니다.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2" data-testid="handover-build-assets-list">
          {state.assets.map((asset) => (
            <li
              key={asset.id}
              className="rounded border border-rule p-3 text-sm"
              data-testid={`handover-build-asset-${asset.id}`}
            >
              <span className="rounded-sm border border-rule px-2 py-0.5 text-xs">
                {buildAssetKindLabel(asset.kind)}
              </span>{" "}
              {asset.label || <span className="text-ink/60">(라벨 없음)</span>}
              <p className="mt-1 font-mono text-xs text-ink/60">{asset.object_key}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ReleasedNotice({ handover }: { handover: Handover }) {
  const via =
    handover.released_via === "timeout"
      ? "확인 없이 기한이 지나 자동으로"
      : "직접 확인해";
  const releasedAt = handover.released_at
    ? new Date(handover.released_at).toLocaleString("ko-KR")
    : "";

  return (
    <p className="mt-6 font-semibold text-verified" data-testid="handover-released">
      {via} 예치금이 해제되었습니다{releasedAt ? ` (${releasedAt})` : ""} — 개발자에게 상금이
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
        인수를 확인하면 <strong>예치금이 해제되어 개발자에게 상금이 지급됩니다</strong> — 되돌릴
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
          className={`w-fit rounded px-4 py-2 disabled:opacity-50 ${dangerButtonClass("outline")}`}
          data-testid="handover-accept-button"
        >
          인수 확인
        </button>
      ) : (
        <div className="flex flex-col gap-2 rounded border border-attention p-4">
          <p data-testid="handover-accept-confirm-notice">
            정말 확인하시겠습니까? 예치금이 즉시 해제되며 되돌릴 수 없습니다.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onConfirm}
              disabled={isSaving}
              className="rounded border border-attention bg-attention px-3 py-2 text-sm text-paper disabled:opacity-50"
              data-testid="handover-accept-confirm"
            >
              {isSaving ? "확인하는 중..." : "확인 — 예치금 해제"}
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
