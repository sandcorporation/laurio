"use client";

// 출제자가 마감 전에도 제출 소스를 펼쳐 본다 (#211, ADR-0022/0028).
//
// **목록·상세를 훑는 것만으로는 소스가 보이지 않는다.** 제출 목록(`GET /assignments/
// {id}/submissions`)은 소스를 아예 담지 않는다 — 「펼치기」 버튼을 눌러야만
// `POST /assignments/{id}/submissions/{submissionId}/source`가 나가고, 그 요청 하나가
// 서버에 `AssignmentSourceReading`을 남긴다(ADR-0022가 Operator에 대해 세운 것과
// 같은 모양). 공모전과 달리 Award가 없어 감출 근거 자체가 없지만(ADR-0028), 대신
// "펼치는 행위"가 있어야 그 기록이 신호가 된다는 규율은 그대로 따른다.
//
// **이 파일은 목록을 그리지 않는다 — 행 하나에 붙는 조각이다.** #211이 병렬로
// 개발되던 동안 제출 목록 섹션을 통째로 갖고 있었는데, #210도 같은 화면에 Score를
// 실은 목록을 만들어 두 목록이 한 페이지에 겹쳤다. 통합에서 목록은 #210의 것
// 하나로 합치고(그쪽이 Score까지 실은 상위집합이다), 펼치기만 여기 남겼다.
import { useState } from "react";

import { bffClient } from "@/lib/bff/client";
import type { AssignmentSourceRevealOut } from "@/lib/submissions/types";

type RevealState =
  | { status: "idle" }
  | { status: "revealing" }
  | { status: "revealed"; data: AssignmentSourceRevealOut }
  | { status: "error"; message: string };

export function AssignmentSourceReveal({
  assignmentId,
  submissionId,
}: {
  assignmentId: string;
  submissionId: number;
}) {
  const [reveal, setReveal] = useState<RevealState>({ status: "idle" });

  async function handleReveal() {
    setReveal({ status: "revealing" });
    const response = await bffClient.post<AssignmentSourceRevealOut>(
      `/api/backend/assignments/${assignmentId}/submissions/${submissionId}/source`,
    );
    if (!response.ok) {
      setReveal({ status: "error", message: response.detail });
      return;
    }
    setReveal({ status: "revealed", data: response.data });
  }

  return (
    <div className="mt-2 flex flex-col gap-2" data-testid="assignment-submission-source">
      {reveal.status !== "revealed" ? (
        <button
          type="button"
          onClick={() => void handleReveal()}
          disabled={reveal.status === "revealing"}
          data-testid="assignment-submission-reveal-source-button"
          className="w-fit border border-ink px-3 py-1.5 text-xs hover:bg-ink hover:text-paper disabled:opacity-50"
        >
          {reveal.status === "revealing" ? "펼치는 중..." : "소스 펼치기"}
        </button>
      ) : null}

      {reveal.status === "idle" || reveal.status === "revealing" ? (
        <p className="text-xs text-ink/60" data-testid="assignment-submission-reveal-notice">
          기본은 접혀 있습니다 — 펼치면 그 열람이 기록되고 제출자가 확인할 수 있습니다.
        </p>
      ) : null}

      {reveal.status === "error" && (
        <p
          role="alert"
          className="text-xs text-attention"
          data-testid="assignment-submission-reveal-error"
        >
          {reveal.message}
        </p>
      )}

      {reveal.status === "revealed" && (
        <div className="flex flex-col gap-1" data-testid="assignment-submission-revealed-assets">
          <p className="text-xs text-verified">펼쳤습니다 — 이 열람이 기록되었습니다.</p>
          <ul className="flex flex-col gap-1">
            {reveal.data.assets.map((asset) => (
              <li
                key={asset.id}
                className="text-xs"
                data-testid={`assignment-source-asset-${asset.id}`}
              >
                <span className="text-ink/60">{asset.label || asset.kind} — </span>
                <a
                  href={asset.url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                  data-testid={`assignment-source-asset-link-${asset.id}`}
                >
                  {asset.kind === "source" ? "다운로드" : asset.url}
                </a>
              </li>
            ))}
          </ul>
          {reveal.data.assets.length === 0 && (
            <p className="text-xs text-ink/60">이 제출에는 아직 소스 자료가 없습니다.</p>
          )}
        </div>
      )}
    </div>
  );
}
