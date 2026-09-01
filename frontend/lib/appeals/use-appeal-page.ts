"use client";

// 이의 제기 화면의 데이터 (#74).
//
// 이 화면은 **세 가지를 한 번에** 필요로 한다: 무엇에 이의를 제기하는지(채점
// 결과), 이미 제기했는지(이의와 그 심판), 그리고 내 소스가 몇 번 열렸는지(열람
// 기록, ADR-0022). 셋을 따로 부르되 실패는 각각 구분한다 — 열람 기록을 못
// 불러온 것과 채점 결과를 못 불러온 것은 화면이 할 말이 다르다.
//
// **낙관적 갱신을 하지 않는다.** 이의는 한 Submission 에 하나뿐이고 되돌릴 수
// 없다(append-only). 접수됐다고 먼저 그려 놓고 서버가 409 를 내면, 사용자는
// 자기가 낸 적 없는 이의를 봤다고 믿게 된다.
import { useCallback, useEffect, useState } from "react";

import { sessionFetch } from "@/lib/auth/client-fetch";
import type { components } from "@/lib/api/schema.gen";

export type OwnScore = components["schemas"]["OwnScoreOut"];
export type Appeal = components["schemas"]["AppealOut"];
export type SourceReading = components["schemas"]["SourceReadingOut"];

export type AppealPageState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      /** 채점 전이면 없다 — 그때는 이의를 제기할 것 자체가 없다. */
      score: OwnScore | null;
      /** 이미 제기했으면 그 이의. 없으면 폼을 준다. */
      appeal: Appeal | null;
      readings: SourceReading[];
      /** 열람 기록만 따로 실패할 수 있다 — 그때도 나머지는 보여준다. */
      readingsFailed: boolean;
    };

async function readJson<T>(path: string): Promise<{ ok: true; value: T } | { ok: false; status: number }> {
  const response = await sessionFetch(path, { cache: "no-store" });
  if (!response.ok) return { ok: false, status: response.status };
  return { ok: true, value: (await response.json()) as T };
}

export function useAppealPage(submissionId: string): {
  state: AppealPageState;
  reload: () => void;
} {
  const [state, setState] = useState<AppealPageState>({ status: "loading" });
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const [score, appeal, readings] = await Promise.all([
          readJson<OwnScore>(`/api/backend/submissions/${submissionId}/score`),
          readJson<Appeal>(`/api/backend/submissions/${submissionId}/appeal`),
          readJson<{ items: SourceReading[] }>(
            `/api/backend/submissions/${submissionId}/source-readings`,
          ),
        ]);
        if (cancelled) return;

        // 404 는 실패가 아니다 — "아직 채점 안 됐다"·"아직 이의가 없다"는 둘 다
        // 정상적인 사실이다. 그 밖의 실패(403·500)는 화면 전체가 실패한 것이다.
        if (!score.ok && score.status !== 404) return setState({ status: "error" });
        if (!appeal.ok && appeal.status !== 404) return setState({ status: "error" });

        setState({
          status: "ready",
          score: score.ok ? score.value : null,
          appeal: appeal.ok ? appeal.value : null,
          readings: readings.ok ? readings.value.items : [],
          readingsFailed: !readings.ok,
        });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [submissionId, nonce]);

  return { state, reload };
}

/** 이의를 접수한다. 실패하면 서버가 준 문구를 그대로 돌려준다 — 기한이 지났다·
 * 이미 냈다는 각각 다른 사실이고, 화면이 그것을 짐작해 다시 쓰면 갈라진다. */
export async function submitAppeal(
  submissionId: string,
  reason: string,
): Promise<{ ok: true } | { ok: false; message: string }> {
  const response = await sessionFetch(`/api/backend/submissions/${submissionId}/appeal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });

  if (response.status === 201) return { ok: true };

  const detail = await response
    .json()
    .then((body: { detail?: string }) => body.detail)
    .catch(() => undefined);
  return { ok: false, message: detail ?? "이의를 접수하지 못했습니다. 잠시 후 다시 시도해주세요." };
}
