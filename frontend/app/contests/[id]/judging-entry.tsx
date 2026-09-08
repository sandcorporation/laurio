"use client";

// 공개 상세에서 자기 공모전을 연 Sponsor 가 바로 심사로 들어가는 진입점 (#226).
//
// **백엔드는 바뀌지 않는다.** `ContestOut`이 이미 `is_owner`·`status`·
// `judging_ends_at`·`submission_count`를 싣는다(#164, #106, #13) — 이 컴포넌트는
// 그 값을 읽기만 한다.
//
// **패턴은 `submit-cta.tsx`(#164)를 그대로 따른다.** 공개 상세 SSR(ADR-0015)은
// Authorization을 보내지 않으므로 `is_owner`가 서버 렌더 페이로드에는 항상
// `false`로 온다 — 이 컴포넌트가 마운트된 뒤 BFF 프록시를 거쳐 **같은
// 엔드포인트**(`GET /contests/{id}`)를 인증 구역 클라이언트로 다시 불러 진짜
// 값을 읽는다. 그 조회는 익명 방문자에게도 안전하다(auth=None이라 401이 나지
// 않는다 — `bffClient`의 로그인 리다이렉트가 이 마운트만으로 튀지 않는다).
//
// 기본 상태는 "확인 중"이고 아무것도 그리지 않는다 — owner로 확인된 뒤에만
// 내용을 채운다. 그래서 절대다수인 비소유자·익명 방문자에게는 깜빡임 없이
// 계속 아무것도 안 보인다(AC "확인 전 깜빡임으로 잠깐 노출되지도 않는다").
//
// **Score와 소스는 여기서도 다루지 않는다**(ADR-0006, ADR-0014) — 이 컴포넌트가
// 읽는 `ContestOut`에는 애초에 그 필드가 없다. 이 조각이 더하는 것은 "심사
// 화면으로 가는 링크가 지금 눌릴 수 있는가와 왜인가" 하나뿐이다.
import { useEffect, useState } from "react";
import Link from "next/link";

import { bffClient } from "@/lib/bff/client";
import { formatDday } from "@/lib/contest-format";
import type { ContestDetail } from "@/lib/submissions/types";

type LoadState =
  | { status: "checking" }
  | { status: "hidden" }
  | { status: "visible"; contest: ContestDetail };

export function SponsorJudgingEntry({ contestId }: { contestId: number }) {
  const [state, setState] = useState<LoadState>({ status: "checking" });

  useEffect(() => {
    let cancelled = false;
    bffClient.get<ContestDetail>(`/api/backend/contests/${contestId}`).then((res) => {
      if (cancelled) return;
      setState(res.ok && res.data.is_owner ? { status: "visible", contest: res.data } : { status: "hidden" });
    });
    return () => {
      cancelled = true;
    };
  }, [contestId]);

  if (state.status !== "visible") return null;

  const { contest } = state;

  return (
    <section
      data-testid="sponsor-judging-entry"
      data-contest-status={contest.status}
      className="flex flex-col gap-2 border-b border-rule pb-6"
    >
      <h2 className="text-sm font-medium">심사</h2>
      {renderBody(contest)}
    </section>
  );
}

function renderBody(contest: ContestDetail) {
  // CLOSED — 심사기간(마감 + 7일, #13) 안이다. 눌리는 링크와 남은 기간을 함께 보여준다.
  if (contest.status === "closed") {
    return (
      <>
        <Link
          href={`/console/contests/${contest.id}/judge`}
          data-testid="judging-entry-link"
          className="inline-flex w-fit items-center rounded-sm border border-ink bg-ink px-6 py-2.5 text-sm font-medium text-paper hover:bg-ink/90"
        >
          심사하러 가기
        </Link>
        {contest.judging_ends_at && (
          <span data-testid="judging-entry-remaining" className="font-mono text-xs text-ink/60">
            심사기간 종료까지 {formatDday(contest.judging_ends_at)}
          </span>
        )}
      </>
    );
  }

  // AWARDED — 이미 선정을 마쳤다. 링크는 남기지 않는다(AC: "누를 수 없는 링크를
  // 남겨 두지 않는다").
  if (contest.status === "awarded") {
    return (
      <p data-testid="judging-entry-message" className="text-sm text-ink/60">
        이미 참가작을 선정했습니다.
      </p>
    );
  }

  // JUDGING_ENDED — 심사기간이 지나도록 아무도 선정하지 않았다. 링크가 사라지고
  // 그 사실을 말한다(AC).
  if (contest.status === "judging_ended") {
    return (
      <p data-testid="judging-entry-message" className="text-sm text-ink/60">
        심사기간이 종료되어 더 이상 심사할 수 없습니다.
      </p>
    );
  }

  // DRAFT·PUBLISHED(아직 마감 전)와 Assignment 상태(과제에는 심사 화면이 없다,
  // ADR-0028/0029) — 지금 무엇을 기다리는지 말하고 링크는 주지 않는다.
  return (
    <p data-testid="judging-entry-message" className="text-sm text-ink/60">
      공모전이 마감되면 이 자리에서 심사를 시작할 수 있습니다.
    </p>
  );
}
