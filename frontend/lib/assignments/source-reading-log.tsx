"use client";

// 제출자가 자기 제출물의 소스 열람 기록을 본다 (#211, ADR-0022/0028).
//
// 기록만 남기고 아무도 읽지 않으면 이 저장소가 반복해 겪은 "쓰기만 하고 소비처가
// 없는 필드"가 된다(ADR-0022) — 이 컴포넌트가 그 소비처다. 누가 봤는지는 보여주지
// 않는다(백엔드 `AssignmentSourceReadingOut`에 애초에 없다) — 시각과 횟수만으로
// "출제자가 몇 번 열어봤다"는 약속을 검증할 수 있다.
import { useBackendQuery } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";
import type { AssignmentSourceReadingOut } from "@/lib/submissions/types";

export function AssignmentSourceReadingLog({ submissionId }: { submissionId: number }) {
  const { state } = useBackendQuery<AssignmentSourceReadingOut[]>(
    bffClient,
    `/api/backend/submissions/${submissionId}/assignment-source-readings`,
  );

  return (
    <section
      className="border border-rule p-4 text-sm text-ink/80"
      data-testid="assignment-source-reading-log"
    >
      <p className="font-medium">출제자의 소스 열람 기록</p>
      {state.status === "loading" && (
        <p className="mt-1 text-xs text-ink/60" data-testid="assignment-source-reading-log-loading">
          불러오는 중...
        </p>
      )}
      {state.status === "error" && (
        <p role="alert" className="mt-1 text-xs text-attention" data-testid="assignment-source-reading-log-error">
          열람 기록을 불러오지 못했습니다.
        </p>
      )}
      {state.status === "ready" && state.data.length === 0 && (
        <p className="mt-1 text-xs text-ink/60" data-testid="assignment-source-reading-log-empty">
          아직 출제자가 소스를 열람하지 않았습니다.
        </p>
      )}
      {state.status === "ready" && state.data.length > 0 && (
        <ul className="mt-1 flex flex-col gap-1" data-testid="assignment-source-reading-log-list">
          {state.data.map((reading, index) => (
            <li key={index} className="text-xs font-mono" data-testid="assignment-source-reading-entry">
              {new Date(reading.read_at).toLocaleString("ko-KR")}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
